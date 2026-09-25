"""Risk for the demonstration account: the factor model applied to the book it was built for.

Two populations meet here, as they do at a real asset manager:

* The **estimation universe** - five hundred synthetic stocks over ten years -
  is where the model is estimated and validated. Over the demonstration window
  its world factor, industries and currencies are the Day 2 market's own, so
  the model has seen the moves that drove the book.
* The **coverage universe** - the thirty-six stocks of Meridian World Equity,
  the book's other holdings, the Treasury bond and cash - is what the account
  and its benchmark actually hold. Their exposures are computed from their own
  descriptors on the estimation universe's scale; their specific risks from
  their own residuals. They are *not* shrunk towards the estimation universe's
  size deciles: the backtest showed that prior to be wrong for them (the
  account's mega-caps are more idiosyncratic than the universe's), pulling the
  tracking error forecast a fifth too low. The bond, which
  no equity model explains, gets a time-series beta to the world factor and
  the rest of its variance as specific risk. Cash carries only its currency.

Index funds are looked through to the benchmark's constituents, as in the
attribution: a US index fund is exposure to the North American stocks, a world
fund to all of them. What the look-through does not explain - the fund's
return less its constituents' - is the fund's *basis*, carried as a separate
line with its own specific risk, as production systems carry an ETF's
tracking risk. Leaving it out was the first thing the backtest caught.

Every day of the demonstration window the model forecasts the account's
volatility and tracking error for the next day, using only what was known that
morning; the next day's return is then recorded against it. That is the
backtest of the forecasts the account was actually managed with.
"""

from __future__ import annotations

import logging
import math
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property, lru_cache

import numpy as np

from ..core.exceptions import ValidationError
from ..marketdata.providers.synthetic import demo_market
from ..marketdata.series import TimeSeries
from ..performance.benchmark import BenchmarkDay
from ..performance.contributions import CASH_PREFIX
from ..risk.comparison import Trial, minimum_variance_trials
from ..risk.estimation import FactorReturnHistory, estimate
from ..risk.exposures import historical_beta, standardise_against
from ..risk.factors import BASE_CURRENCY, CURRENCIES, INDUSTRIES, STYLES, WORLD, FactorSet, currency_factor
from ..risk.forecast import ForecastTrack, RollingForecaster
from ..risk.garch import GarchFit, ewma_forecasts, garch_forecasts, rolling_forecasts
from ..risk.model import FactorRiskModel, RiskDecomposition
from ..risk.specific import SPECIFIC_HALF_LIFE, shrink_against
from ..risk.stress import StressResult, historical_scenario, hypothetical_scenarios, run_all
from ..risk.universe import FactorUniverse, Overlay, UniverseHistory
from ..risk.var import RiskEstimate, cornish_fisher, historical, monte_carlo, parametric
from .demo_market import DEMO_END, DEMO_START
from .demo_performance import (
    BOOK_CONSTITUENTS,
    COMPANIONS,
    FUND_SCOPE,
    DemoPerformance,
    build_demo_performance,
    companion_specs,
)

UNIVERSE_SEED = 11
RANDOM_PORTFOLIOS = 30
BOOK_WARM_UP = 90  # valuation days of coverage history before the first scored forecast
CONFIDENCE = 0.99
BOND_ID = "US-T-2032"
TREASURY_PIECE = "TREASURY"
BASIS_SUFFIX = ":basis"

#: Historical windows replayed against today's exposures.
HISTORICAL_SCENARIOS: tuple[tuple[str, date, date, str], ...] = (
    ("February-March 2020", date(2020, 2, 20), date(2020, 3, 23), "The pandemic crash, peak to trough"),
    ("2022 bear market", date(2022, 1, 3), date(2022, 10, 14), "Nine months of falling markets"),
    ("February 2018", date(2018, 2, 1), date(2018, 2, 9), "The volatility spike of early 2018"),
    ("Momentum crash, November 2020", date(2020, 11, 9), date(2020, 11, 13), "Winners sold for value in a week"),
)


@dataclass(frozen=True)
class CoverageAsset:
    asset_id: str
    kind: str  # equity, bond, cash, or basis (a fund's return less its look-through)
    currency: str
    sector: str | None = None
    cap: float = 0.0  # starting market capitalisation in dollars


