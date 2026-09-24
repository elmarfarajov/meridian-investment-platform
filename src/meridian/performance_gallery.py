"""The Day 4 charts: performance and attribution of the demonstration account.

Data preparation lives here and the chart functions take plain inputs, as for
the Day 3 charts, so every figure is rebuilt deterministically by
``meridian charts gallery`` and shows the numbers the tests assert.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from matplotlib.figure import Figure

from .performance.contributions import holding_contributions
from .performance.returns import ReturnSeries, flows_of, modified_dietz, money_weighted_return, standard_periods
from .performance.statistics import RiskReturn, risk_return, summary_rows
from .services.demo_performance import DemoPerformance, build_demo_performance
from .viz.performance import (
    plot_active_distribution,
    plot_attribution_bridge,
    plot_attribution_calendar,
    plot_contributions,
    plot_cumulative_performance,
    plot_currency_attribution,
    plot_drawdown_episodes,
    plot_factsheet,
    plot_linking,
    plot_monthly_returns,
    plot_return_methods,
    plot_risk_return,
    plot_rolling_risk,
    plot_segment_attribution,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem


def _perf() -> DemoPerformance:
    return build_demo_performance()


def return_method_rows(perf: DemoPerformance) -> list[tuple[str, float, float, float]]:
    """For each calendar year and since inception: time-weighted, money-weighted over the period, Modified Dietz."""
    series = perf.portfolio_returns
    bridges = perf.accounting.daily_bridges
    start, end = series.start, series.days[-1]
    periods = [
        (str(year), max(start, date(year - 1, 12, 31)), min(end, date(year, 12, 31)))
        for year in range(start.year, end.year + 1)
    ]
    periods.append(("Since inception", start, end))
    rows = []
    for label, first, last in periods:
        steps = [step for step in bridges if first < step.end <= last]
        opening, closing = float(steps[0].opening), float(steps[-1].closing)
        flows = flows_of(steps)
        rows.append(
            (
                label,
                series.total(first, last),
                money_weighted_return(opening, closing, flows, first, last).period,
                modified_dietz(opening, closing, flows, first, last),
            )
        )
    return rows


def holding_series(perf: DemoPerformance) -> dict[str, ReturnSeries]:
    """Each holding's own daily return in dollars on the days it was held from the start of the day."""
    found: dict[str, list[tuple[date, float]]] = {}
    for day in perf.portfolio_days:
        for exposure in day.exposures:
            if exposure.is_cash or exposure.value <= 0:
                continue
            found.setdefault(exposure.key, []).append((day.day, exposure.result / exposure.value))
    return {
        key: ReturnSeries(tuple(day for day, _ in rows), tuple(rate for _, rate in rows), key)
        for key, rows in found.items()
        if len(rows) > 60
    }


def cumulative_chart() -> Figure:
    perf = _perf()
    return plot_cumulative_performance(perf.portfolio_returns, perf.benchmark_returns, perf.equity_returns)


def bridge_chart() -> Figure:
    return plot_attribution_bridge(_perf().by_sector)


def sector_chart() -> Figure:
    return plot_segment_attribution(_perf().by_sector, title="Attribution by sector")


def region_chart() -> Figure:
    return plot_segment_attribution(_perf().by_region, title="Attribution by region")


def calendar_chart() -> Figure:
    return plot_attribution_calendar(_perf().monthly_by_sector)


def linking_chart() -> Figure:
    return plot_linking(_perf().by_sector)


def methods_chart() -> Figure:
    perf = _perf()
    nav = [(item.day, float(item.nav)) for item in perf.accounting.valuations]
    return plot_return_methods(return_method_rows(perf), nav, flows_of(perf.accounting.daily_bridges)[1:])


def monthly_chart() -> Figure:
    perf = _perf()
    return plot_monthly_returns(perf.portfolio_returns, perf.benchmark_returns)


def rolling_chart() -> Figure:
    perf = _perf()
    return plot_rolling_risk(perf.portfolio_returns, perf.benchmark_returns)


def risk_return_chart() -> Figure:
    perf = _perf()
    points: dict[str, RiskReturn] = {
        "Global Equity Core": risk_return(perf.portfolio_returns),
        "Policy benchmark": risk_return(perf.benchmark_returns),
        "Meridian World Equity": risk_return(perf.equity_returns),
    }
    for key, series in sorted(holding_series(perf).items()):
        points[key] = risk_return(series)
    return plot_risk_return(points, ["Global Equity Core", "Policy benchmark", "Meridian World Equity"])


