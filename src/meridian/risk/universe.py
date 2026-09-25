"""The estimation universe: five hundred stocks whose true risk is known.

A risk model is a forecast, and a forecast can only be judged against what it
was trying to forecast. With real data the truth is never observed: a model's
volatility forecast is compared with a realised volatility that is itself a
noisy estimate. A synthetic universe removes that excuse. Its returns are
generated from a factor structure that is recorded - the factor returns, the
true exposures, the conditional variance of every factor and of every stock's
residual on every day - so the model can be scored against the answer.

The universe is built to be hard in the ways real markets are:

* **Ten years**, 2016 to 2026, so that a model has to live through a crisis.
* **Regimes.** A crash in February-April 2020 with volatility four times
  normal; a bear market through 2022; a momentum crash in November 2020 when
  the previous year's winners fell and cheap stocks rallied in a week.
* **Fat tails and clustering.** The world factor and every stock's residual
  follow GARCH(1,1) with Student-t innovations, the same process as the Day 2
  market.
* **Characteristics that drift.** Size moves with the price, momentum is
  recomputed every month from the stock's own returns, and value and quality
  wander. The exposures a model sees are observed with error: quality through a
  noisy accounting ratio, beta only through a historical regression.
* **The same market as the book.** Over the demonstration window (April 2024 to
  September 2026) the world factor, the industry factors and the currencies are
  replayed from the Day 2 market, so the model estimated here explains the
  stocks the account actually holds.

Stock identifiers are plainly synthetic (``RU0001``). The universe stands in for
the few thousand stocks a commercial model covers; five hundred is enough to
show why a sample covariance matrix fails and a factor model does not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

import numpy as np

from ..core.exceptions import ValidationError
from ..marketdata.providers.synthetic import weekdays
from .exposures import standardise
from .factors import BASE_CURRENCY, CURRENCIES, INDUSTRIES, REGION_OF_CURRENCY, STYLES, WORLD

TRADING_DAYS = 252
UNIVERSE_START = date(2016, 1, 4)

#: Stocks per currency, roughly the regional mix of a world index.
REGION_COUNTS = {"USD": 260, "EUR": 90, "GBP": 50, "CHF": 30, "JPY": 70}

#: Relative number of stocks per industry.
INDUSTRY_WEIGHTS = {
    "Communication Services": 0.07,
    "Consumer Discretionary": 0.11,
    "Consumer Staples": 0.07,
    "Energy": 0.05,
    "Financials": 0.15,
    "Health Care": 0.11,
    "Industrials": 0.14,
    "Information Technology": 0.14,
    "Materials": 0.07,
    "Real Estate": 0.04,
    "Utilities": 0.05,
}

#: Annual volatility of each industry factor (relative to the world).
INDUSTRY_VOL = {
    "Communication Services": 0.06,
    "Consumer Discretionary": 0.06,
    "Consumer Staples": 0.05,
    "Energy": 0.10,
    "Financials": 0.07,
    "Health Care": 0.06,
    "Industrials": 0.05,
    "Information Technology": 0.08,
    "Materials": 0.07,
    "Real Estate": 0.07,
    "Utilities": 0.06,
}

#: Annual volatility and drift of the style factors. For beta, the volatility is of the part of the
#: factor *not* explained by the world factor: a stock's market sensitivity is its true beta, so the
#: beta factor's return is the cross-sectional spread of betas times the world's return, plus this.
STYLE_VOL = {"Beta": 0.02, "Size": 0.035, "Value": 0.04, "Momentum": 0.055, "Quality": 0.025}
STYLE_DRIFT = {"Beta": 0.0, "Size": -0.01, "Value": 0.01, "Momentum": 0.03, "Quality": 0.02}

CURRENCY_VOL = {"EUR": 0.075, "GBP": 0.08, "CHF": 0.07, "JPY": 0.10}

WORLD_VOL = 0.15
WORLD_DRIFT = 0.07
GARCH_ALPHA, GARCH_BETA, TAIL_DOF = 0.06, 0.92, 5.0
SPECIFIC_ALPHA, SPECIFIC_BETA = 0.05, 0.93


@dataclass(frozen=True)
class Regime:
    """A stretch of history with its own volatility, and the total return some factors made over it.

    Volatility is scaled by the multipliers. A drift cannot make a crash - with
    volatility four times normal the noise over a month is larger than any
    plausible drift - so the factors' *totals* over the window are fixed
    instead: the day-to-day path keeps its randomness and the window ends where
    history says it did.
    """

    name: str
    start: date
    end: date
    world_multiplier: float = 1.0
    industry_multiplier: float = 1.0
    style_multiplier: float = 1.0
    specific_multiplier: float = 1.0
    currency_multiplier: float = 1.0
    targets: tuple[tuple[str, float], ...] = ()  # factor, simple return over the window


REGIMES: tuple[Regime, ...] = (
    Regime("2018 volatility spike", date(2018, 1, 29), date(2018, 2, 8), 2.5, 1.3, 1.2, 1.1, 1.1, (("World", -0.10),)),
    Regime(
        "2020 crash",
        date(2020, 2, 20),
        date(2020, 3, 23),
        4.0,
        2.2,
        2.0,
        1.8,
        1.6,
        (("World", -0.32), ("Energy", -0.25), ("Size", 0.03), ("Quality", 0.02)),
    ),
    Regime("2020 recovery", date(2020, 3, 24), date(2020, 6, 30), 2.2, 1.6, 1.5, 1.4, 1.3, (("World", 0.40),)),
    Regime(
        "2020 momentum crash",
        date(2020, 11, 9),
        date(2020, 11, 13),
        1.3,
        1.5,
        3.0,
        1.2,
        1.0,
        (("Momentum", -0.12), ("Value", 0.06)),
    ),
    Regime(
        "2022 bear market",
        date(2022, 1, 3),
        date(2022, 10, 12),
        1.5,
        1.3,
        1.3,
        1.2,
        1.3,
        (("World", -0.25), ("Value", 0.08), ("Information Technology", -0.08), ("Energy", 0.30)),
    ),
)


@dataclass(frozen=True)
class UniverseStock:
    stock_id: str
    sector: str
    currency: str

    @property
    def region(self) -> str:
        return REGION_OF_CURRENCY[self.currency]


@dataclass(frozen=True)
class Overlay:
    """Factor paths to replay on part of the grid: the market the demonstration book lives in.

    All arrays are daily log returns on ``days``, which must be consecutive
    weekdays of the universe grid. ``world_variance`` is the world factor's
    conditional variance, ``industry_vol`` the annual volatility of the replayed
    industries, and ``fx`` each currency's log return against the dollar.

    ``style_scale`` scales the style factors over the overlay. The Day 2 market
    moves its stocks by a market factor, their betas and sector factors only -
    it has no size, value, momentum or quality premia - so to *be* that market
    the universe silences them there (scale zero) and keeps only the beta
    factor's ride on the world.
    """

    days: tuple[date, ...]
    world: np.ndarray
    world_variance: np.ndarray
    industries: dict[str, np.ndarray]
    industry_vol: float
    fx: dict[str, np.ndarray] = field(default_factory=dict)
    style_scale: float = 0.0


@dataclass
class UniverseHistory:
    """What the generator produced: what a model can observe, and the truth it cannot."""

    days: tuple[date, ...]
    stocks: tuple[UniverseStock, ...]
    # observable
    local_returns: np.ndarray  # T x N simple returns in local currency
    fx_returns: dict[str, np.ndarray]  # simple return of each currency against the dollar
    caps: np.ndarray  # T x N market capitalisation in dollars at each close
    month_starts: tuple[int, ...]  # grid index of the first day of each month
    book_to_price: np.ndarray  # M x N, reported at each month start
    return_on_equity: np.ndarray  # M x N, a noisy measure of quality
    # the truth
    true_factor_returns: dict[str, np.ndarray]  # log returns, local factors and currencies
    true_factor_variance: dict[str, np.ndarray]  # conditional daily variance
    true_style_exposures: np.ndarray  # M x N x styles
    true_beta: np.ndarray  # N
    true_specific_variance: np.ndarray  # T x N conditional daily variance
    beta_world_covariance: np.ndarray  # T, conditional covariance of the beta and world factors
    overlay_start: int | None = None

    @property
    def stock_ids(self) -> tuple[str, ...]:
        return tuple(stock.stock_id for stock in self.stocks)

    @property
    def usd_returns(self) -> np.ndarray:
        """Returns in dollars: the local return compounded with the currency's."""
        fx = np.column_stack(
            [
                self.fx_returns[stock.currency] if stock.currency != BASE_CURRENCY else np.zeros(len(self.days))
                for stock in self.stocks
            ]
        )
        return (1.0 + self.local_returns) * (1.0 + fx) - 1.0

    def month_of(self, day_index: int) -> int:
        """The index of the latest month start on or before a grid day."""
        position = int(np.searchsorted(np.asarray(self.month_starts), day_index, side="right")) - 1
        return max(position, 0)

    @cached_property
    def _industries(self) -> np.ndarray:
        return self.industry_matrix()

    @cached_property
    def _currencies(self) -> np.ndarray:
        return self.currency_matrix()

    def industry_matrix(self) -> np.ndarray:
        matrix = np.zeros((len(self.stocks), len(INDUSTRIES)))
        for row, stock in enumerate(self.stocks):
            matrix[row, INDUSTRIES.index(stock.sector)] = 1.0
        return matrix

    def currency_matrix(self) -> np.ndarray:
        matrix = np.zeros((len(self.stocks), len(CURRENCIES)))
        for row, stock in enumerate(self.stocks):
            if stock.currency != BASE_CURRENCY:
                matrix[row, CURRENCIES.index(stock.currency)] = 1.0
        return matrix

    def true_variance(self, day_index: int, weights: np.ndarray) -> float:
        """The true conditional variance of a dollar portfolio's return on one day."""
        return float(self.true_variances(day_index, weights[:, None])[0])

    def true_variances(self, day_index: int, weights: np.ndarray) -> np.ndarray:
        """True conditional variances of several portfolios at once (``weights`` is N x P)."""
        styles = self.true_style_exposures[self.month_of(day_index)]
        world = weights.sum(axis=0)
        industries = self._industries.T @ weights
        style = styles.T @ weights
        currencies = self._currencies.T @ weights
        factor_var = self.true_factor_variance
        variance = world**2 * factor_var[WORLD][day_index]
        variance = variance + np.array([factor_var[name][day_index] for name in INDUSTRIES]) @ industries**2
        variance = variance + np.array([factor_var[name][day_index] for name in STYLES]) @ style**2
        variance = variance + np.array([factor_var[f"FX {code}"][day_index] for code in CURRENCIES]) @ currencies**2
        variance = variance + 2.0 * world * style[STYLES.index("Beta")] * self.beta_world_covariance[day_index]
        return variance + self.true_specific_variance[day_index] @ weights**2


