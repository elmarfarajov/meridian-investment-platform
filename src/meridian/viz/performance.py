"""Charts for performance and attribution.

What a performance report has to answer, one chart per question:

* **How did it do against its benchmark?** Growth of 100, the active return
  accumulating, and the drawdowns.
* **Why?** The attribution bridge from benchmark to portfolio, by sector and by
  region, month by month, currency apart - and why the effects have to be linked.
* **Which return?** Time-weighted against money-weighted against Modified Dietz.
* **At what risk?** Rolling volatility, tracking error and beta; return against
  risk for every holding; the drawdown episodes; the distribution of active days.
* **Who drove it?** Each holding's contribution.
* **The page the client reads**: a one-page factsheet.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from ..performance.attribution import EFFECTS, AttributionResult, carino_factor
from ..performance.contributions import PortfolioDay
from ..performance.returns import PeriodReturn, ReturnSeries
from ..performance.statistics import (
    RiskReturn,
    calendar_table,
    drawdown_episodes,
    relative,
    rolling,
)
from .accounting import _margins
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block, x_of

EFFECT_COLOURS = {
    "allocation": PALETTE["navy"],
    "selection": PALETTE["teal"],
    "interaction": PALETTE["violet"],
    "currency": PALETTE["sky"],
    "costs": PALETTE["slate"],
}
PORTFOLIO_COLOUR = PALETTE["navy"]
BENCHMARK_COLOUR = PALETTE["slate"]
EQUITY_COLOUR = PALETTE["sky"]
_DIVERGING = LinearSegmentedColormap.from_list("active", ["#B3202C", "#F2D4D6", "#FFFFFF", "#CFE8DB", "#2E7D5B"], N=256)


def _pct(value: float, places: int = 1, signed: bool = False) -> str:
    return f"{value:+.{places}%}" if signed else f"{value:.{places}%}"


def _bp(value: float) -> str:
    return f"{value * 1e4:+,.0f} bp"


def _percent_axis(axis, which: str = "y", places: int = 0) -> None:  # type: ignore[no-untyped-def]
    target = axis.yaxis if which == "y" else axis.xaxis
    target.set_major_formatter(lambda value, _: f"{value:.{places}%}")


# ---------------------------------------------------------------------------- 1. cumulative performance
def plot_cumulative_performance(
    portfolio: ReturnSeries, benchmark: ReturnSeries, equity: ReturnSeries | None = None
) -> Figure:
    figure = new_figure(15.5, 10.0)
    grid = figure.add_gridspec(3, 1, height_ratios=[1.6, 0.8, 0.8], hspace=0.28, **_margins(figure, bottom=0.9))
    growth = figure.add_subplot(grid[0])
    for series, colour, width in ((portfolio, PORTFOLIO_COLOUR, 2.2), (benchmark, BENCHMARK_COLOUR, 1.6)):
        points = series.index(100.0)
        growth.plot(
            [day for day, _ in points],
            [value for _, value in points],
            color=colour,
            linewidth=width,
            label=f"{series.name}  {_pct(series.total(), signed=True)}",
        )
    if equity is not None:
        points = equity.index(100.0)
        growth.plot(
            [day for day, _ in points],
            [value for _, value in points],
            color=EQUITY_COLOUR,
            linewidth=1.1,
            linestyle="--",
            label=f"{equity.name}  {_pct(equity.total(), signed=True)}",
        )
    p_points, b_points = portfolio.index(100.0), benchmark.index(100.0)
    days = [day for day, _ in p_points]
    p_values = np.array([value for _, value in p_points])
    b_values = np.array([value for _, value in b_points])
    growth.fill_between(
        days, p_values, b_values, where=p_values >= b_values, color=PALETTE["gain"], alpha=0.12, interpolate=True
    )
    growth.fill_between(
        days, p_values, b_values, where=p_values < b_values, color=PALETTE["loss"], alpha=0.12, interpolate=True
    )
    growth.axhline(100, color=PALETTE["muted"], linewidth=0.8)
    style_axes(growth, title="Growth of 100, time-weighted, net of costs")
    growth.legend(loc="upper left")

    active = figure.add_subplot(grid[1], sharex=growth)
    relative_path = p_values / b_values - 1.0
    active.fill_between(
        days, relative_path, 0, where=relative_path >= 0, color=PALETTE["gain"], alpha=0.35, interpolate=True
    )
    active.fill_between(
        days, relative_path, 0, where=relative_path < 0, color=PALETTE["loss"], alpha=0.35, interpolate=True
    )
    active.plot(days, relative_path, color=PALETTE["ink"], linewidth=1.0)
    active.axhline(0, color=PALETTE["muted"], linewidth=0.8)
    _percent_axis(active, places=1)
    style_axes(active, title="Cumulative active return (portfolio growth over benchmark growth, less one)")
    annotate(
        active,
        f"{relative_path[-1]:+.2%} at the end",
        (x_of(days[-1]), float(relative_path[-1])),
        highlight=True,
        xytext=(-120, 12),
        textcoords="offset points",
    )

    under = figure.add_subplot(grid[2], sharex=growth)
    for series, colour in ((portfolio, PORTFOLIO_COLOUR), (benchmark, BENCHMARK_COLOUR)):
        drawdowns = series.drawdowns()
        under.fill_between(
            [day for day, _ in drawdowns], [value for _, value in drawdowns], 0, color=colour, alpha=0.25
        )
        under.plot(
            [day for day, _ in drawdowns],
            [value for _, value in drawdowns],
            color=colour,
            linewidth=0.9,
            label=f"{series.name}: worst {_pct(min(v for _, v in drawdowns))}",
        )
    _percent_axis(under)
    style_axes(under, title="Drawdown from the running peak")
    under.legend(loc="lower left")
    title_block(
        figure,
        "Performance against the policy benchmark",
        "Daily time-weighted returns from the book of record, chained; the benchmark is 80% Meridian World Equity, "
        "15% the US Treasury and 5% cash, rebalanced monthly.",
    )
    caption(figure, "Returns are in US dollars and net of every commission, fee, tax and unreclaimable withholding.")
    return figure


# ---------------------------------------------------------------------------- 2. attribution bridge
def plot_attribution_bridge(result: AttributionResult, *, title: str | None = None) -> Figure:
    figure = new_figure(15.8, 7.8)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.25, 1.0], wspace=0.3, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    steps = [("Benchmark", result.benchmark)] + [
        (name.title(), result.effect(name)) for name in (*EFFECTS, "currency", "costs")
    ]
    steps.append(("Portfolio", result.portfolio))
    running = 0.0
    levels = [0.0]
    for index, (label, value) in enumerate(steps):
        levels += [running, running + value] if label not in {"Benchmark", "Portfolio"} else [value]
        if label in {"Benchmark", "Portfolio"}:
            axis.bar(index, value, color=BENCHMARK_COLOUR if label == "Benchmark" else PORTFOLIO_COLOUR, width=0.62)
            running = value
            axis.annotate(
                _pct(value, 2, True),
                (index, value),
                xytext=(0, 5 if value >= 0 else -14),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                weight="bold",
            )
            continue
        colour = EFFECT_COLOURS[label.lower()]
        axis.bar(index, value, bottom=running, color=colour, width=0.62)
        edge = max(running, running + value) if value >= 0 else min(running, running + value)
        axis.annotate(
            _bp(value),
            (index, edge),
            xytext=(0, 5 if value >= 0 else -14),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            weight="bold",
            color=PALETTE["ink"],
        )
        axis.plot(
            [index - 0.31, index + 1.31], [running + value] * 2, color=PALETTE["muted"], linewidth=0.7, linestyle=":"
        )
        running += value
    low, high = min(levels), max(levels)
    pad = (high - low) * 0.14
    axis.set_ylim(low - pad, high + pad)
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.set_xticks(range(len(steps)), labels=[label for label, _ in steps])
    _percent_axis(axis, places=0)
    style_axes(
        axis, title=f"From the benchmark's return to the portfolio's, {result.start:%b %Y} to {result.end:%b %Y}"
    )
    annotate(
        axis,
        f"active {_pct(result.active, 2, True)}; residual {result.residual:.0e}",
        (0.02, 0.95),
        xycoords="axes fraction",
        highlight=True,
    )

    detail = figure.add_subplot(grid[1])
    segments = sorted(result.segments, key=lambda item: item.total)
    rows = np.arange(len(segments))
    left_pos = np.zeros(len(segments))
    left_neg = np.zeros(len(segments))
    for effect in EFFECTS:
        values = np.array([getattr(item, effect) for item in segments])
        starts = np.where(values >= 0, left_pos, left_neg)
        detail.barh(rows, values, left=starts, color=EFFECT_COLOURS[effect], height=0.6, label=effect)
        left_pos += np.where(values >= 0, values, 0)
        left_neg += np.where(values < 0, values, 0)
    for row, item in enumerate(segments):
        detail.text(max(left_pos[row], 0) + 0.0008, row, _bp(item.total), va="center", fontsize=7.8)
    detail.set_yticks(rows, labels=[item.segment for item in segments])
    detail.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    detail.xaxis.set_major_formatter(lambda value, _: f"{value * 1e4:+.0f}")
    style_axes(detail, title=f"By {result.dimension} (basis points)", grid="x")
    detail.legend(loc="lower right")
    title_block(
        figure,
        title or "Where the active return came from",
        "Brinson-Fachler on local returns, currency apart, costs apart; daily effects linked by Cariño so they add "
        "up to the compounded active return exactly.",
    )
    caption(
        figure, "Index funds are looked through to the benchmark's constituents. Effects in basis points of return."
    )
    return figure


# ---------------------------------------------------------------------------- 3/4. by segment
def plot_segment_attribution(result: AttributionResult, *, title: str) -> Figure:
    segments = sorted(result.segments, key=lambda item: -item.average_wb)
    figure = new_figure(15.8, 7.4)
    grid = figure.add_gridspec(
        1, 3, width_ratios=[1.0, 1.0, 1.15], wspace=0.08, **_margins(figure, bottom=1.0, left=0.14, right=0.93)
    )
    rows = np.arange(len(segments))
    weights = figure.add_subplot(grid[0])
    weights.barh(
        rows + 0.19, [item.average_wp for item in segments], height=0.36, color=PORTFOLIO_COLOUR, label="portfolio"
    )
    weights.barh(
        rows - 0.19, [item.average_wb for item in segments], height=0.36, color=BENCHMARK_COLOUR, label="benchmark"
    )
    weights.set_yticks(rows, labels=[item.segment for item in segments])
    weights.invert_yaxis()
    _percent_axis(weights, "x")
    style_axes(weights, title="Average weight", grid="x")
    weights.legend(loc="lower right")

    returns = figure.add_subplot(grid[1], sharey=weights)
    returns.barh(rows + 0.19, [item.portfolio_return for item in segments], height=0.36, color=PORTFOLIO_COLOUR)
    returns.barh(rows - 0.19, [item.benchmark_return for item in segments], height=0.36, color=BENCHMARK_COLOUR)
    returns.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    returns.tick_params(labelleft=False)
    _percent_axis(returns, "x")
    style_axes(returns, title="Local return over the period", grid="x")

    effects = figure.add_subplot(grid[2], sharey=weights)
    width = 0.26
    for offset, effect in zip((-width, 0.0, width), EFFECTS, strict=True):
        effects.barh(
            rows + offset,
            [getattr(item, effect) for item in segments],
            height=width,
            color=EFFECT_COLOURS[effect],
            label=effect,
        )
    for row, item in enumerate(segments):
        effects.text(
            1.02,
            row,
            _bp(item.total),
            transform=effects.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=8,
            weight="bold",
            color=PALETTE["gain"] if item.total >= 0 else PALETTE["loss"],
            clip_on=False,
        )
    effects.text(
        1.02,
        -0.9,
        "total",
        transform=effects.get_yaxis_transform(),
        ha="left",
        va="center",
        fontsize=7.6,
        color=PALETTE["muted"],
        clip_on=False,
    )
    effects.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    effects.tick_params(labelleft=False)
    effects.xaxis.set_major_formatter(lambda value, _: f"{value * 1e4:+.0f}")
    style_axes(effects, title="Effects (basis points)", grid="x")
    figure.legend(*effects.get_legend_handles_labels(), loc="lower right", ncol=3, bbox_to_anchor=(0.93, 0.01))
    title_block(
        figure,
        title,
        f"Allocation {_bp(result.effect('allocation'))}, selection {_bp(result.effect('selection'))}, interaction "
        f"{_bp(result.effect('interaction'))}; active return {_pct(result.active, 2, True)} from "
        f"{result.start:%d %b %Y} to {result.end:%d %b %Y}.",
    )
    caption(
        figure,
        "Allocation pays for being overweight a segment that beat the benchmark; selection for beating the segment.",
    )
    return figure


# ---------------------------------------------------------------------------- 5. calendar of effects
def plot_attribution_calendar(months: Sequence[AttributionResult]) -> Figure:
    names = sorted({item.segment for month in months for item in month.segments})
    matrix = np.array(
        [
            [month.segment(name).total if any(s.segment == name for s in month.segments) else 0.0 for name in names]
            for month in months
        ]
    )
    extra = np.array([[month.effect("currency"), month.effect("costs"), month.active] for month in months])
    figure = new_figure(15.8, 8.2)
    grid = figure.add_gridspec(
        1, 2, width_ratios=[len(names), 3.4], wspace=0.04, **_margins(figure, bottom=1.1, left=0.08)
    )
    axis = figure.add_subplot(grid[0])
    limit = float(np.abs(matrix).max()) or 1e-4
    axis.imshow(matrix.T, cmap=_DIVERGING, vmin=-limit, vmax=limit, aspect="auto")
    axis.set_yticks(range(len(names)), labels=names, fontsize=8)
    axis.set_xticks(range(len(months)), labels=[f"{month.end:%b\n%y}" for month in months], fontsize=6.8)
    for (column, row), value in np.ndenumerate(matrix):
        if abs(value) >= 0.0005:
            axis.text(column, row, f"{value * 1e4:.0f}", ha="center", va="center", fontsize=6, color=PALETTE["ink"])
    axis.grid(visible=False)
    axis.set_title("Allocation + selection + interaction by sector, each month (basis points)")
    side = figure.add_subplot(grid[1])
    limit_extra = float(np.abs(extra).max()) or 1e-4
    side.imshow(extra, cmap=_DIVERGING, vmin=-limit_extra, vmax=limit_extra, aspect="auto")
    side.set_xticks(range(3), labels=["currency", "costs", "active"], fontsize=8)
    side.set_yticks([])
    for (row, column), value in np.ndenumerate(extra):
        side.text(column, row, f"{value * 1e4:.0f}", ha="center", va="center", fontsize=6.4)
    side.grid(visible=False)
    side.set_title("And the rest")
    title_block(
        figure,
        "Attribution, month by month",
        "Each month's effects are linked within the month, so every row of the right-hand column is that month's "
        "active return exactly. Green added value against the benchmark; red took it away.",
    )
    caption(figure, "Colour scales are symmetric about zero; the right-hand panel has its own scale.")
    return figure


# ---------------------------------------------------------------------------- 6. why link
def plot_linking(result: AttributionResult) -> Figure:
    days = [item.day for item in result.days]
    arithmetic = np.cumsum([item.active for item in result.days])
    growth_p = np.cumprod([1.0 + item.portfolio for item in result.days])
    growth_b = np.cumprod([1.0 + item.benchmark for item in result.days])
    geometric = growth_p - growth_b
    factors = [carino_factor(item.portfolio, item.benchmark) for item in result.days]
    figure = new_figure(15.5, 7.6)
    grid = figure.add_gridspec(
        2,
        2,
        height_ratios=[1.4, 1.0],
        width_ratios=[1.5, 1.0],
        hspace=0.38,
        wspace=0.22,
        **_margins(figure, bottom=0.95),
    )
    axis = figure.add_subplot(grid[0, 0])
    axis.plot(days, geometric, color=PORTFOLIO_COLOUR, linewidth=2.0, label="active return, compounded (R - B)")
    axis.plot(
        days, arithmetic, color=PALETTE["accent"], linewidth=1.3, linestyle="--", label="sum of daily active returns"
    )
    axis.axhline(0, color=PALETTE["muted"], linewidth=0.8)
    _percent_axis(axis, places=1)
    style_axes(axis, title="What adding daily effects gets wrong")
    axis.legend(loc="lower left")
    gap = figure.add_subplot(grid[1, 0], sharex=axis)
    gap.fill_between(days, (geometric - arithmetic) * 1e4, color=PALETTE["accent"], alpha=0.3)
    gap.plot(days, (geometric - arithmetic) * 1e4, color=PALETTE["accent"], linewidth=1.0)
    gap.axhline(0, color=PALETTE["muted"], linewidth=0.8)
    style_axes(gap, title="The gap, in basis points: what linking has to put back")
    factor_axis = figure.add_subplot(grid[:, 1])
    big_k = carino_factor(result.portfolio, result.benchmark)
    factor_axis.hist(np.array(factors) / big_k, bins=40, color=PALETTE["teal"], alpha=0.85)
    factor_axis.axvline(1.0, color=PALETTE["ink"], linewidth=0.8)
    style_axes(factor_axis, title="Each day's Cariño scaling k_t / K", xlabel="scale applied to that day's effects")
    annotate(
        factor_axis,
        f"linked effects sum to R - B;\nresidual {result.residual:.0e}\nunlinked gap {_bp(result.linking_gap)}",
        (0.04, 0.84),
        xycoords="axes fraction",
        highlight=True,
    )
    title_block(
        figure,
        "Why attribution effects have to be linked",
        "Returns compound and effects add. Over two and a half years the plain sum of daily active returns drifts "
        "away from the compounded active return; Cariño's factors rescale each day so nothing is left over.",
    )
    caption(figure, "k_t = [ln(1+R_t) - ln(1+B_t)] / (R_t - B_t); K is the same over the whole period.")
    return figure


# ---------------------------------------------------------------------------- 7. which return
def plot_return_methods(
    rows: Sequence[tuple[str, float, float, float]],
    nav: Sequence[tuple[date, float]],
    flows: Sequence[tuple[date, float]],
) -> Figure:
    """``rows``: label, time-weighted, money-weighted (period), Modified Dietz."""
    figure = new_figure(15.5, 7.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.25, 1.0], wspace=0.2, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(rows))
    for offset, index, label, colour in (
        (-0.26, 1, "time-weighted", PORTFOLIO_COLOUR),
        (0.0, 2, "money-weighted (IRR)", PALETTE["teal"]),
        (0.26, 3, "Modified Dietz", PALETTE["sky"]),
    ):
        values = [float(row[index]) for row in rows]
        axis.bar(positions + offset, values, width=0.25, color=colour, label=label)
        for x, value in zip(positions + offset, values, strict=True):
            axis.annotate(
                _pct(value, 1, True),
                (x, value),
                xytext=(0, 3 if value >= 0 else -11),
                textcoords="offset points",
                ha="center",
                fontsize=6.6,
            )
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.set_xticks(positions, labels=[row[0] for row in rows])
    _percent_axis(axis)
    low, high = axis.get_ylim()
    axis.set_ylim(low - (high - low) * 0.06, high + (high - low) * 0.22)
    style_axes(axis, title="Three answers to 'what was the return?'")
    axis.legend(loc="upper left", ncol=3)
    timeline = figure.add_subplot(grid[1])
    timeline.plot([day for day, _ in nav], [value for _, value in nav], color=PORTFOLIO_COLOUR, linewidth=1.4)
    timeline.yaxis.set_major_formatter(lambda value, _: f"{value / 1e6:.1f}m")
    for day, amount in flows:
        level = next((value for when, value in nav if when >= day), nav[-1][1])
        timeline.annotate(
            f"{'deposit' if amount > 0 else 'withdrawal'} {abs(amount) / 1e3:,.0f}k",
            (x_of(day), level),
            xytext=(0, 26 if amount > 0 else -30),
            textcoords="offset points",
            ha="center",
            fontsize=7.8,
            arrowprops={"arrowstyle": "->", "color": PALETTE["accent"]},
            color=PALETTE["ink"],
        )
    style_axes(timeline, title="Net asset value and the client's flows (USD)")
    title_block(
        figure,
        "Time-weighted, money-weighted and Modified Dietz",
        "The time-weighted return judges the manager and ignores when the client added money; the money-weighted "
        "return judges the client's experience and does not. Modified Dietz approximates the second, not the first.",
    )
    caption(figure, "Money-weighted returns are shown over each period (not annualised) so the three are comparable.")
    return figure


# ---------------------------------------------------------------------------- 8. monthly calendar
def plot_monthly_returns(portfolio: ReturnSeries, benchmark: ReturnSeries) -> Figure:
    mine, theirs = calendar_table(portfolio), calendar_table(benchmark)
    years = sorted(mine)
    figure = new_figure(15.8, 6.8)
    grid = figure.add_gridspec(1, 2, wspace=0.1, **_margins(figure, bottom=0.95, left=0.05))
    for column, (table, title, subtract) in enumerate(
        ((mine, "Portfolio, monthly return", False), (mine, "Active: portfolio less benchmark", True))
    ):
        axis = figure.add_subplot(grid[column])
        matrix = np.full((len(years), 13), np.nan)
        for row, year in enumerate(years):
            for month in range(1, 14):
                value = table.get(year, {}).get(month)
                if value is None:
                    continue
                if subtract:
                    other = theirs.get(year, {}).get(month)
                    value = value - other if other is not None else None
                if value is not None:
                    matrix[row, month - 1] = value
        limit = float(np.nanmax(np.abs(matrix))) or 0.01
        axis.imshow(matrix, cmap=_DIVERGING, vmin=-limit, vmax=limit, aspect="auto")
        for (row, month), value in np.ndenumerate(matrix):
            if not math.isnan(value):
                axis.text(
                    month,
                    row,
                    f"{value:.1%}",
                    ha="center",
                    va="center",
                    fontsize=7.2,
                    weight="bold" if month == 12 else "normal",
                )
        axis.set_xticks(range(13), labels=["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D", "Year"])
        axis.set_yticks(range(len(years)), labels=[str(year) for year in years])
        axis.axvline(11.5, color=PALETTE["surface"], linewidth=3)
        axis.grid(visible=False)
        axis.set_title(title)
    title_block(
        figure,
        "Returns by month",
        "Each cell is a month's time-weighted return, linked from daily returns; the year column links the months. "
        "Active returns are simple differences, as monthly factsheets show them.",
    )
    caption(figure, "2024 starts on 2 April and 2026 ends on 18 September.")
    return figure


# ---------------------------------------------------------------------------- 9. rolling
def plot_rolling_risk(portfolio: ReturnSeries, benchmark: ReturnSeries, window: int = 63) -> Figure:
    points = rolling(portfolio, benchmark, window)
    days = [point.day for point in points]
    figure = new_figure(15.5, 9.0)
    grid = figure.add_gridspec(3, 1, hspace=0.35, **_margins(figure, bottom=0.9))
    vol = figure.add_subplot(grid[0])
    vol.plot(days, [p.volatility for p in points], color=PORTFOLIO_COLOUR, label="portfolio")
    vol.plot(days, [p.benchmark_volatility for p in points], color=BENCHMARK_COLOUR, label="benchmark")
    _percent_axis(vol)
    style_axes(vol, title=f"Volatility, annualised, rolling {window} trading days")
    vol.legend(loc="upper right")
    te = figure.add_subplot(grid[1], sharex=vol)
    te.plot(days, [p.tracking_error for p in points], color=PALETTE["violet"], label="tracking error")
    twin = te.twinx()
    twin.plot(
        days, [p.information_ratio for p in points], color=PALETTE["teal"], linewidth=1.0, label="information ratio"
    )
    twin.axhline(0, color=PALETTE["muted"], linewidth=0.6)
    twin.grid(visible=False)
    twin.spines["right"].set_visible(True)
    twin.set_ylabel("information ratio", color=PALETTE["teal"])
    _percent_axis(te, places=1)
    style_axes(te, title="Tracking error (left) and information ratio (right)")
    te.legend(loc="upper left")
    beta = figure.add_subplot(grid[2], sharex=vol)
    beta.plot(days, [p.beta for p in points], color=PALETTE["navy"])
    beta.axhline(1.0, color=PALETTE["muted"], linewidth=0.8)
    style_axes(beta, title="Beta to the benchmark")
    title_block(
        figure,
        "Risk, as it moved",
        "A full-period figure hides regimes: rolling windows show when the portfolio took more or less risk than its "
        "benchmark, and whether the active risk was paid for.",
    )
    caption(
        figure,
        "A quarter (63 trading days) per window; information ratio is the window's annualised active return "
        "over its tracking error.",
    )
    return figure


# ---------------------------------------------------------------------------- 10. risk and return
def plot_risk_return(points: Mapping[str, RiskReturn], highlight: Sequence[str], risk_free: float = 0.04) -> Figure:
    figure = new_figure(14.0, 8.2)
    axis = figure.add_axes((0.08, 0.95 / 8.2, 0.9, 1 - 2.2 / 8.2))
    for name, stats in points.items():
        emphasised = name in highlight
        axis.scatter(
            stats.volatility,
            stats.annual_return,
            s=150 if emphasised else 55,
            color=PORTFOLIO_COLOUR if name == highlight[0] else BENCHMARK_COLOUR if emphasised else PALETTE["sky"],
            edgecolor="white",
            zorder=4,
        )
        axis.annotate(
            name,
            (stats.volatility, stats.annual_return),
            xytext=(7, 4),
            textcoords="offset points",
            fontsize=8.5 if emphasised else 7.6,
            weight="bold" if emphasised else "normal",
        )
    top = max(stats.volatility for stats in points.values()) * 1.1
    for sharpe in (-0.5, 0.0, 0.5):
        axis.plot(
            [0, top],
            [risk_free, risk_free + sharpe * top],
            color=PALETTE["grid"],
            linewidth=1.0,
            linestyle="--",
            zorder=1,
        )
        axis.text(
            top, risk_free + sharpe * top, f"Sharpe {sharpe:+.1f}", fontsize=7.4, color=PALETTE["muted"], va="center"
        )
    axis.axhline(0, color=PALETTE["muted"], linewidth=0.8)
    _percent_axis(axis, "x")
    _percent_axis(axis, "y")
    axis.set_xlim(0, top * 1.08)
    style_axes(axis, xlabel="annualised volatility", ylabel="annualised return", grid="both")
    title_block(
        figure,
        "Return against risk",
        "The portfolio, its benchmark and every holding over the time each was held. Dashed lines join the risk-free "
        f"rate ({risk_free:.0%}) to equal Sharpe ratios.",
    )
    caption(figure, "Holding returns are their own time-weighted returns in US dollars on the days they were held.")
    return figure


# ---------------------------------------------------------------------------- 11. drawdown episodes
def plot_drawdown_episodes(portfolio: ReturnSeries, benchmark: ReturnSeries) -> Figure:
    figure = new_figure(15.5, 7.6)
    grid = figure.add_gridspec(
        2,
        2,
        height_ratios=[1.9, 0.6],
        width_ratios=[1.0, 1.0],
        hspace=0.35,
        wspace=0.12,
        **_margins(figure, bottom=0.9),
    )
    axis = figure.add_subplot(grid[0, :])
    index = portfolio.index(100.0)
    axis.plot([day for day, _ in index], [value for _, value in index], color=PORTFOLIO_COLOUR, linewidth=1.6)
    episodes = [item for item in drawdown_episodes(portfolio, 5) if item.depth <= -0.01]
    shades = [PALETTE["loss"], PALETTE["violet"], PALETTE["sky"], PALETTE["teal"], PALETTE["slate"]]
    for rank, (episode, colour) in enumerate(zip(episodes, shades, strict=False), start=1):
        end = episode.recovery or index[-1][0]
        axis.axvspan(x_of(episode.peak), x_of(end), color=colour, alpha=0.13)
        low = next(value for day, value in index if day == episode.trough)
        axis.annotate(
            f"#{rank} {episode.depth:.1%}",
            (x_of(episode.trough), low),
            xytext=(0, -16),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=colour,
            weight="bold",
        )
    axis.margins(y=0.14)
    if episodes and episodes[0].recovery is None:
        axis.annotate(
            "not yet recovered",
            (x_of(index[-1][0]), index[-1][1]),
            xytext=(-6, 12),
            textcoords="offset points",
            ha="right",
            fontsize=8,
            color=PALETTE["loss"],
        )
    style_axes(axis, title="The portfolio's deepest drawdowns (over 1%), peak to recovery")
    for column, (series, label) in enumerate(((portfolio, "Portfolio"), (benchmark, "Benchmark"))):
        table_axis = figure.add_subplot(grid[1, column])
        table_axis.axis("off")
        rows = [
            [
                f"#{rank}",
                f"{e.depth:.1%}",
                f"{e.peak:%d %b %y}",
                f"{e.trough:%d %b %y}",
                f"{e.recovery:%d %b %y}" if e.recovery else "not yet",
                f"{e.length}",
            ]
            for rank, e in enumerate((item for item in drawdown_episodes(series, 5) if item.depth <= -0.01), start=1)
        ]
        rows = rows or [["", "none", "", "", "", ""]]
        table = table_axis.table(
            cellText=rows,
            colLabels=["", "depth", "peak", "trough", "recovered", "days"],
            loc="center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8.2)
        table.scale(1, 1.35)
        for (row, _), cell in table.get_celld().items():
            cell.set_edgecolor(PALETTE["grid"])
            if row == 0:
                cell.set_text_props(weight="bold", color=PALETTE["navy"])
        table_axis.set_title(f"{label}: deepest drawdowns", loc="left")
    title_block(
        figure,
        "Drawdowns: how deep, how long, and whether they recovered",
        "Depth is the fall from the running peak; length runs from the peak to the day the peak was regained.",
    )
    caption(figure, "Growth of 100, time-weighted.")
    return figure


# ---------------------------------------------------------------------------- 12. currency
def plot_currency_attribution(result: AttributionResult) -> Figure:
    currencies = sorted(result.currency, key=lambda code: result.currency[code])
    weights: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for item in result.days:
        for code, (wp, wb) in item.currency_weights.items():
            weights[code][0] += wp / len(result.days)
            weights[code][1] += wb / len(result.days)
    figure = new_figure(15.5, 7.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 1.4], wspace=0.3, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    rows = np.arange(len(currencies))
    axis.barh(
        rows + 0.19, [weights[code][0] for code in currencies], height=0.36, color=PORTFOLIO_COLOUR, label="portfolio"
    )
    axis.barh(
        rows - 0.19, [weights[code][1] for code in currencies], height=0.36, color=BENCHMARK_COLOUR, label="benchmark"
    )
    for row, code in enumerate(currencies):
        axis.text(
            1.03,
            row,
            _bp(result.currency[code]),
            transform=axis.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=9,
            weight="bold",
            color=PALETTE["gain"] if result.currency[code] >= 0 else PALETTE["loss"],
            clip_on=False,
        )
    axis.text(
        1.03,
        len(currencies) - 0.4,
        "effect",
        transform=axis.get_yaxis_transform(),
        ha="left",
        va="center",
        fontsize=7.6,
        color=PALETTE["muted"],
        clip_on=False,
    )
    axis.set_yticks(rows, labels=currencies)
    _percent_axis(axis, "x")
    style_axes(axis, title="Average currency weight, and the effect", grid="x")
    axis.legend(loc="center right")
    path = figure.add_subplot(grid[1])
    days = [item.day for item in result.days]
    for code, colour in zip(
        sorted(result.currency),
        [PALETTE["sky"], PALETTE["teal"], PALETTE["violet"], PALETTE["slate"], PALETTE["navy"]],
        strict=False,
    ):
        cumulative = np.cumsum([item.currency.get(code, 0.0) for item in result.days])
        path.plot(days, cumulative * 1e4, color=colour, linewidth=1.4, label=code)
    total = np.cumsum([sum(item.currency.values()) for item in result.days])
    path.plot(days, total * 1e4, color=PALETTE["ink"], linewidth=2.0, label="all currencies")
    path.axhline(0, color=PALETTE["muted"], linewidth=0.8)
    style_axes(path, title="Currency effect accumulating (basis points, unlinked)")
    path.legend(loc="lower left", ncol=3)
    title_block(
        figure,
        "Currency: kept apart from stock picking",
        "Per currency, the portfolio's currency contribution less the benchmark's. Holding no yen when the benchmark "
        "holds 4.5% is a currency position too.",
    )
    caption(
        figure,
        "Conversion spreads are part of the dollar line. Linked effects on the bridge; unlinked running sums here.",
    )
    return figure


# ---------------------------------------------------------------------------- 13. contribution
def plot_contributions(contributions: Mapping[str, float], days: Sequence[PortfolioDay], total: float) -> Figure:
    average: dict[str, float] = defaultdict(float)
    for day in days:
        for exposure in day.exposures:
            key = "Cash" if exposure.is_cash else exposure.key
            average[key] += day.weight(exposure) / len(days)
    items = sorted(contributions.items(), key=lambda item: item[1])
    figure = new_figure(15.0, 7.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.5, 0.6], wspace=0.08, **_margins(figure, bottom=0.95, left=0.12))
    axis = figure.add_subplot(grid[0])
    rows = np.arange(len(items))
    axis.barh(
        rows,
        [value for _, value in items],
        color=[PALETTE["gain"] if value >= 0 else PALETTE["loss"] for _, value in items],
        height=0.62,
    )
    for row, (_, value) in enumerate(items):
        axis.text(value, row, f" {value:+.2%} ", va="center", ha="left" if value >= 0 else "right", fontsize=8)
    axis.set_yticks(rows, labels=[name for name, _ in items])
    axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    low, high = min(0.0, items[0][1]), max(0.0, items[-1][1])
    axis.set_xlim(low - (high - low) * 0.12, high + (high - low) * 0.12)
    _percent_axis(axis, "x", places=1)
    style_axes(axis, title=f"Contribution to the {total:+.2%} time-weighted return", grid="x")
    side = figure.add_subplot(grid[1], sharey=axis)
    side.barh(rows, [average.get(name, 0.0) for name, _ in items], color=PALETTE["grid"], height=0.62)
    side.tick_params(labelleft=False)
    _percent_axis(side, "x")
    style_axes(side, title="Average weight", grid="x")
    title_block(
        figure,
        "Who drove the return",
        "Each holding's daily result over the capital at risk, linked with Cariño's factors so the contributions add "
        "up to the portfolio's return exactly.",
    )
    caption(figure, "Contributions include price, currency and income; costs are the portfolio's own line.")
    return figure


# ---------------------------------------------------------------------------- 14. active days
def plot_active_distribution(portfolio: ReturnSeries, benchmark: ReturnSeries) -> Figure:
    p = np.array(portfolio.rates)
    b = np.array(benchmark.rates)
    active = p - b
    rel = relative(portfolio, benchmark)
    figure = new_figure(15.5, 7.0)
    grid = figure.add_gridspec(1, 3, width_ratios=[1.3, 1.0, 0.8], wspace=0.28, **_margins(figure, bottom=0.95))
    hist = figure.add_subplot(grid[0])
    hist.hist(active * 1e4, bins=60, color=PALETTE["teal"], alpha=0.85)
    hist.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    hist.axvline(active.mean() * 1e4, color=PALETTE["accent"], linewidth=1.2)
    style_axes(hist, title="Daily active returns (basis points)", xlabel="portfolio less benchmark, one day")
    annotate(
        hist,
        f"hit rate {rel.hit_rate:.0%}\ntracking error {rel.tracking_error:.1%}",
        (0.03, 0.85),
        xycoords="axes fraction",
        highlight=True,
    )
    scatter = figure.add_subplot(grid[1])
    scatter.scatter(b * 100, p * 100, s=8, color=PORTFOLIO_COLOUR, alpha=0.4)
    line = np.linspace(b.min(), b.max(), 10)
    scatter.plot(
        line * 100, (line * rel.beta) * 100, color=PALETTE["accent"], linewidth=1.3, label=f"beta {rel.beta:.2f}"
    )
    scatter.plot(line * 100, line * 100, color=PALETTE["muted"], linewidth=0.8, linestyle=":", label="beta 1")
    style_axes(
        scatter,
        title="Daily returns, portfolio against benchmark (%)",
        xlabel="benchmark",
        ylabel="portfolio",
        grid="both",
    )
    scatter.legend(loc="upper left")
    capture = figure.add_subplot(grid[2])
    capture.bar([0, 1], [rel.up_capture, rel.down_capture], color=[PALETTE["gain"], PALETTE["loss"]], width=0.55)
    for x, value in ((0, rel.up_capture), (1, rel.down_capture)):
        capture.annotate(
            f"{value:.0%}", (x, value), xytext=(0, 4), textcoords="offset points", ha="center", weight="bold"
        )
    capture.axhline(1.0, color=PALETTE["muted"], linewidth=0.8)
    capture.set_xticks([0, 1], labels=["up capture", "down capture"])
    _percent_axis(capture)
    style_axes(capture, title="Capture of the benchmark's days")
    title_block(
        figure,
        "Day by day against the benchmark",
        "How often the portfolio beat its benchmark, by how much, and how much of the benchmark's rising and falling "
        "days it took part in.",
    )
    caption(figure, "Capture: the portfolio's linked return on the benchmark's up (down) days over the benchmark's.")
    return figure


# ---------------------------------------------------------------------------- 15. factsheet
def plot_factsheet(
    name: str,
    portfolio: ReturnSeries,
    benchmark: ReturnSeries,
    periods: Sequence[tuple[PeriodReturn, PeriodReturn]],
    stats_rows: Sequence[tuple[str, str, str]],
    by_sector: AttributionResult,
    contributions: Mapping[str, float],
    as_of: date,
) -> Figure:
    figure = new_figure(11.7, 16.5)
    grid = figure.add_gridspec(
        4, 2, height_ratios=[1.1, 0.9, 1.0, 1.0], hspace=0.5, wspace=0.28, **_margins(figure, top=1.5, bottom=0.8)
    )
    growth = figure.add_subplot(grid[0, :])
    for series, colour in ((portfolio, PORTFOLIO_COLOUR), (benchmark, BENCHMARK_COLOUR)):
        points = series.index(100.0)
        growth.plot(
            [d for d, _ in points],
            [v for _, v in points],
            color=colour,
            linewidth=2.0 if colour == PORTFOLIO_COLOUR else 1.4,
            label=series.name,
        )
    style_axes(growth, title="Growth of 100")
    growth.legend(loc="lower left")
    table_axis = figure.add_subplot(grid[1, 0])
    table_axis.axis("off")
    rows = [
        [
            mine.label,
            _pct(mine.annualised if mine.is_annualised else mine.total, 2, True),
            _pct(theirs.annualised if theirs.is_annualised else theirs.total, 2, True),
            _pct(
                (mine.annualised if mine.is_annualised else mine.total)
                - (theirs.annualised if theirs.is_annualised else theirs.total),
                2,
                True,
            ),
        ]
        for mine, theirs in periods
    ]
    table = table_axis.table(
        cellText=rows, colLabels=["period", "portfolio", "benchmark", "active"], loc="center", cellLoc="center"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.6)
    table.scale(1, 1.5)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor(PALETTE["grid"])
        if row == 0:
            cell.set_text_props(weight="bold", color=PALETTE["navy"])
    table_axis.set_title("Returns (over a year: annualised)", loc="left")
    stats_axis = figure.add_subplot(grid[1, 1])
    stats_axis.axis("off")
    stats = stats_axis.table(
        cellText=[list(row) for row in stats_rows[:10]],
        colLabels=["measure", "portfolio", "benchmark"],
        loc="center",
        cellLoc="center",
    )
    stats.auto_set_font_size(False)
    stats.set_fontsize(8.2)
    stats.scale(1, 1.25)
    for (row, _), cell in stats.get_celld().items():
        cell.set_edgecolor(PALETTE["grid"])
        if row == 0:
            cell.set_text_props(weight="bold", color=PALETTE["navy"])
    stats_axis.set_title("Risk, since inception", loc="left")
    bridge = figure.add_subplot(grid[2, 0])
    labels = ["allocation", "selection", "interaction", "currency", "costs"]
    values = [by_sector.effect(label) for label in labels]
    bridge.barh(range(len(labels)), values, color=[EFFECT_COLOURS[label] for label in labels])
    for row, value in enumerate(values):
        bridge.text(
            value, row, f" {value * 1e4:+.0f} bp ", va="center", ha="left" if value >= 0 else "right", fontsize=8
        )
    bridge.set_yticks(range(len(labels)), labels=labels)
    bridge.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    span = max(values) - min(0.0, min(values))
    bridge.set_xlim(min(0.0, min(values)) - span * 0.25, max(0.0, max(values)) + span * 0.22)
    bridge.xaxis.set_major_formatter(lambda value, _: f"{value * 1e4:+.0f}")
    style_axes(bridge, title=f"Attribution of {_pct(by_sector.active, 2, True)} active (bp)", grid="x")
    top = figure.add_subplot(grid[2, 1])
    ranked = sorted(contributions.items(), key=lambda item: item[1])
    chosen = ranked[:4] + ranked[-4:]
    top.barh(
        range(len(chosen)),
        [value for _, value in chosen],
        color=[PALETTE["gain"] if v >= 0 else PALETTE["loss"] for _, v in chosen],
    )
    top.set_yticks(range(len(chosen)), labels=[k for k, _ in chosen], fontsize=8)
    top.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    _percent_axis(top, "x", places=1)
    style_axes(top, title="Largest contributions", grid="x")
    sectors = figure.add_subplot(grid[3, :])
    segments = sorted(by_sector.segments, key=lambda item: -item.average_wp)
    positions = np.arange(len(segments))
    sectors.bar(
        positions - 0.19, [item.average_wp for item in segments], width=0.36, color=PORTFOLIO_COLOUR, label="portfolio"
    )
    sectors.bar(
        positions + 0.19, [item.average_wb for item in segments], width=0.36, color=BENCHMARK_COLOUR, label="benchmark"
    )
    sectors.set_xticks(positions, labels=[item.segment.replace(" ", "\n", 1) for item in segments], fontsize=7.4)
    _percent_axis(sectors)
    style_axes(sectors, title="Average weights by sector")
    sectors.legend(loc="upper right")
    title_block(
        figure,
        f"{name} - performance report",
        f"Since inception on {portfolio.start:%d %B %Y} to {as_of:%d %B %Y}, in US dollars, net of costs.",
    )
    caption(
        figure,
        "Time-weighted returns from the book of record. "
        "Benchmark: 80% Meridian World Equity (synthetic), 15% US Treasury, 5% cash.",
    )
    return figure


def legend_patches() -> list[Patch]:
    return [Patch(color=colour, label=name) for name, colour in EFFECT_COLOURS.items()]