@dataclass(frozen=True)
class BookForecast:
    """The morning's forecast for one valuation day, and what then happened."""

    day: date
    weekdays: int  # weekdays the return spans (more than one after a holiday)
    volatility: float  # forecast standard deviation of the day's return
    tracking_error: float  # forecast standard deviation of the day's active return
    factor_share: float  # share of forecast variance that is systematic
    realised: float
    active: float

    @property
    def var(self) -> float:
        return parametric(self.volatility, CONFIDENCE).var

    @property
    def exception(self) -> bool:
        return -self.realised > self.var


def _level(series: TimeSeries, day: date) -> float:
    found = series.as_of(day, max_age_days=10)
    if found is None:
        raise ValidationError(f"no total return level on {day}")
    return float(found.value)


def _synthetic_characteristics(asset_id: str) -> tuple[float, float]:
    """Book-to-price and return on equity for a coverage stock: synthetic, but fixed by its identifier."""
    rng = np.random.default_rng(zlib.crc32(asset_id.encode()))
    return float(math.exp(rng.normal(math.log(0.45), 0.5))), float(0.12 + 0.05 * rng.standard_normal())


def overlay_for(performance: DemoPerformance, seed: int = 7) -> Overlay:
    """The Day 2 market's own factors over the demonstration window, for the universe to replay."""
    market = demo_market(seed)
    extra = sorted({spec.sector for spec in companion_specs()})
    draws = market.factor_draws(DEMO_START, DEMO_END, extra_sectors=extra)
    fx_rates = performance.accounting.fx
    fx: dict[str, np.ndarray] = {}
    for code in CURRENCIES:
        levels = np.array([float(fx_rates.rate(code, BASE_CURRENCY, day)) for day in draws.days])
        fx[code] = np.concatenate([[0.0], np.diff(np.log(levels))])
    industries = {name: path for name, path in draws.sectors.items() if name in INDUSTRIES}
    return Overlay(draws.days, draws.market, draws.market_variance, industries, market.sector_vol, fx)


