"""The Day 4 revisit charts: performance against empyrical, and on a century of real US returns.

The real-data charts draw from :mod:`meridian.services.century_review`, the same
functions the tests check, so a chart cannot show a figure the tests do not.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .devtools.performance_reference import reconciliation
from .marketdata.french import INDUSTRY_NAMES, french_history
from .performance.returns import link, xirr
from .performance.statistics import capture_ratio, drawdown_episodes, risk_return
from .services import century_review as century
from .viz.century import (
    DecadeBar,
    Episode,
    ReferenceRow,
    ReviewPanel,
    plot_century_drawdowns,
    plot_decades,
    plot_industry_weights,
    plot_linking,
    plot_rebuilt_market,
    plot_reference,
    plot_review,
    plot_rolling_sharpe,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

EFFECTS = ("allocation", "selection", "interaction")
ROLLING_MONTHS = 120
MICROSOFT_FLOWS = [
    (date(2008, 1, 1), -10000.0),
    (date(2008, 3, 1), 2750.0),
    (date(2008, 10, 30), 4250.0),
    (date(2009, 2, 15), 3250.0),
    (date(2009, 4, 1), 2750.0),
]


def reference_chart() -> Figure:
    rows = [
        ReferenceRow(
            item.dataset, item.measure, item.meridian, item.empyrical, item.under_their_convention, item.agrees
        )
        for item in reconciliation()
    ]
    return plot_reference(rows)


def rebuilt_chart() -> Figure:
    check = century.benchmark_check()
    return plot_rebuilt_market(
        check.months, check.rebuilt, check.published, check.rms_by_decade(), check.largest_gap, check.correlation
    )


def weights_chart() -> Figure:
    history = french_history()
    weights = {name: [history.weights(month)[name] for month in history.months] for name in history.industries}
    order = sorted(history.industries, key=lambda name: weights[name][-1])
    return plot_industry_weights(history.months, {name: weights[name] for name in order}, INDUSTRY_NAMES)


def _annual(total: float, months: int) -> float:
    return float((1.0 + total) ** (12.0 / months) - 1.0)


def decades_chart() -> Figure:
    bars = [
        DecadeBar(label, result.portfolio, result.benchmark, {effect: result.effect(effect) for effect in EFFECTS})
        for label, result in century.decade_attribution()
    ]
    whole = century.equal_weight_attribution()
    months = len(whole.days)
    return plot_decades(bars, (_annual(whole.portfolio, months), _annual(whole.benchmark, months)))


def linking_chart() -> Figure:
    history = french_history()
    last_year_start = history.months[-13]
    short = century.linking_comparison(start=last_year_start)
    long = century.linking_comparison()

    def effects(results):  # type: ignore[no-untyped-def]
        return {method: {effect: result.effect(effect) for effect in EFFECTS} for method, result in results.items()}

    short_any, long_any = next(iter(short.values())), next(iter(long.values()))
    return plot_linking(
        effects(short),
        short_any.active,
        f"The last 12 months, to {history.months[-1]:%B %Y}",
        effects(long),
        long_any.active,
        f"The century since July 1926 ({len(long_any.days):,} months)",
        rf"\$1 became \${1 + long_any.portfolio:,.0f} against \${1 + long_any.benchmark:,.0f}",
    )


def drawdown_chart() -> Figure:
    market = century.market_series()
    points = market.drawdowns()
    episodes = [Episode(item.peak, item.trough, item.recovery, item.depth) for item in drawdown_episodes(market, 5)]
    return plot_century_drawdowns([day for day, _ in points], [value for _, value in points], episodes)


def rolling_sharpe_chart() -> Figure:
    excess = np.array(century.excess_series().rates)
    market = np.array(century.market_series().rates)
    months = century.market_series().days
    days, sharpe, volatility = [], [], []
    for end in range(ROLLING_MONTHS, len(excess) + 1):
        window = excess[end - ROLLING_MONTHS : end]
        days.append(months[end - 1])
        sharpe.append(float(window.mean() / window.std(ddof=1) * math.sqrt(12)))
        volatility.append(float(market[end - ROLLING_MONTHS : end].std(ddof=1) * math.sqrt(12)))
    decades = {}
    for label, _ in century.decade_attribution():
        decade = int(label[:4])
        chosen = [rate for day, rate in zip(months, excess, strict=True) if decade <= day.year < decade + 10]
        values = np.array(chosen)
        decades[label] = float(values.mean() / values.std(ddof=1) * math.sqrt(12))
    return plot_rolling_sharpe(days, sharpe, volatility, decades)


def _xirr_at(basis: float) -> float:
    """XIRR of Microsoft's example on a given day basis, by bisection (only for the before-and-after chart)."""
    origin = MICROSOFT_FLOWS[0][0]

    def value(rate: float) -> float:
        return float(sum(amount / (1.0 + rate) ** ((day - origin).days / basis) for day, amount in MICROSOFT_FLOWS))

    low, high = 0.0, 1.0
    for _ in range(200):
        middle = (low + high) / 2
        low, high = (middle, high) if value(middle) > 0 else (low, middle)
    return (low + high) / 2


