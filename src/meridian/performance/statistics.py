"""Risk-adjusted performance: the numbers a factsheet puts next to the return.

A return means little without the risk taken to earn it, and an active return
means little without the active risk. The measures here are the standard ones,
computed from daily time-weighted returns and annualised with 252 trading days:

* **Volatility** and **downside deviation**; the **Sharpe** ratio (excess return
  over the risk-free rate per unit of volatility) and the **Sortino** ratio (per
  unit of downside deviation only - a manager is not penalised for upside).
* **Tracking error**, the volatility of the active return, and the
  **information ratio**, annualised active return per unit of it: the measure of
  active skill.
* **Beta** and **Jensen's alpha** against the benchmark, **correlation**, and the
  **up and down capture** ratios: how much of the benchmark's good days and bad
  days the portfolio took part in.
* **Maximum drawdown** with its peak, trough and recovery; historical **value at
  risk** and **expected shortfall** at 95%; skewness and excess kurtosis.

The risk-free rate is a parameter, not a series: the demonstration uses a flat
4% a year, roughly the Treasury bill rate over the period.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from ..core.exceptions import ValidationError
from .returns import TRADING_DAYS, ReturnSeries, annualise, link

DEFAULT_RISK_FREE = 0.04


@dataclass(frozen=True)
class Drawdown:
    peak: date
    trough: date
    recovery: date | None
    depth: float

    @property
    def length(self) -> int:
        """Calendar days from peak to recovery (or to the trough if not yet recovered)."""
        return ((self.recovery or self.trough) - self.peak).days


def drawdown_episodes(series: ReturnSeries, count: int = 5) -> list[Drawdown]:
    """The deepest peak-to-trough falls, each with the day it recovered, if it has."""
    index = series.index(1.0)
    episodes: list[Drawdown] = []
    peak_day, peak = index[0]
    trough_day, trough = peak_day, peak
    in_drawdown = False
    for day, level in index[1:]:
        if level >= peak:
            if in_drawdown:
                episodes.append(Drawdown(peak_day, trough_day, day, trough / peak - 1.0))
                in_drawdown = False
            peak_day, peak = day, level
            trough_day, trough = day, level
        else:
            in_drawdown = True
            if level < trough:
                trough_day, trough = day, level
    if in_drawdown:
        episodes.append(Drawdown(peak_day, trough_day, None, trough / peak - 1.0))
    return sorted(episodes, key=lambda item: item.depth)[:count]


def _array(series: ReturnSeries) -> np.ndarray:
    return np.asarray(series.rates, dtype=float)


def _aligned(portfolio: ReturnSeries, benchmark: ReturnSeries) -> tuple[np.ndarray, np.ndarray]:
    common = sorted(set(portfolio.days) & set(benchmark.days))
    if len(common) < 2:
        raise ValidationError("the portfolio and benchmark share fewer than two days")
    p = dict(zip(portfolio.days, portfolio.rates, strict=True))
    b = dict(zip(benchmark.days, benchmark.rates, strict=True))
    return np.array([p[day] for day in common]), np.array([b[day] for day in common])


@dataclass(frozen=True)
class RiskReturn:
    """Absolute measures of one return series."""

    total: float
    annual_return: float
    volatility: float
    downside_deviation: float
    sharpe: float
    sortino: float
    max_drawdown: float
    var_95: float  # daily, as a (negative) return
    expected_shortfall_95: float
    skewness: float
    excess_kurtosis: float
    best_day: float
    worst_day: float
    positive_days: float


def risk_return(series: ReturnSeries, *, risk_free: float = DEFAULT_RISK_FREE) -> RiskReturn:
    rates = _array(series)
    if len(rates) < 2:
        raise ValidationError("risk measures need at least two returns")
    total = link(rates.tolist())
    annual = annualise(total, series.start, series.days[-1])
    volatility = float(rates.std(ddof=1) * math.sqrt(TRADING_DAYS))
    daily_rf = (1.0 + risk_free) ** (1.0 / TRADING_DAYS) - 1.0
    downside = rates[rates < daily_rf] - daily_rf
    downside_deviation = float(math.sqrt((downside**2).sum() / len(rates)) * math.sqrt(TRADING_DAYS))
    var_95 = float(np.quantile(rates, 0.05))
    tail = rates[rates <= var_95]
    standardised = (rates - rates.mean()) / rates.std(ddof=0)
    return RiskReturn(
        total=total,
        annual_return=annual,
        volatility=volatility,
        downside_deviation=downside_deviation,
        sharpe=(annual - risk_free) / volatility if volatility else 0.0,
        sortino=(annual - risk_free) / downside_deviation if downside_deviation else 0.0,
        max_drawdown=min(value for _, value in series.drawdowns()),
        var_95=var_95,
        expected_shortfall_95=float(tail.mean()) if len(tail) else var_95,
        skewness=float((standardised**3).mean()),
        excess_kurtosis=float((standardised**4).mean() - 3.0),
        best_day=float(rates.max()),
        worst_day=float(rates.min()),
        positive_days=float((rates > 0).mean()),
    )


@dataclass(frozen=True)
class Relative:
    """Measures of the portfolio against its benchmark."""

    active_return: float  # annualised portfolio less annualised benchmark
    tracking_error: float
    information_ratio: float
    beta: float
    alpha: float  # Jensen's, annualised
    correlation: float
    up_capture: float
    down_capture: float
    hit_rate: float  # share of days the portfolio beat the benchmark


def relative(portfolio: ReturnSeries, benchmark: ReturnSeries, *, risk_free: float = DEFAULT_RISK_FREE) -> Relative:
    p, b = _aligned(portfolio, benchmark)
    start = min(portfolio.start, benchmark.start)
    end = max(portfolio.days[-1], benchmark.days[-1])
    annual_p = annualise(link(p.tolist()), start, end)
    annual_b = annualise(link(b.tolist()), start, end)
    active = p - b
    tracking_error = float(active.std(ddof=1) * math.sqrt(TRADING_DAYS))
    variance_b = float(b.var(ddof=1))
    beta = float(np.cov(p, b, ddof=1)[0, 1] / variance_b) if variance_b else 0.0
    up, down = b > 0, b < 0
    up_capture = (link(p[up].tolist()) / link(b[up].tolist())) if up.any() else 0.0
    down_capture = (link(p[down].tolist()) / link(b[down].tolist())) if down.any() else 0.0
    return Relative(
        active_return=annual_p - annual_b,
        tracking_error=tracking_error,
        information_ratio=(annual_p - annual_b) / tracking_error if tracking_error else 0.0,
        beta=beta,
        alpha=annual_p - (risk_free + beta * (annual_b - risk_free)),
        correlation=float(np.corrcoef(p, b)[0, 1]),
        up_capture=up_capture,
        down_capture=down_capture,
        hit_rate=float((active > 0).mean()),
    )


@dataclass(frozen=True)
class RollingPoint:
    day: date
    volatility: float
    benchmark_volatility: float
    tracking_error: float
    information_ratio: float
    beta: float


def rolling(portfolio: ReturnSeries, benchmark: ReturnSeries, window: int = 63) -> list[RollingPoint]:
    """Rolling annualised measures over ``window`` trading days (63 is a quarter)."""
    p, b = _aligned(portfolio, benchmark)
    days = sorted(set(portfolio.days) & set(benchmark.days))
    points: list[RollingPoint] = []
    for end in range(window, len(days) + 1):
        pw, bw = p[end - window : end], b[end - window : end]
        active = pw - bw
        te = float(active.std(ddof=1) * math.sqrt(TRADING_DAYS))
        annual_active = float(active.mean() * TRADING_DAYS)
        variance = float(bw.var(ddof=1))
        points.append(
            RollingPoint(
                days[end - 1],
                float(pw.std(ddof=1) * math.sqrt(TRADING_DAYS)),
                float(bw.std(ddof=1) * math.sqrt(TRADING_DAYS)),
                te,
                annual_active / te if te else 0.0,
                float(np.cov(pw, bw, ddof=1)[0, 1] / variance) if variance else 0.0,
            )
        )
    return points


def calendar_table(series: ReturnSeries) -> dict[int, dict[int, float]]:
    """Monthly returns as {year: {month: return}}, with month 13 holding the year."""
    table: dict[int, dict[int, float]] = {}
    for day, value in series.monthly():
        table.setdefault(day.year, {})[day.month] = value
    for year, value in series.yearly():
        table.setdefault(year, {})[13] = value
    return table


def summary_rows(
    portfolio: ReturnSeries, benchmark: ReturnSeries, *, risk_free: float = DEFAULT_RISK_FREE
) -> list[tuple[str, str, str]]:
    """Measure, portfolio, benchmark: the rows of a factsheet's risk table."""
    mine, theirs = risk_return(portfolio, risk_free=risk_free), risk_return(benchmark, risk_free=risk_free)
    rel = relative(portfolio, benchmark, risk_free=risk_free)

    def pct(value: float) -> str:
        return f"{value:.2%}"

    rows: list[tuple[str, str, str]] = [
        ("Total return", pct(mine.total), pct(theirs.total)),
        ("Annualised return", pct(mine.annual_return), pct(theirs.annual_return)),
        ("Volatility", pct(mine.volatility), pct(theirs.volatility)),
        ("Sharpe ratio", f"{mine.sharpe:.2f}", f"{theirs.sharpe:.2f}"),
        ("Sortino ratio", f"{mine.sortino:.2f}", f"{theirs.sortino:.2f}"),
        ("Maximum drawdown", pct(mine.max_drawdown), pct(theirs.max_drawdown)),
        ("Daily VaR 95%", pct(mine.var_95), pct(theirs.var_95)),
        ("Expected shortfall 95%", pct(mine.expected_shortfall_95), pct(theirs.expected_shortfall_95)),
        ("Tracking error", pct(rel.tracking_error), ""),
        ("Information ratio", f"{rel.information_ratio:.2f}", ""),
        ("Beta", f"{rel.beta:.2f}", "1.00"),
        ("Alpha (Jensen)", pct(rel.alpha), ""),
        ("Up capture", pct(rel.up_capture), ""),
        ("Down capture", pct(rel.down_capture), ""),
    ]
    return rows
