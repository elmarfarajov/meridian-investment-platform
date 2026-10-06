"""Almgren-Chriss liquidation on a century of real prices.

Almgren and Chriss (2000) price a liquidation as a mean and a variance. The
mean is the impact the schedule pays. The variance is the price moving while
the position is still held. Their efficient frontier trades one against the
other, and a trader is told: on this schedule, the cost will exceed
``E + 1.645 √V`` one time in twenty. That promise rests on prices being a random
walk with known, constant volatility.

Here it is tested on Kenneth French's daily returns since July 1926: the market
and each of its twelve industries, every five-day week. Each week the paper's
own example is run: $50m of a $50 stock sold over five days, one trade a day,
with Table 1's impact and spread.

- **The volatility** is forecast before the week starts, with RiskMetrics' EWMA
  (decay 0.94, as Day 5), and alternatively as the standard deviation of the
  year before. It is never the week's own.
- **The realised cost** is the impact the schedule pays, which the model
  knows, plus what the price did to the shares still held. That second part
  uses the real daily returns: ``C = E - Σ x_k S_0 r_k``.
- **The autocorrelation** of daily returns, estimated over the year before the
  week, restates the variance (``ExecutionProblem.variance(..., autocorrelation)``):
  a random walk has none, and an index whose daily returns move together is
  riskier to hold through a week than its daily volatility says.
- **The test** is the paper's 95% bound. If the model is right, the cost exceeds
  ``E + 1.645 √V`` in 5% of weeks, for a seller and for a buyer alike, and
  ``(C - E) / √V`` is standard normal.

**A control.** The same test on a simulated random walk, where the model is
true, gives 5% when the volatility is known, and a little more when it is
forecast: the forecaster's own error widens the tails. That is the baseline
the century is set against.

Three schedules are tried: even (the risk-neutral trader), the paper's
(λ = 10⁻⁶, κT ≈ 3 at the example's volatility), and an urgent one (λ = 10⁻⁵).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..execution.almgren_chriss import ExecutionProblem
from ..marketdata.french import FrenchDaily, french_daily
from ..risk.validation import kupiec

#: Almgren and Chriss (2000), Table 1
PRICE = 50.0
SHARES = 1e6
DAYS = 5
EPSILON = 0.0625
ETA = 2.5e-6
GAMMA = 2.5e-7
EWMA_DECAY = 0.94
YEAR = 250
WARM_UP = 250  # days of history before the first week: the EWMA forgets its start, the year is full
BOUND = 1.645  # the paper's 95% value-at-risk multiplier, lambda_v
SCHEDULES: dict[str, float] = {"even": 0.0, "the paper's": 1e-6, "urgent": 1e-5}


def ewma_volatility(returns: np.ndarray, decay: float = EWMA_DECAY) -> np.ndarray:
    """The forecast for each day made the evening before: sigma^2_t = decay sigma^2_{t-1} + (1 - decay) r^2_{t-1}."""
    variance = np.empty(len(returns))
    variance[0] = float(np.var(returns[:WARM_UP]))
    for day in range(1, len(returns)):
        variance[day] = decay * variance[day - 1] + (1 - decay) * returns[day - 1] ** 2
    return np.sqrt(variance)


def trailing_volatility(returns: np.ndarray, window: int = YEAR) -> np.ndarray:
    """The standard deviation of the ``window`` days before each day (NaN until there are enough)."""
    output = np.full(len(returns), np.nan)
    squares = np.concatenate([[0.0], np.cumsum(returns**2)])
    sums = np.concatenate([[0.0], np.cumsum(returns)])
    for day in range(window, len(returns)):
        total, square = sums[day] - sums[day - window], squares[day] - squares[day - window]
        output[day] = math.sqrt(max(square / window - (total / window) ** 2, 0.0) * window / (window - 1))
    return output


def trailing_autocorrelation(returns: np.ndarray, days: np.ndarray, window: int = YEAR) -> np.ndarray:
    """The lag-one autocorrelation of the ``window`` days before each of ``days`` (0 where there is not a year)."""
    output = np.zeros(len(days))
    for position, day in enumerate(days):
        if day > window:
            history = returns[day - window : day]
            output[position] = float(np.corrcoef(history[:-1], history[1:])[0, 1])
    return output


def problem(daily_volatility: float) -> ExecutionProblem:
    """The paper's example at a given daily volatility (the paper's own is 0.95 / 50 = 1.9%)."""
    return ExecutionProblem(SHARES, float(DAYS), DAYS, PRICE * daily_volatility, ETA, GAMMA, EPSILON)


@dataclass(frozen=True)
class Weeks:
    """Every week of one series: the forecast, and for each schedule the standardised cost a seller paid."""

    name: str
    starts: np.ndarray  # index of each week's first day
    years: np.ndarray  # calendar year of each week's first day
    forecast: np.ndarray  # the daily volatility forecast for the week
    realised: np.ndarray  # the week's realised daily volatility
    autocorrelation: np.ndarray  # the lag-one autocorrelation of the year before each week
    z: dict[str, np.ndarray]  # schedule -> (C - E) / sqrt(V) for a seller; a buyer's is -z
    z_corrected: dict[str, np.ndarray]  # the same, with V restated for the autocorrelation
    expected: dict[str, np.ndarray]  # schedule -> E, dollars
    deviation: dict[str, np.ndarray]  # schedule -> sqrt(V), dollars
    cost: dict[str, np.ndarray]  # schedule -> the seller's realised cost, dollars


def weeks(
    name: str, returns: np.ndarray, years: np.ndarray, forecaster: str = "ewma", known: float | None = None
) -> Weeks:
    """Every five-day week of a series; ``known`` replaces the forecast with the true volatility (a control)."""
    if known is not None:
        sigma = np.full(len(returns), known)
    else:
        sigma = ewma_volatility(returns) if forecaster == "ewma" else trailing_volatility(returns)
    starts = np.arange(WARM_UP, len(returns) - DAYS + 1, DAYS)
    forecast = sigma[starts]
    moves = np.stack([returns[starts + day] for day in range(DAYS)], axis=1)  # weeks x 5: r_1 .. r_5
    realised = moves.std(axis=1, ddof=0) * math.sqrt(DAYS / (DAYS - 1))
    rho = trailing_autocorrelation(returns, starts)
    z, z_corrected, expected, deviation, cost = {}, {}, {}, {}, {}
    for schedule, risk_aversion in SCHEDULES.items():
        holdings = np.array([problem(level).holdings(risk_aversion)[1:] for level in forecast])  # x_1 .. x_N
        e = np.array([problem(level).expected_cost(risk_aversion) for level in forecast])
        v = np.sqrt([problem(level).variance(risk_aversion) for level in forecast])
        timing = -(holdings * PRICE * moves).sum(axis=1)  # a seller loses what the held shares lose
        expected[schedule], deviation[schedule] = e, v
        cost[schedule] = e + timing
        z[schedule] = timing / v
        corrected = np.sqrt(
            [problem(level).variance(risk_aversion, float(r)) for level, r in zip(forecast, rho, strict=True)]
        )
        z_corrected[schedule] = timing / corrected
    return Weeks(name, starts, years[starts], forecast, realised, rho, z, z_corrected, expected, deviation, cost)


@dataclass(frozen=True)
class Coverage:
    """How often the cost broke the paper's 95% bound, and whether that is consistent with 5%."""

    weeks: int
    exceedances: int
    p_value: float  # Kupiec's likelihood-ratio test of a 5% rate (Day 5's)

    @property
    def rate(self) -> float:
        return self.exceedances / self.weeks if self.weeks else 0.0


