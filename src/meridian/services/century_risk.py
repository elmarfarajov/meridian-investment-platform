"""Risk measurement on a century of daily US returns.

Four studies on the packaged daily Kenneth French data (``marketdata.french``):

- :func:`var_backtest` forecasts the US market's one-day 99% VaR every day since
  1928 four ways - normal with RiskMetrics volatility, historical simulation,
  filtered historical simulation, GARCH-t - and scores every forecast: exceptions,
  Kupiec and Christoffersen over the whole span, and Basel's zone year by year.
- :func:`bias_by_decade` asks of the RiskMetrics volatility forecast what Day 5
  asked of the factor model: is the standardised outcome's dispersion one? For
  the market and each of the twelve industries, decade by decade.
- :func:`forecast_losses` compares the volatility forecasts on the QLIKE loss.
- :func:`minimum_variance_trials` builds a minimum-variance portfolio of the
  twelve industries every month from four covariance estimators and sets the
  risk each promised against the risk each delivered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np

from ..marketdata.french import FrenchDaily, french_daily
from ..risk.backtest import (
    ewma_volatility,
    filtered_historical_var,
    garch_var,
    historical_var,
    normal_var,
)
from ..risk.covariance import (
    EwmaState,
    ledoit_wolf,
    ledoit_wolf_constant_correlation,
    minimum_variance_weights,
    sample_covariance,
)
from ..risk.validation import (
    CoverageTest,
    TrafficLight,
    bias_statistic,
    christoffersen,
    confidence_band,
    kupiec,
    qlike,
    traffic_light,
)

CONFIDENCE = 0.99
FIRST_SCORED = date(1929, 1, 1)  # every forecaster has its history by then except GARCH, scored from 1930
METHODS = (
    "Normal, RiskMetrics volatility",
    "Historical simulation (500 days)",
    "Filtered historical simulation",
    "GARCH(1,1), Student-t",
)
COVARIANCE_WINDOW = 252
HOLDING = 21


@dataclass(frozen=True)
class MethodBacktest:
    method: str
    days: tuple[date, ...]
    returns: np.ndarray
    var: np.ndarray
    hits: np.ndarray

    @property
    def exceptions(self) -> int:
        return int(self.hits.sum())

    @property
    def rate(self) -> float:
        return self.exceptions / len(self.hits)

    @property
    def kupiec(self) -> CoverageTest:
        return kupiec(self.exceptions, len(self.hits), CONFIDENCE)

    @property
    def christoffersen(self) -> CoverageTest:
        return christoffersen(self.hits)

    def by_year(self) -> dict[int, TrafficLight]:
        years: dict[int, list[int]] = {}
        for day, hit in zip(self.days, self.hits, strict=True):
            years.setdefault(day.year, []).append(int(hit))
        return {year: traffic_light(sum(values), len(values), CONFIDENCE) for year, values in sorted(years.items())}

    def zone_counts(self) -> dict[str, int]:
        counts = {"green": 0, "yellow": 0, "red": 0}
        for light in self.by_year().values():
            counts[light.zone] += 1
        return counts

    def worst(self, count: int = 5) -> list[tuple[date, float, float]]:
        """The largest exceedances: (day, return, return over the VaR forecast)."""
        ratio = -self.returns / self.var
        order = np.argsort(ratio)[::-1][:count]
        return [(self.days[i], float(self.returns[i]), float(ratio[i])) for i in order]


@lru_cache(maxsize=1)
def _forecasts() -> tuple[FrenchDaily, dict[str, np.ndarray], list[tuple[int, float, float, float]]]:
    data = french_daily()
    returns = data.market
    garch, garch_volatility, fits = garch_var(returns, CONFIDENCE)
    forecasts = {
        METHODS[0]: normal_var(returns, CONFIDENCE),
        METHODS[1]: historical_var(returns, CONFIDENCE),
        METHODS[2]: filtered_historical_var(returns, CONFIDENCE),
        METHODS[3]: garch,
        "GARCH volatility": garch_volatility,
    }
    return data, forecasts, fits


def var_backtest(start: date | None = None) -> list[MethodBacktest]:
    """Every method scored on the same days: from the first day all four have a forecast."""
    data, forecasts, _ = _forecasts()
    first = max(data.index_of(start or FIRST_SCORED), *(int(np.argmax(np.isfinite(v))) for v in forecasts.values()))
    days = data.days[first:]
    returns = data.market[first:]
    results = []
    for method in METHODS:
        var = forecasts[method][first:]
        results.append(MethodBacktest(method, days, returns, var, (-returns > var).astype(int)))
    return results


def garch_fits() -> list[tuple[date, float, float, float]]:
    data, _, fits = _forecasts()
    return [(data.days[day], alpha, beta, dof) for day, alpha, beta, dof in fits]


# ---------------------------------------------------------------------------- bias by decade
@dataclass(frozen=True)
class DecadeBias:
    series: str
    decade: int
    bias: float
    low: float
    high: float

    @property
    def verdict(self) -> str:
        return "under-forecasts" if self.bias > self.high else "over-forecasts" if self.bias < self.low else "unbiased"


def bias_by_decade() -> list[DecadeBias]:
    """The RiskMetrics forecast's bias statistic for the market and every industry, decade by decade."""
    data = french_daily()
    series = {"Market": data.market, **{name: data.industry(name) for name in data.industries}}
    decades = np.array([day.year // 10 * 10 for day in data.days])
    found = []
    for name, returns in series.items():
        z = returns / ewma_volatility(returns)
        for decade in sorted(set(decades.tolist())):
            chosen = z[(decades == decade) & np.isfinite(z)]
            if len(chosen) < 250:
                continue
            low, high = confidence_band(len(chosen))
            found.append(DecadeBias(name, decade, bias_statistic(chosen), low, high))
    return found


# ---------------------------------------------------------------------------- forecast losses
def forecast_losses() -> dict[str, dict[int, float]]:
    """QLIKE of three volatility forecasts of the market, by decade (lower is better)."""
    data, forecasts, _ = _forecasts()
    returns = data.market
    rolling = np.full(len(returns), np.nan)
    squares = np.concatenate([[0.0], np.cumsum(returns**2)])
    for day in range(252, len(returns)):
        rolling[day] = math.sqrt((squares[day] - squares[day - 252]) / 252)
    candidates = {
        "RiskMetrics EWMA": ewma_volatility(returns),
        "GARCH(1,1)-t": forecasts["GARCH volatility"],
        "Rolling 252 days": rolling,
    }
    decades = np.array([day.year // 10 * 10 for day in data.days])
    scored = np.ones(len(returns), dtype=bool)
    for values in candidates.values():
        scored &= np.isfinite(values)
    found: dict[str, dict[int, float]] = {}
    for name, values in candidates.items():
        found[name] = {
            int(decade): qlike(returns[scored & (decades == decade)], values[scored & (decades == decade)])
            for decade in sorted(set(decades[scored].tolist()))
        }
        found[name][0] = qlike(returns[scored], values[scored])  # 0: the whole span
    return found


# ---------------------------------------------------------------------------- covariance
ESTIMATORS = (
    "Sample (252 days)",
    "EWMA (42 / 200 days)",
    "Ledoit-Wolf (identity)",
    "Ledoit-Wolf (constant correlation)",
)


@dataclass(frozen=True)
class Trial:
    day: date
    estimator: str
    promised: float  # annualised
    delivered: float  # annualised, over the next month


@lru_cache(maxsize=1)
def minimum_variance_trials() -> tuple[Trial, ...]:
    """Monthly minimum-variance portfolios of the twelve industries, promised against delivered."""
    data = french_daily()
    returns = data.returns
    months = [index for index in range(1, len(data.days)) if data.days[index].month != data.days[index - 1].month]
    trials = []
    ewma = EwmaState.start(returns.shape[1])
    absorbed = 0
    for start in months:
        if start < COVARIANCE_WINDOW or start + HOLDING > len(returns):
            while absorbed < start:
                ewma.update(returns[absorbed])
                absorbed += 1
            continue
        while absorbed < start:
            ewma.update(returns[absorbed])
            absorbed += 1
        window = returns[start - COVARIANCE_WINDOW : start]
        future = returns[start : start + HOLDING]
        estimates = {
            ESTIMATORS[0]: sample_covariance(window),
            ESTIMATORS[1]: ewma.covariance(),
            ESTIMATORS[2]: ledoit_wolf(window).covariance,
            ESTIMATORS[3]: ledoit_wolf_constant_correlation(window).covariance,
        }
        for name, covariance in estimates.items():
            weights = minimum_variance_weights(covariance)
            promised = math.sqrt(max(float(weights @ covariance @ weights), 0.0) * 252)
            delivered = float(np.std(future @ weights, ddof=1)) * math.sqrt(252)
            trials.append(Trial(data.days[start], name, promised, delivered))
    return tuple(trials)


def covariance_summary() -> dict[str, tuple[float, float, float]]:
    """Per estimator: mean promised, mean delivered, and delivered over promised."""
    rows = {}
    for name in ESTIMATORS:
        chosen = [trial for trial in minimum_variance_trials() if trial.estimator == name]
        promised = float(np.mean([trial.promised for trial in chosen]))
        delivered = float(np.mean([trial.delivered for trial in chosen]))
        rows[name] = (promised, delivered, delivered / promised)
    return rows