@dataclass
class DemoRisk:
    performance: DemoPerformance
    universe: UniverseHistory
    estimated: FactorReturnHistory
    shrink_coverage: bool = False  # shrink coverage specific risk towards the universe's size deciles
    _cache: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ the coverage universe
    @cached_property
    def factors(self) -> FactorSet:
        return self.estimated.factors

    @cached_property
    def valuation_days(self) -> list[date]:
        return list(self.performance.accounting.valuation_days)

    @cached_property
    def coverage(self) -> dict[str, CoverageAsset]:
        assets: dict[str, CoverageAsset] = {}
        for key, _, sector, _, currency, _, cap in BOOK_CONSTITUENTS:
            assets[key] = CoverageAsset(key, "equity", currency, sector, cap * 1e9)
        for key, _, sector, _, currency, _, cap, *_ in COMPANIONS:
            assets[key] = CoverageAsset(key, "equity", currency, sector, cap * 1e9)
        instruments = self.performance.accounting.instruments
        for day in self.performance.portfolio_days:
            for exposure in day.exposures:
                key = exposure.key
                if key in assets or exposure.is_cash or key in FUND_SCOPE:
                    continue
                instrument = instruments[key]
                if key == BOND_ID:
                    assets[key] = CoverageAsset(key, "bond", "USD")
                else:
                    assets[key] = CoverageAsset(
                        key, "equity", str(instrument.currency), getattr(instrument, "sector", None), 20e9
                    )
        for code in (BASE_CURRENCY, *CURRENCIES):
            assets[f"{CASH_PREFIX}{code}"] = CoverageAsset(f"{CASH_PREFIX}{code}", "cash", code)
        for fund in FUND_SCOPE:
            assets[f"{fund}{BASIS_SUFFIX}"] = CoverageAsset(f"{fund}{BASIS_SUFFIX}", "basis", BASE_CURRENCY)
        return assets

    @cached_property
    def intervals(self) -> list[list[int]]:
        """For each valuation day, the positions in the factor history of the weekdays its return spans."""
        position = {day: index for index, day in enumerate(self.estimated.days)}
        spans: list[list[int]] = [[position[self.valuation_days[0]]]]
        for previous, day in zip(self.valuation_days, self.valuation_days[1:], strict=False):
            spans.append(list(range(position[previous] + 1, position[day] + 1)))
        return spans

    @cached_property
    def factor_returns(self) -> np.ndarray:
        """Factor returns compounded over each valuation day's span (valuation days x K)."""
        return np.vstack([np.prod(1.0 + self.estimated.returns[span], axis=0) - 1.0 for span in self.intervals])

    @cached_property
    def universe_market(self) -> np.ndarray:
        """The estimation universe's cap-weighted local return over each valuation day's span."""
        local, caps, first = self.universe.local_returns, self.universe.caps, self.estimated.first_index
        daily = np.einsum(
            "tn,tn->t", caps[first - 1 : -1] / caps[first - 1 : -1].sum(axis=1, keepdims=True), local[first:]
        )
        return np.array([np.prod(1.0 + daily[span]) - 1.0 for span in self.intervals])

    @cached_property
    def asset_returns(self) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """Each coverage asset's (local, dollar) return on each valuation day; the first day is zero."""
        series = self.performance.total_return_series
        fx = self.performance.accounting.fx
        days = self.valuation_days
        output: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for key, asset in self.coverage.items():
            if asset.kind == "cash":
                continue
            if asset.kind == "bond":
                usd = np.array([0.0] + [self.performance.bond_returns.get(day, 0.0) for day in days[1:]])
                output[key] = (usd, usd)
                continue
            if asset.kind == "basis":
                continue
            levels = np.array([_level(series[key], day) for day in days])
            rates = np.array([float(fx.rate(asset.currency, BASE_CURRENCY, day)) for day in days])
            local = np.concatenate([[0.0], levels[1:] / levels[:-1] - 1.0])
            move = np.concatenate([[0.0], rates[1:] / rates[:-1] - 1.0])
            output[key] = (local, (1.0 + local) * (1.0 + move) - 1.0)
        for fund in FUND_SCOPE:
            levels = np.array([_level(series[fund], day) for day in days])
            basis = np.zeros(len(days))
            for index in range(1, len(days)):
                shares = self._fund_shares(fund, self.performance.benchmark_days[index - 1])
                through = sum(share * output[key][1][index] for key, share in shares.items())
                basis[index] = levels[index] / levels[index - 1] - 1.0 - through
            output[f"{fund}{BASIS_SUFFIX}"] = (basis, basis)
        return output

    # ------------------------------------------------------------------ exposures of the coverage assets
    def _universe_descriptors(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        matrix = self.estimated.exposure_on(self.estimated.position(self.valuation_days[index]))
        assert matrix.raw is not None
        return matrix.raw, matrix.caps

    @cached_property
    def month_anchor(self) -> dict[int, int]:
        """For each monthly exposure key, the first valuation day it is in force: exposures refresh monthly."""
        anchors: dict[int, int] = {}
        for index, day in enumerate(self.valuation_days):
            key = int(self.estimated.exposure_month[self.estimated.position(day)])
            anchors.setdefault(key, max(index, 1))
        return anchors

    def coverage_exposures(self, index: int) -> dict[str, np.ndarray]:
        """Exposures of every coverage asset on the morning of valuation day ``index``, refreshed monthly."""
        key = int(self.estimated.exposure_month[self.estimated.position(self.valuation_days[index])])
        cached: dict[str, np.ndarray] | None = self._cache.get(("exposures", key))
        if cached is not None:
            return cached
        index = self.month_anchor[key]
        raw, caps = self._universe_descriptors(index)
        beta_prior_mean = float((caps / caps.sum()) @ raw[:, 0])
        beta_prior_var = float(np.var(raw[:, 0]))
        count = len(self.factors)
        output: dict[str, np.ndarray] = {}
        equity_raw: dict[str, list[float]] = {}
        market = self.universe_market
        start = max(1, index - 252)
        for asset_id, asset in self.coverage.items():
            vector = np.zeros(count)
            if asset.kind == "basis":
                output[asset_id] = vector
                continue
            if asset.kind == "cash":
                if asset.currency != BASE_CURRENCY:
                    vector[self.factors.index(currency_factor(asset.currency))] = 1.0
                output[asset_id] = vector
                continue
            local, usd = self.asset_returns[asset_id]
            if asset.kind == "bond":
                window = slice(start, index)
                world = self.factor_returns[window, self.factors.index(WORLD)]
                if index - start > 20:
                    beta, _ = historical_beta(usd[window][:, None], world)
                    vector[self.factors.index(WORLD)] = float(beta[0])
                output[asset_id] = vector
                continue
            if index - start > 20:
                beta, error = historical_beta(local[start:index][:, None], market[start:index])
                shrunk = (beta_prior_var * beta[0] + error[0] ** 2 * beta_prior_mean) / (beta_prior_var + error[0] ** 2)
            else:
                shrunk = beta_prior_mean
            cap = asset.cap * float(np.prod(1.0 + usd[1:index]))
            momentum = float(np.sum(np.log1p(local[max(1, index - 252) : max(1, index - 21)])))
            book_to_price, roe = _synthetic_characteristics(asset_id)
            equity_raw[asset_id] = [float(shrunk), math.log(cap), math.log(book_to_price), momentum, roe]
            vector[0] = 1.0
            vector[1 + INDUSTRIES.index(asset.sector or "Industrials")] = 1.0
            if asset.currency != BASE_CURRENCY:
                vector[self.factors.index(currency_factor(asset.currency))] = 1.0
            output[asset_id] = vector
        style_start = 1 + len(INDUSTRIES)
        for asset_id, values in equity_raw.items():
            for k in range(len(STYLES)):
                output[asset_id][style_start + k] = float(
                    standardise_against(np.array([values[k]]), raw[:, k], caps)[0]
                )
        self._cache[("exposures", key)] = output
        return output

    # ------------------------------------------------------------------ weights
    def benchmark_weights(self, index: int) -> dict[str, float]:
        """The policy benchmark's weights at the start of valuation day ``index``."""
        day = self.performance.benchmark_days[index - 1]  # one entry per return day, from the second valuation day
        weights: dict[str, float] = {}
        for piece in day.pieces:
            key = BOND_ID if piece.key == TREASURY_PIECE else f"{CASH_PREFIX}USD" if piece.key == "CASH" else piece.key
            weights[key] = weights.get(key, 0.0) + piece.weight
        return weights

    def portfolio_weights(self, index: int) -> dict[str, float]:
        """The account's weights at the start of valuation day ``index``, index funds looked through."""
        day = self.performance.portfolio_days[index - 1]
        bench = self.performance.benchmark_days[index - 1]
        weights: dict[str, float] = defaultdict(float)
        for exposure in day.exposures:
            weight = day.weight(exposure)
            if exposure.key in FUND_SCOPE:
                for constituent, share in self._fund_shares(exposure.key, bench).items():
                    weights[constituent] += weight * share
                weights[f"{exposure.key}{BASIS_SUFFIX}"] += weight
            else:
                weights[exposure.key] += weight
        return dict(weights)

    def _fund_shares(self, fund_id: str, day: BenchmarkDay) -> dict[str, float]:
        region = FUND_SCOPE[fund_id]
        pieces = [
            piece
            for piece in day.pieces
            if piece.key not in (TREASURY_PIECE, "CASH") and (region is None or piece.region == region)
        ]
        total = sum(piece.weight for piece in pieces)
        return {piece.key: piece.weight / total for piece in pieces}

    # ------------------------------------------------------------------ the daily forecasts
    @cached_property
    def specific_states(self) -> list[dict[str, tuple[float, float]]]:
        """For each valuation day, every asset's EWMA of squared daily specific returns before that day."""
        decay = 0.5 ** (1.0 / SPECIFIC_HALF_LIFE)
        state: dict[str, tuple[float, float]] = {}
        states: list[dict[str, tuple[float, float]]] = [dict(state)]
        for index in range(1, len(self.valuation_days)):
            states.append(dict(state))
            span = len(self.intervals[index])
            exposures = self.coverage_exposures(index)
            for asset_id, (_, usd) in self.asset_returns.items():
                residual = (usd[index] - float(exposures[asset_id] @ self.factor_returns[index])) / math.sqrt(span)
                squares, weight = state.get(asset_id, (0.0, 0.0))
                state[asset_id] = (decay * squares + (1 - decay) * residual**2, decay * weight + (1 - decay))
        return states

    @cached_property
    def book_forecasts(self) -> list[BookForecast]:
        """Every valuation day after the warm-up: the morning's forecasts and the day's outcome."""
        forecaster = RollingForecaster(self.universe, self.estimated)
        days = self.valuation_days
        portfolio_rates = dict(
            zip(self.performance.portfolio_returns.days, self.performance.portfolio_returns.rates, strict=True)
        )
        benchmark_rates = dict(
            zip(self.performance.benchmark_returns.days, self.performance.benchmark_returns.rates, strict=True)
        )
        output: list[BookForecast] = []
        for index in range(BOOK_WARM_UP, len(days)):
            exposures = self.coverage_exposures(index)
            span = len(self.intervals[index])
            position = self.estimated.position(days[index])
            covariance = forecaster.factor_covariance(position)
            specific = self._specific_variances(self.specific_states[index], forecaster, position)
            model = FactorRiskModel(days[index], self.factors, covariance, exposures, specific)
            weights = self.portfolio_weights(index)
            total = model.decompose(weights)
            active_weights = dict(weights)
            for asset, weight in self.benchmark_weights(index).items():
                active_weights[asset] = active_weights.get(asset, 0.0) - weight
            active = model.decompose(active_weights)
            rate, bench = portfolio_rates[days[index]], benchmark_rates[days[index]]
            scale = math.sqrt(span)
            output.append(
                BookForecast(
                    days[index], span, total.daily * scale, active.daily * scale, total.factor_share, rate, rate - bench
                )
            )
        return output

    def _specific_variances(
        self, state: dict[str, tuple[float, float]], forecaster: RollingForecaster, position: int
    ) -> dict[str, float]:
        caps = self.universe.caps[self.estimated.first_index + position - 1]
        universe_vols = np.sqrt(forecaster.specific.variances(caps))
        output: dict[str, float] = {}
        for asset_id, asset in self.coverage.items():
            if asset.kind == "cash":
                output[asset_id] = 0.0
                continue
            squares, weight = state[asset_id]
            vol = math.sqrt(squares / weight)
            if asset.kind == "equity" and self.shrink_coverage:
                vol = shrink_against(vol, asset.cap, universe_vols, caps)
            output[asset_id] = vol**2
        return output

    # ------------------------------------------------------------------ as of the last day
    @cached_property
    def model(self) -> FactorRiskModel:
        """The model on the last morning of the demonstration: what the risk report shows."""
        index = len(self.valuation_days) - 1
        forecaster = RollingForecaster(self.universe, self.estimated)
        position = self.estimated.position(self.valuation_days[index])
        exposures = self.coverage_exposures(index)
        covariance = forecaster.factor_covariance(position)
        specific = self._specific_variances(self.specific_states[index], forecaster, position)
        return FactorRiskModel(
            self.valuation_days[index],
            self.factors,
            covariance,
            exposures,
            specific,
            "EWMA factor covariance (42-day volatilities, 200-day correlations)",
        )

    @property
    def last(self) -> int:
        return len(self.valuation_days) - 1

    @cached_property
    def portfolio(self) -> RiskDecomposition:
        return self.model.decompose(self.portfolio_weights(self.last))

    @cached_property
    def benchmark(self) -> RiskDecomposition:
        return self.model.decompose(self.benchmark_weights(self.last))

    @cached_property
    def active_weights(self) -> dict[str, float]:
        weights = dict(self.portfolio_weights(self.last))
        for asset, weight in self.benchmark_weights(self.last).items():
            weights[asset] = weights.get(asset, 0.0) - weight
        return weights

    @cached_property
    def active(self) -> RiskDecomposition:
        return self.model.decompose(self.active_weights)

    @cached_property
    def holdings_history(self) -> np.ndarray:
        """Today's holdings applied to every past valuation day's asset returns: the scenarios of historical VaR."""
        weights = self.portfolio_weights(self.last)
        rows = np.zeros(len(self.valuation_days) - 1)
        for asset, weight in weights.items():
            if asset in self.asset_returns:
                rows += weight * self.asset_returns[asset][1][1:]
        return rows

    @cached_property
    def var_estimates(self) -> list[RiskEstimate]:
        sigma = self.portfolio.daily
        history = self.holdings_history
        centred = history - history.mean()
        skew = float(np.mean(centred**3) / np.std(history) ** 3)
        kurt = float(np.mean(centred**4) / np.std(history) ** 4 - 3.0)
        weights = self.portfolio_weights(self.last)
        assets = tuple(asset for asset in weights if weights[asset] != 0)
        estimate_mc, _ = self.monte_carlo
        return (
            [
                parametric(sigma, CONFIDENCE),
                cornish_fisher(sigma, skew, kurt, CONFIDENCE),
                historical(history, CONFIDENCE),
                estimate_mc,
            ]
            if assets
            else []
        )

    @cached_property
    def monte_carlo(self) -> tuple[RiskEstimate, np.ndarray]:
        weights = self.portfolio_weights(self.last)
        assets = tuple(asset for asset in weights if weights[asset] != 0)
        return monte_carlo(
            self.model.exposure_matrix(assets),
            self.model.factor_covariance,
            np.array([self.model.specific_variance[asset] for asset in assets]),
            np.array([weights[asset] for asset in assets]),
            confidence=CONFIDENCE,
        )

    @cached_property
    def stress(self) -> list[StressResult]:
        scenarios = [historical_scenario(self.estimated, *item) for item in HISTORICAL_SCENARIOS]
        scenarios += hypothetical_scenarios()
        return run_all(scenarios, self.factors, self.portfolio.exposures, self.benchmark.exposures)

    # ------------------------------------------------------------------ validation on the estimation universe
    @cached_property
    def validation_forecaster(self) -> RollingForecaster:
        return RollingForecaster(self.universe, self.estimated)

    @cached_property
    def universe_tracks(self) -> dict[str, ForecastTrack]:
        """The cap-weighted market and random portfolios, forecast every day for nine years."""
        history = self.universe
        rng = np.random.default_rng(2026)
        count = len(history.stocks)
        rules = {"Cap-weighted market": lambda grid: history.caps[grid - 1] / history.caps[grid - 1].sum()}
        for number in range(RANDOM_PORTFOLIOS):
            weights = np.zeros(count)
            weights[rng.choice(count, 40, replace=False)] = 1 / 40
            rules[f"Random {number + 1}"] = (lambda fixed: lambda grid: fixed)(weights)
        return RollingForecaster(history, self.estimated).run(rules)

    @cached_property
    def factor_z(self) -> dict[str, np.ndarray]:
        return RollingForecaster(self.universe, self.estimated).factor_z_scores()

    @cached_property
    def factor_z_sample(self) -> dict[str, np.ndarray]:
        return RollingForecaster(self.universe, self.estimated).factor_z_scores(method="sample")

    @cached_property
    def specific_z(self) -> np.ndarray:
        return RollingForecaster(self.universe, self.estimated).specific_z_scores()

    @cached_property
    def specific_z_raw(self) -> np.ndarray:
        return RollingForecaster(self.universe, self.estimated).specific_z_scores(shrink=False)

    @cached_property
    def world_volatility(self) -> dict[str, np.ndarray]:
        """One-day-ahead forecasts of the world factor's volatility by each method, and the truth."""
        returns = self.estimated.factor(WORLD)
        first = self.estimated.first_index
        garch, fits = garch_forecasts(returns)
        self._cache["garch fits"] = fits
        return {
            "Truth": np.sqrt(self.universe.true_factor_variance[WORLD][first:]),
            "GARCH(1,1)": garch,
            "EWMA (42-day half-life)": ewma_forecasts(returns, 42),
            "Equal-weighted 252 days": rolling_forecasts(returns),
        }

    @property
    def garch_fits(self) -> list[GarchFit]:
        _ = self.world_volatility
        fits: list[GarchFit] = self._cache["garch fits"]
        return fits

    @cached_property
    def market_truth_z(self) -> np.ndarray:
        """The Day 2 market factor over its own true conditional volatility, on the scored days.

        The yardstick for the book's bias statistic: a forecaster that knew the
        market's true risk every day would score this over the same window.
        """
        draws = demo_market(7).factor_draws(DEMO_START, DEMO_END)
        z = draws.market / np.sqrt(draws.market_variance)
        first = self.book_forecasts[0].day
        return z[list(draws.days).index(first) :]

    def with_shrinkage(self) -> DemoRisk:
        """The same account with coverage specific risk shrunk towards the universe: the rejected variant."""
        return DemoRisk(self.performance, self.universe, self.estimated, shrink_coverage=True)

    @cached_property
    def minimum_variance(self) -> list[Trial]:
        return minimum_variance_trials(self.universe, RollingForecaster(self.universe, self.estimated), every=2)


@lru_cache(maxsize=2)
def build_demo_risk(seed: int = UNIVERSE_SEED) -> DemoRisk:
    logging.getLogger().setLevel(logging.WARNING)
    performance = build_demo_performance()
    universe = FactorUniverse(seed=seed).generate(end=DEMO_END, overlay=overlay_for(performance))
    estimated = estimate(universe)
    if estimated.days[-1] != DEMO_END:
        raise ValidationError("the risk universe must end on the demonstration's last day")
    return DemoRisk(performance, universe, estimated)
