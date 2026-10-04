"""Meridian's performance statistics reconciled against empyrical and scipy.

empyrical is the performance-statistics library Quantopian wrote for pyfolio and
zipline; it is maintained as ``empyrical-reloaded`` and is the closest thing the
Python world has to a reference for return and risk measures. scipy supplies the
reference for the higher moments. This module computes every measure both ways on
two datasets:

- **the demonstration account** against its policy benchmark, daily, with a 4%
  risk-free rate - the series every Day 4 chart is drawn from;
- **a century of real returns**: the equal-weighted US market against the
  published market, monthly since July 1926 (``marketdata.french``).

A measure either **agrees** (to 1e-10), or differs by a **convention**. A
difference is not accepted on a description: for each convention the module also
computes the measure *under empyrical's convention* from Meridian's own building
blocks, and that figure must agree with empyrical's to 1e-10. So every gap is
both explained and accounted for to the last digit.

empyrical is a development dependency; nothing in the platform needs it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..performance.returns import ReturnSeries, link
from ..performance.statistics import _aligned, capture_ratio, relative, risk_return

TOLERANCE = 1e-10


def _empyrical() -> Any:
    import empyrical

    return empyrical


@dataclass(frozen=True, slots=True)
class Convention:
    """A measure on which Meridian and empyrical knowingly differ, and why."""

    measure: str
    meridian: str
    empyrical: str
    reason: str


CONVENTIONS: dict[str, Convention] = {
    item.measure: item
    for item in (
        Convention(
            "annual return",
            "calendar time: (1 + R) ^ (365.25 / days) - 1, and not annualised under a year (GIPS)",
            "period count: (1 + R) ^ (periods per year / n) - 1",
            "Calendar time is what a client's statement means by 'a year'. A count of 252 trading days a year is "
            "a convention of its own, off by a day or two each year.",
        ),
        Convention(
            "Sharpe ratio",
            "annual rate less the risk-free rate, over annualised volatility (geometric)",
            "mean excess return per period over its standard deviation, times the root of periods per year "
            "(arithmetic, Sharpe 1994)",
            "Both are standard. The geometric form compares what was earned with what a bill earned, as a factsheet "
            "reports it; the arithmetic form is Sharpe's ex-post definition and the one optimisation uses.",
        ),
        Convention(
            "Sortino ratio",
            "annual rate less the risk-free rate, over annualised downside deviation",
            "mean excess return per period times periods per year, over annualised downside deviation",
            "The same choice as the Sharpe ratio, geometric against arithmetic; the downside deviations agree.",
        ),
        Convention(
            "alpha",
            "Jensen's alpha on annual rates: R - [rf + beta (B - rf)]",
            "the mean per-period regression residual, compounded: (1 + mean(r - rf - beta (b - rf))) ^ n - 1",
            "Jensen's form on annual rates is what a factsheet states; empyrical's is the regression intercept.",
        ),
        Convention(
            "expected shortfall",
            "the mean of every return at or below the interpolated 5% quantile",
            "the mean of the lowest floor((n - 1) x 5%) + 1 returns",
            "Two estimators of the same tail mean; they differ when the quantile falls between observations.",
        ),
    )
}


@dataclass(frozen=True)
class Comparison:
    dataset: str
    measure: str
    meridian: float
    empyrical: float
    under_their_convention: float | None = None  # Meridian's blocks, recombined the way empyrical does

    @property
    def difference(self) -> float:
        return self.meridian - self.empyrical

    @property
    def agrees(self) -> bool:
        return abs(self.difference) <= TOLERANCE * max(1.0, abs(self.empyrical))

    @property
    def convention(self) -> Convention | None:
        return CONVENTIONS.get(self.measure)

    @property
    def reconciled(self) -> bool:
        """Agrees outright, or differs by a known convention that accounts for the whole gap."""
        if self.agrees:
            return True
        if self.convention is None or self.under_their_convention is None:
            return False
        return abs(self.under_their_convention - self.empyrical) <= TOLERANCE * max(1.0, abs(self.empyrical))


def compare(portfolio: ReturnSeries, benchmark: ReturnSeries, risk_free: float, dataset: str) -> list[Comparison]:
    """Every measure both ways on one pair of series."""
    ep = _empyrical()
    from scipy import stats

    period = {252: "daily", 12: "monthly"}[portfolio.periods_per_year]
    per_year = portfolio.periods_per_year
    p, b = _aligned(portfolio, benchmark)
    aligned = ReturnSeries(
        tuple(day for day in portfolio.days if day in set(benchmark.days)), tuple(p), portfolio.name,
        portfolio.start, per_year,
    )  # fmt: skip
    mine = risk_return(aligned, risk_free=risk_free)
    rel = relative(portfolio, benchmark, risk_free=risk_free)
    rf = (1.0 + risk_free) ** (1.0 / per_year) - 1.0
    excess = p - rf
    beta = float(ep.beta(p, b, risk_free=rf))
    count = len(p)

    def by_count(rates: np.ndarray) -> float:
        return float(np.prod(1.0 + rates) ** (per_year / len(rates)) - 1.0)

    def tail_mean(rates: np.ndarray) -> float:
        cut = int((len(rates) - 1) * 0.05)
        return float(np.mean(np.partition(rates, cut)[: cut + 1]))

    rows: list[tuple[str, float, Callable[[], float], float | None]] = [
        ("total return", link(p.tolist()), lambda: float(ep.cum_returns_final(p)), None),
        ("annual return", mine.annual_return, lambda: float(ep.annual_return(p, period=period)), by_count(p)),
        ("volatility", mine.volatility, lambda: float(ep.annual_volatility(p, period=period)), None),
        ("downside deviation", mine.downside_deviation,
         lambda: float(ep.downside_risk(p, required_return=rf, period=period)), None),
        ("Sharpe ratio", mine.sharpe, lambda: float(ep.sharpe_ratio(p, risk_free=rf, period=period)),
         float(excess.mean() / excess.std(ddof=1) * math.sqrt(per_year))),
        ("Sortino ratio", mine.sortino, lambda: float(ep.sortino_ratio(p, required_return=rf, period=period)),
         float(excess.mean() * per_year / mine.downside_deviation)),
        ("maximum drawdown", mine.max_drawdown, lambda: float(ep.max_drawdown(p)), None),
        ("value at risk 95%", mine.var_95, lambda: float(ep.value_at_risk(p, cutoff=0.05)), None),
        ("expected shortfall", mine.expected_shortfall_95,
         lambda: float(ep.conditional_value_at_risk(p, cutoff=0.05)), tail_mean(p)),
        ("skewness", mine.skewness, lambda: float(stats.skew(p)), None),
        ("excess kurtosis", mine.excess_kurtosis, lambda: float(stats.kurtosis(p)), None),
        ("beta", rel.beta, lambda: beta, None),
        ("alpha", rel.alpha, lambda: float(ep.alpha(p, b, risk_free=rf, period=period)),
         float((1.0 + np.mean(excess - beta * (b - rf))) ** per_year - 1.0)),
        ("up capture", rel.up_capture, lambda: float(ep.up_capture(p, b, period=period)),
         capture_ratio(p[b > 0], b[b > 0], per_year)),
        ("down capture", rel.down_capture, lambda: float(ep.down_capture(p, b, period=period)),
         capture_ratio(p[b < 0], b[b < 0], per_year)),
    ]  # fmt: skip
    del count
    return [Comparison(dataset, name, float(ours), theirs(), recombined) for name, ours, theirs, recombined in rows]


def reconciliation() -> list[Comparison]:
    """Both datasets: the demonstration account daily, and a century of US returns monthly."""
    from ..services.century_review import equal_weight_series, market_series
    from ..services.demo_performance import build_demo_performance

    demo = build_demo_performance()
    return [
        *compare(demo.portfolio_returns, demo.benchmark_returns, 0.04, "demonstration account, daily"),
        *compare(equal_weight_series(), market_series(), 0.0, "US equal-weighted market, monthly since 1926"),
    ]