def _student_t(rng: np.random.Generator, size: int | tuple[int, ...], dof: float = TAIL_DOF) -> np.ndarray:
    return rng.standard_t(dof, size) * math.sqrt((dof - 2.0) / dof)


def _regime_arrays(grid: list[date]) -> dict[str, np.ndarray]:
    steps = len(grid)
    arrays = {name: np.ones(steps) for name in ("world", "industry", "style", "specific", "currency")}
    for regime in REGIMES:
        for index, day in enumerate(grid):
            if regime.start <= day <= regime.end:
                arrays["world"][index] = regime.world_multiplier
                arrays["industry"][index] = regime.industry_multiplier
                arrays["style"][index] = regime.style_multiplier
                arrays["specific"][index] = regime.specific_multiplier
                arrays["currency"][index] = regime.currency_multiplier
    return arrays


def _impose_targets(grid: list[date], factors: dict[str, np.ndarray]) -> None:
    """Shift each targeted factor's log returns within its regime so the window compounds to the target."""
    for regime in REGIMES:
        window = [index for index, day in enumerate(grid) if regime.start <= day <= regime.end]
        if not window:
            continue
        for name, total in regime.targets:
            if name not in factors:
                continue  # a style target, imposed once the styles exist
            path = factors[name]
            gap = math.log1p(total) - float(path[window].sum())
            path[window] += gap / len(window)