def review_chart() -> Figure:
    from .services.demo_performance import build_demo_performance

    perf = build_demo_performance()
    series = perf.portfolio_returns
    end = date(2026, 3, 31)
    old_start, new_start = date(2025, 3, 28), date(2025, 3, 31)
    benchmark = np.array(perf.benchmark_returns.rates)
    capture_before, capture_after = [], []
    for leverage in (1.5, 2.0):
        portfolio = benchmark * leverage
        up = benchmark > 0
        capture_before.append(link(portfolio[up].tolist()) / link(benchmark[up].tolist()))
        capture_after.append(capture_ratio(portfolio[up], benchmark[up], 252))
    quarters = [
        (date(2025, 3, 31), date(2025, 6, 30)),
        (date(2025, 6, 30), date(2025, 9, 30)),
        (date(2025, 9, 30), date(2025, 12, 31)),
        (date(2025, 12, 31), date(2026, 3, 31)),
    ]
    sharpe_before, sharpe_after, labels = [], [], []
    for start, stop in quarters:
        part = series.between(start, stop)
        measures = risk_return(part, risk_free=0.04)
        sharpe_before.append((measures.total - 0.04) / measures.volatility)
        sharpe_after.append(measures.sharpe)
        labels.append(f"Q to {stop:%b %y}")
    old_xirr = _xirr_at(365.25)
    panels = [
        ReviewPanel(
            "XIRR on Microsoft's own example (%)",
            ("XIRR",),
            (old_xirr * 100,),
            (xirr(MICROSOFT_FLOWS) * 100,),
            ".4f",
            f"Years of 365.25 days gave {old_xirr:.4%}; Excel's 365 gives {xirr(MICROSOFT_FLOWS):.4%}, the "
            "figure Microsoft prints (37.3362535%) and a client checks against.",
        ),
        ReviewPanel(
            "Up capture of a leveraged portfolio",
            ("1.5x", "2x"),
            tuple(capture_before),
            tuple(capture_after),
            ".3f",
            "A ratio of compounded totals; now Morningstar's and empyrical's ratio of returns annualised over "
            "the benchmark's up days. Both rise with leverage; the old figures ran away with it.",
        ),
        ReviewPanel(
            "The trailing year to 31 March 2026 (%)",
            ("1-year return",),
            (series.total(old_start, end) * 100,),
            (series.total(new_start, end) * 100,),
            ".2f",
            "Day 4 started the year on the 28th (min(day, 28)), so it held three extra days. It starts on 31 "
            "March now.",
        ),
        ReviewPanel(
            "Sharpe ratio of a single quarter",
            tuple(labels),
            tuple(sharpe_before),
            tuple(sharpe_after),
            ".2f",
            "A quarter's return was set against an annual 4% risk-free rate and an annualised volatility. "
            "It is now annualised first, as the other two terms are.",
        ),
    ]
    return plot_review(panels)


def century_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "empyrical-reconciliation.png",
            "Every measure against empyrical",
            "Thirty measures on two datasets: agreeing to 1e-10, or differing by a convention that "
            "accounts for every digit.",
            reference_chart,
            "validation",
        ),
        GalleryItem(
            "market-rebuilt.png",
            "The US market rebuilt from twelve industries",
            "A cap-weighted index of its industries since 1926, against the market Fama and French publish.",
            rebuilt_chart,
            "performance",
        ),
        GalleryItem(
            "industry-weights.png",
            "A century of the market's composition",
            "Each industry's share of the US market's value, every month since July 1926.",
            weights_chart,
            "performance",
        ),
        GalleryItem(
            "equal-weight-attribution.png",
            "Equal weight against cap weight, decade by decade",
            "Brinson-Fachler by industry on a century of real returns.",
            decades_chart,
            "performance",
        ),
        GalleryItem(
            "linking-methods.png",
            "Four linking methods, one total",
            "Cariño, Menchero, GRAP and Frongello over a year and over a century.",
            linking_chart,
            "performance",
        ),
        GalleryItem(
            "century-drawdowns.png",
            "A century of drawdowns",
            "How far below its last peak the US market was, every month since 1926.",
            drawdown_chart,
            "performance",
        ),
        GalleryItem(
            "rolling-sharpe.png",
            "Ten years at a time",
            "The rolling ten-year Sharpe ratio of the US market, and by decade.",
            rolling_sharpe_chart,
            "performance",
        ),
        GalleryItem(
            "performance-review.png",
            "A second reading of Day 4",
            "Four faults, each figure before and after the fix.",
            review_chart,
            "performance",
        ),
    )
