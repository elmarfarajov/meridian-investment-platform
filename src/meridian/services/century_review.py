"""Performance measurement on a century of real US equity returns.

Three studies on the packaged Kenneth French data (``marketdata.french``):

- :func:`benchmark_check` rebuilds the US market as a capitalisation-weighted
  index of its twelve industries - each weighted by its firms times their average
  size at the start of the month - and sets it against the market return the
  library publishes. It is the same test an index provider's own replication has
  to pass, and it validates the weights the attribution uses.
- :func:`equal_weight_attribution` explains the equal-weighted market - every
  stock in equal weight, the purest small-company tilt there is - against the
  capitalisation-weighted market, industry by industry, with Brinson-Fachler:
  allocation is weighting industries by their number of firms rather than their
  value; selection is holding each industry's stocks equally rather than by size.
  Linked by decade, and over the century with all four linking methods.
- :func:`market_series` and :func:`excess_series` give the market as a monthly
  return series for the risk statistics: drawdowns since 1926, Sharpe ratios by
  decade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np

from ..marketdata.french import FrenchHistory, french_history
from ..performance.attribution import AttributionDay, AttributionResult, brinson_fachler_day, link_attribution
from ..performance.linking import METHODS, LinkMethod
from ..performance.returns import ReturnSeries

DIMENSION = "industry"
ORIGIN = date(1926, 6, 30)  # the first return is July 1926's


@dataclass(frozen=True)
class BenchmarkCheck:
    months: tuple[date, ...]
    rebuilt: tuple[float, ...]
    published: tuple[float, ...]

    @property
    def gaps(self) -> np.ndarray:
        return np.array(self.rebuilt) - np.array(self.published)

    @property
    def rms_gap(self) -> float:
        return float(np.sqrt(np.mean(self.gaps**2)))

    @property
    def correlation(self) -> float:
        return float(np.corrcoef(self.rebuilt, self.published)[0, 1])

    @property
    def largest_gap(self) -> tuple[date, float]:
        index = int(np.argmax(np.abs(self.gaps)))
        return self.months[index], float(self.gaps[index])

    def growth(self) -> tuple[float, float]:
        """What one dollar became, rebuilt and published."""
        return float(np.prod(1.0 + np.array(self.rebuilt))), float(np.prod(1.0 + np.array(self.published)))

    def rms_by_decade(self) -> dict[int, float]:
        decades: dict[int, list[float]] = {}
        for month, gap in zip(self.months, self.gaps, strict=True):
            decades.setdefault(month.year // 10 * 10, []).append(float(gap))
        return {decade: float(np.sqrt(np.mean(np.square(values)))) for decade, values in sorted(decades.items())}


def benchmark_check(history: FrenchHistory | None = None) -> BenchmarkCheck:
    history = history or french_history()
    return BenchmarkCheck(
        history.months,
        tuple(history.cap_weighted(month) for month in history.months),
        tuple(history.factors[month].market for month in history.months),
    )


@lru_cache(maxsize=1)
def attribution_days() -> tuple[AttributionDay, ...]:
    """Every month since July 1926: the equal-weighted market against the cap-weighted, by industry."""
    history = french_history()
    found = []
    for month in history.months:
        values, shares, data = history.weights(month), history.firm_shares(month), history.data[month]
        portfolio = {name: (shares[name], item.equal_weighted) for name, item in data.items()}
        benchmark = {name: (values[name], item.value_weighted) for name, item in data.items()}
        found.append(brinson_fachler_day(month, portfolio, benchmark))
    return tuple(found)


def equal_weight_attribution(
    start: date | None = None, end: date | None = None, method: LinkMethod = "carino"
) -> AttributionResult:
    """The equal-weighted market against the cap-weighted over months in ``(start, end]``."""
    days = [
        item for item in attribution_days() if (start is None or item.day > start) and (end is None or item.day <= end)
    ]
    return link_attribution(days, DIMENSION, method)


def decade_attribution() -> list[tuple[str, AttributionResult]]:
    """Calendar decades (the 1920s are July 1926 to December 1929), each linked on its own."""
    found = []
    for decade in range(1920, 2030, 10):
        start, end = date(decade - 1, 12, 31), date(decade + 9, 12, 31)
        result = equal_weight_attribution(start, end)
        found.append((f"{decade}s", result))
    return found


def linking_comparison(start: date | None = None, end: date | None = None) -> dict[LinkMethod, AttributionResult]:
    return {method: equal_weight_attribution(start, end, method) for method in METHODS}


def market_series(history: FrenchHistory | None = None) -> ReturnSeries:
    """The published US market return, monthly since July 1926."""
    history = history or french_history()
    months = tuple(month for month in history.months if month in history.factors)
    return ReturnSeries(
        months, tuple(history.factors[month].market for month in months), "US market", ORIGIN, periods_per_year=12
    )


def excess_series(history: FrenchHistory | None = None) -> ReturnSeries:
    """The market's return over the one-month Treasury bill: the series a Sharpe ratio is measured on."""
    history = history or french_history()
    months = tuple(month for month in history.months if month in history.factors)
    return ReturnSeries(
        months,
        tuple(history.factors[month].market_excess for month in months),
        "US market over bills",
        ORIGIN,
        periods_per_year=12,
    )


def equal_weight_series() -> ReturnSeries:
    days = attribution_days()
    return ReturnSeries(
        tuple(item.day for item in days),
        tuple(item.portfolio for item in days),
        "Equal-weighted market",
        ORIGIN,
        periods_per_year=12,
    )


def cap_weight_series() -> ReturnSeries:
    days = attribution_days()
    return ReturnSeries(
        tuple(item.day for item in days),
        tuple(item.benchmark for item in days),
        "Cap-weighted market (rebuilt)",
        ORIGIN,
        periods_per_year=12,
    )