class FactorUniverse:
    """Generates an estimation universe with a recorded factor structure."""

    def __init__(self, size: int | None = None, *, seed: int = 11) -> None:
        self.seed = seed
        total = sum(REGION_COUNTS.values())
        self.size = size or total
        if self.size < 60:
            raise ValidationError("a factor model needs a universe of at least sixty stocks")

    def generate(
        self, start: date = UNIVERSE_START, end: date = date(2026, 9, 18), overlay: Overlay | None = None
    ) -> UniverseHistory:
        if end <= start:
            raise ValidationError("a universe needs end after start")
        rng = np.random.default_rng(self.seed)
        grid = weekdays(start, end)
        steps, dt = len(grid), 1.0 / TRADING_DAYS
        stocks = self._stocks(rng)
        count = len(stocks)
        regimes = _regime_arrays(grid)

        # ---- the factors' daily log returns and true conditional variances
        world, world_variance = self._garch(rng, steps, WORLD_VOL**2 * dt, regimes["world"])
        world = world + (WORLD_DRIFT * dt - 0.5 * WORLD_VOL**2 * dt)
        factors: dict[str, np.ndarray] = {WORLD: world}
        variances: dict[str, np.ndarray] = {WORLD: world_variance}
        for name in INDUSTRIES:
            scale = INDUSTRY_VOL[name] * math.sqrt(dt) * regimes["industry"]
            factors[name] = rng.standard_normal(steps) * scale
            variances[name] = scale**2
        for code in CURRENCIES:
            scale = CURRENCY_VOL[code] * math.sqrt(dt) * regimes["currency"]
            factors[f"FX {code}"] = rng.standard_normal(steps) * scale
            variances[f"FX {code}"] = scale**2
        overlay_start = self._apply_overlay(grid, factors, variances, overlay)
        _impose_targets(grid, factors)  # world and industries first: the beta factor is built on the world

        # ---- the styles last, so the beta factor rides on the world factor actually used.
        # A stock with beta b moves b times the world; with exposures standardised to one
        # cross-sectional standard deviation, that is a beta factor of (spread of betas) x world.
        true_beta = np.clip(rng.normal(1.0, 0.25, count), 0.4, 1.8)
        dispersion = float(np.std(true_beta))
        world, world_variance = factors[WORLD], variances[WORLD]
        for name in STYLES:
            scale = STYLE_VOL[name] * math.sqrt(dt) * regimes["style"]
            noise = _student_t(rng, steps, 6.0) * scale
            factors[name] = noise + STYLE_DRIFT[name] * dt
            variances[name] = scale**2
            if overlay is not None and overlay_start is not None:
                window = slice(overlay_start, overlay_start + len(overlay.days))
                factors[name][window] *= overlay.style_scale
                variances[name][window] = variances[name][window] * overlay.style_scale**2
        factors["Beta"] = factors["Beta"] + dispersion * world
        variances["Beta"] = variances["Beta"] + dispersion**2 * world_variance
        beta_world = dispersion * world_variance
        _impose_targets(grid, factors)  # then the styles (the world is already on target)

        # ---- the stocks' characteristics
        log_cap = np.clip(rng.normal(math.log(15e9), 1.1, count), math.log(3e8), math.log(2.5e12))
        base_bp = rng.normal(math.log(0.45), 0.5, count)
        base_quality = rng.standard_normal(count)
        specific_annual = np.clip(
            0.20 * np.exp(-0.18 * (log_cap - log_cap.mean())) * np.exp(rng.normal(0.0, 0.2, count)), 0.10, 0.70
        )
        industries = np.zeros((count, len(INDUSTRIES)))
        for row, stock in enumerate(stocks):
            industries[row, INDUSTRIES.index(stock.sector)] = 1.0
        currency_of = [stock.currency for stock in stocks]

        month_starts = [index for index, day in enumerate(grid) if index == 0 or day.month != grid[index - 1].month]
        months = len(month_starts)
        style_exposures = np.zeros((months, count, len(STYLES)))
        book_to_price = np.zeros((months, count))
        roe = np.zeros((months, count))

        local_log = np.zeros((steps, count))
        caps = np.zeros((steps, count))
        specific_variance = np.zeros((steps, count))
        long_run = specific_annual**2 * dt
        current_variance = long_run.copy()
        omega = long_run * (1 - SPECIFIC_ALPHA - SPECIFIC_BETA)
        cap = np.exp(log_cap)
        bp_drift = np.zeros(count)
        quality_drift = np.zeros(count)
        shocks = _student_t(rng, (steps, count))
        fx_log = {code: factors[f"FX {code}"] for code in CURRENCIES}
        fx_by_stock = np.column_stack(
            [fx_log[code] if code != BASE_CURRENCY else np.zeros(steps) for code in currency_of]
        )
        cumulative = np.zeros((steps + 1, count))

        for month, first in enumerate(month_starts):
            last = month_starts[month + 1] if month + 1 < months else steps
            bp_drift += rng.normal(0.0, 0.05, count)
            quality_drift = 0.97 * quality_drift + rng.normal(0.0, 0.08, count)
            log_bp = base_bp + bp_drift
            latent_quality = base_quality + quality_drift
            window_end, window_start = max(first - 21, 0), max(first - TRADING_DAYS, 0)
            momentum = cumulative[window_end] - cumulative[window_start]
            raw = np.column_stack([true_beta, np.log(cap), log_bp, momentum, latent_quality])
            exposures = np.column_stack([standardise(raw[:, k], cap) for k in range(len(STYLES))])
            if window_end == window_start:
                exposures[:, STYLES.index("Momentum")] = 0.0
            style_exposures[month] = exposures
            book_to_price[month] = np.exp(log_bp)
            roe[month] = 0.12 + 0.05 * latent_quality + rng.normal(0.0, 0.02, count)

            style_block = np.column_stack([factors[name][first:last] for name in STYLES])
            industry_block = np.column_stack([factors[name][first:last] for name in INDUSTRIES])
            systematic = factors[WORLD][first:last, None] + industry_block @ industries.T + style_block @ exposures.T
            for offset, day in enumerate(range(first, last)):
                specific_variance[day] = current_variance * regimes["specific"][day] ** 2
                innovation = np.sqrt(current_variance) * shocks[day]
                current_variance = omega + SPECIFIC_ALPHA * innovation**2 + SPECIFIC_BETA * current_variance
                local_log[day] = systematic[offset] + innovation * regimes["specific"][day] - 0.5 * long_run
                cap = cap * np.exp(local_log[day] + fx_by_stock[day])
                caps[day] = cap
                cumulative[day + 1] = cumulative[day] + local_log[day]

        fx_simple = {code: np.expm1(fx_log[code]) for code in CURRENCIES}
        return UniverseHistory(
            days=tuple(grid),
            stocks=stocks,
            local_returns=np.expm1(local_log),
            fx_returns=fx_simple,
            caps=caps,
            month_starts=tuple(month_starts),
            book_to_price=book_to_price,
            return_on_equity=roe,
            true_factor_returns=factors,
            true_factor_variance=variances,
            true_style_exposures=style_exposures,
            true_beta=true_beta,
            true_specific_variance=specific_variance,
            beta_world_covariance=beta_world,
            overlay_start=overlay_start,
        )

    # ------------------------------------------------------------------ helpers
    def _stocks(self, rng: np.random.Generator) -> tuple[UniverseStock, ...]:
        total = sum(REGION_COUNTS.values())
        counts = {code: max(1, round(count * self.size / total)) for code, count in REGION_COUNTS.items()}
        counts["USD"] += self.size - sum(counts.values())
        names = list(INDUSTRY_WEIGHTS)
        probabilities = np.array(list(INDUSTRY_WEIGHTS.values()))
        probabilities = probabilities / probabilities.sum()
        drawn = [
            (names[int(k)], code)
            for code, count in counts.items()
            for k in rng.choice(len(names), size=count, p=probabilities)
        ]
        return tuple(
            UniverseStock(f"RU{position + 1:04d}", sector, code) for position, (sector, code) in enumerate(drawn)
        )

    def _garch(
        self, rng: np.random.Generator, steps: int, long_run: float, multiplier: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        shocks = _student_t(rng, steps)
        omega = long_run * (1 - GARCH_ALPHA - GARCH_BETA)
        path, variance = np.empty(steps), np.empty(steps)
        current = long_run
        for index in range(steps):
            variance[index] = current * multiplier[index] ** 2
            innovation = math.sqrt(current) * shocks[index]
            path[index] = innovation * multiplier[index]
            current = omega + GARCH_ALPHA * innovation**2 + GARCH_BETA * current
        return path, variance

    @staticmethod
    def _apply_overlay(
        grid: list[date],
        factors: dict[str, np.ndarray],
        variances: dict[str, np.ndarray],
        overlay: Overlay | None,
    ) -> int | None:
        if overlay is None:
            return None
        try:
            first = grid.index(overlay.days[0])
        except ValueError as error:
            raise ValidationError("the overlay must start on a weekday of the universe grid") from error
        last = first + len(overlay.days)
        if tuple(grid[first:last]) != overlay.days:
            raise ValidationError("the overlay's days must be consecutive weekdays of the universe grid")
        dt = 1.0 / TRADING_DAYS
        factors[WORLD][first:last] = overlay.world
        variances[WORLD][first:last] = overlay.world_variance
        for name, path in overlay.industries.items():
            if name in factors:
                factors[name][first:last] = path
                variances[name][first:last] = overlay.industry_vol**2 * dt
        for code, path in overlay.fx.items():
            key = f"FX {code}"
            if key in factors:
                factors[key][first:last] = path
                variances[key][first:last] = np.full(len(path), float(np.var(path)))
        return first