def drawdown_chart() -> Figure:
    perf = _perf()
    return plot_drawdown_episodes(perf.portfolio_returns, perf.benchmark_returns)


def currency_chart() -> Figure:
    return plot_currency_attribution(_perf().by_sector)


def contribution_chart() -> Figure:
    perf = _perf()
    return plot_contributions(
        holding_contributions(perf.portfolio_days), perf.portfolio_days, perf.portfolio_returns.total()
    )


def active_chart() -> Figure:
    perf = _perf()
    return plot_active_distribution(perf.portfolio_returns, perf.benchmark_returns)


def factsheet_chart() -> Figure:
    perf = _perf()
    mine, theirs = standard_periods(perf.portfolio_returns), standard_periods(perf.benchmark_returns)
    return plot_factsheet(
        perf.accounting.portfolio.name,
        perf.portfolio_returns,
        perf.benchmark_returns,
        list(zip(mine, theirs, strict=True)),
        summary_rows(perf.portfolio_returns, perf.benchmark_returns),
        perf.by_sector,
        holding_contributions(perf.portfolio_days),
        perf.portfolio_returns.days[-1],
    )


def performance_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "cumulative-performance.png",
            "Performance against the benchmark",
            "Growth of 100, the active return accumulating, and the drawdowns of both.",
            cumulative_chart,
            "performance",
        ),
        GalleryItem(
            "attribution-bridge.png",
            "From the benchmark's return to the portfolio's",
            "Allocation, selection, interaction, currency and costs, linked by Cariño, and by sector.",
            bridge_chart,
            "performance",
        ),
        GalleryItem(
            "sector-attribution.png",
            "Attribution by sector",
            "Average weights, local returns and the three Brinson-Fachler effects, sector by sector.",
            sector_chart,
            "performance",
        ),
        GalleryItem(
            "region-attribution.png",
            "Attribution by region",
            "The same active return decomposed by region, index funds looked through.",
            region_chart,
            "performance",
        ),
        GalleryItem(
            "attribution-calendar.png",
            "Attribution, month by month",
            "Each month's effects by sector, linked within the month so the rows add up.",
            calendar_chart,
            "performance",
        ),
        GalleryItem(
            "attribution-linking.png",
            "Why effects have to be linked",
            "The plain sum of daily active returns drifts from the compounded active return; Cariño closes the gap.",
            linking_chart,
            "performance",
        ),
        GalleryItem(
            "return-methods.png",
            "Which return?",
            "Time-weighted, money-weighted and Modified Dietz, year by year, with the client's flows.",
            methods_chart,
            "performance",
        ),
        GalleryItem(
            "monthly-returns.png",
            "Returns by month",
            "A calendar of monthly returns and of active returns against the benchmark.",
            monthly_chart,
            "performance",
        ),
        GalleryItem(
            "rolling-risk.png",
            "Risk, as it moved",
            "Rolling volatility, tracking error, information ratio and beta.",
            rolling_chart,
            "performance",
        ),
        GalleryItem(
            "risk-return.png",
            "Return against risk",
            "The portfolio, its benchmark and every holding, with lines of equal Sharpe ratio.",
            risk_return_chart,
            "performance",
        ),
        GalleryItem(
            "drawdown-episodes.png",
            "Drawdowns",
            "The deepest falls from peak, how long they lasted and whether they recovered.",
            drawdown_chart,
            "performance",
        ),
        GalleryItem(
            "currency-attribution.png",
            "Currency, kept apart",
            "Currency weights against the benchmark's and the effect of each currency.",
            currency_chart,
            "performance",
        ),
        GalleryItem(
            "contribution-to-return.png",
            "Who drove the return",
            "Each holding's linked contribution to the time-weighted return.",
            contribution_chart,
            "performance",
        ),
        GalleryItem(
            "active-days.png",
            "Day by day against the benchmark",
            "The distribution of daily active returns, beta, and up and down capture.",
            active_chart,
            "performance",
        ),
        GalleryItem(
            "factsheet.png",
            "The performance report",
            "The one page a client reads: returns by period, risk, attribution and contributions.",
            factsheet_chart,
            "performance",
        ),
    )