def coverage(z: np.ndarray, side: str = "sell") -> Coverage:
    values = z if side == "sell" else -z
    count = int((values > BOUND).sum())
    return Coverage(len(values), count, kupiec(count, len(values), coverage=0.95).p_value)


@lru_cache(maxsize=2)
def century(forecaster: str = "ewma") -> tuple[Weeks, ...]:
    """The market first, then the twelve industries."""
    data: FrenchDaily = french_daily()
    years = np.array([day.year for day in data.days])
    series = [weeks("Market", data.market, years, forecaster)]
    series += [weeks(name, data.industry(name), years, forecaster) for name in data.industries]
    return tuple(series)


def pooled(series: tuple[Weeks, ...], schedule: str) -> np.ndarray:
    return np.concatenate([item.z[schedule] for item in series])


def pooled_corrected(series: tuple[Weeks, ...], schedule: str) -> np.ndarray:
    return np.concatenate([item.z_corrected[schedule] for item in series])


def by_decade(item: Weeks, schedule: str, side: str = "sell", *, corrected: bool = False) -> dict[int, Coverage]:
    decades = (item.years // 10) * 10
    z = item.z_corrected[schedule] if corrected else item.z[schedule]
    return {int(d): coverage(z[decades == d], side) for d in np.unique(decades)}


def variance_ratio(returns: np.ndarray, horizon: int = DAYS) -> float:
    """Variance of non-overlapping ``horizon``-day sums over ``horizon`` daily variances: 1 for a random walk."""
    usable = len(returns) // horizon * horizon
    sums = returns[:usable].reshape(-1, horizon).sum(axis=1)
    return float(sums.var() / (horizon * returns[:usable].var()))
