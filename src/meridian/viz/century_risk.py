"""Charts for the Day 5 revisit: risk against independent references and a century of daily returns.

The functions take plain inputs, prepared in :mod:`meridian.century_risk_gallery`.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import matplotlib.dates as mdates
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap, TwoSlopeNorm
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .style import PALETTE, caption, new_figure, style_axes, title_block, x_of

ZONE_COLOURS = {"green": PALETTE["gain"], "yellow": "#E8B04A", "red": PALETTE["loss"]}
METHOD_COLOURS = [PALETTE["slate"], PALETTE["violet"], PALETTE["teal"], PALETTE["navy"]]


# ---------------------------------------------------------------------------- references
@dataclass(frozen=True)
class ReferenceGap:
    reference: str
    subject: str
    gap: float  # absolute difference
    convention: bool = False


def plot_references(
    counts: Sequence[int],
    cumulative: Sequence[float],
    published: Sequence[float],
    zones: Sequence[str],
    gaps: Sequence[ReferenceGap],
) -> Figure:
    fig = new_figure(14.0, 7.6)
    title_block(
        fig,
        "Day 5 against its references: the Basel table to the printed digit, arch to the last bit",
        "Left: the probability that a correct 99% VaR model is exceeded this many times in 250 days, as Meridian "
        "computes it and as the Basel Committee printed it in 1996. Right: every other check, as the size of the gap.",
    )
    ax = fig.add_axes((0.06, 0.13, 0.42, 0.68))
    x = np.arange(len(counts))
    ax.bar(x, np.array(cumulative) * 100, color=[ZONE_COLOURS[zone] for zone in zones], width=0.7, alpha=0.85)
    ax.plot(x, published, "D", color=PALETTE["ink"], ms=6, label="Basel Committee (1996), Table 2")
    for xi, value in zip(x, published, strict=True):
        ax.text(
            xi, value + 2.5, f"{value:.2f}", ha="center", fontsize=7.3, color=PALETTE["ink"], rotation=90, va="bottom"
        )
    ax.axhline(95, color=PALETTE["muted"], lw=0.8, ls="--")
    ax.axhline(99.99, color=PALETTE["muted"], lw=0.8, ls=":")
    ax.text(-0.4, 96, "95%: yellow from here", fontsize=7.5, color=PALETTE["muted"])
    ax.set_xticks(x, [str(count) for count in counts])
    ax.set_ylim(0, 128)
    style_axes(ax, xlabel="exceptions in 250 days", ylabel="cumulative probability (%)", grid="y")
    handles: list[Patch | Line2D] = [Patch(color=colour, label=zone) for zone, colour in ZONE_COLOURS.items()]
    handles.append(Line2D([], [], marker="D", ls="", color=PALETTE["ink"], label="printed by the Committee"))
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=8.5, ncol=2)
    right = fig.add_axes((0.62, 0.13, 0.35, 0.68))
    y = np.arange(len(gaps))[::-1]
    for position, item in zip(y, gaps, strict=True):
        shown = max(item.gap, 1e-20)
        colour = PALETTE["accent"] if item.convention else PALETTE["navy"]
        right.plot(shown, position, "o", color=colour, ms=7)
        right.text(
            1e-21, position + 0.28, f"{item.reference}: {item.subject}", fontsize=7.8, color=PALETTE["ink"], va="bottom"
        )
        label = "0 (identical)" if item.gap == 0 else f"{item.gap:.1e}"
        right.text(shown * 3, position, label, fontsize=7.5, va="center", color=colour)
    right.set_xscale("log")
    right.set_xlim(1e-21, 1e-1)
    right.set_ylim(-0.7, len(gaps) - 0.1)
    right.set_yticks([])
    right.axvspan(1e-21, 1e-12, color=PALETTE["band"], zorder=0)
    style_axes(right, xlabel="absolute gap between Meridian and the reference (log scale)", grid="x")
    right.spines["left"].set_visible(False)
    right.text(1e-20, -0.6, "shaded: agreement to 1e-12", fontsize=7.5, color=PALETTE["muted"])
    caption(
        fig,
        "References: Basel Committee on Banking Supervision (1996), supervisory framework for backtesting; "
        "arch (Sheppard); pandas; scikit-learn; PyPortfolioOpt. Orange: a documented convention (PyPortfolioOpt's "
        "T - 1 sample), which agrees to 0 given the sample Ledoit and Wolf's own code uses.",
    )
    return fig


# ---------------------------------------------------------------------------- the century of zones
def plot_zone_heatmap(
    methods: Sequence[str],
    years: Sequence[int],
    zones: Sequence[Sequence[str]],
    totals: Sequence[tuple[float, int, int, int]],
) -> Figure:
    fig = new_figure(14.0, 6.4)
    title_block(
        fig,
        "Ninety-seven years of 99% VaR on the US market, scored as a regulator would",
        "Every year's exceptions in Basel's traffic-light zones, for four forecasters run every day since 1929 on "
        "returns known the evening before. Right: the exception rate over the whole span, and the years in each zone.",
    )
    ax = fig.add_axes((0.17, 0.2, 0.62, 0.6))
    codes = {"green": 0, "yellow": 1, "red": 2}
    grid = np.array([[codes[zone] for zone in row] for row in zones])
    cmap = ListedColormap([ZONE_COLOURS["green"], ZONE_COLOURS["yellow"], ZONE_COLOURS["red"]])
    ax.imshow(grid, aspect="auto", cmap=cmap, norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5], 3), interpolation="nearest")
    ax.set_yticks(range(len(methods)), methods, fontsize=9)
    ticks = [index for index, year in enumerate(years) if year % 10 == 0]
    ax.set_xticks(ticks, [str(years[index]) for index in ticks], fontsize=8.5)
    ax.grid(visible=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for year, label in ((1987, "1987"), (2008, "2008"), (2020, "2020")):
        if year in years:
            ax.annotate(
                label,
                xy=(years.index(year), -0.5),
                xytext=(years.index(year), -0.95),
                ha="center",
                fontsize=7.5,
                color=PALETTE["muted"],
                annotation_clip=False,
            )
    side = fig.add_axes((0.81, 0.2, 0.17, 0.6))
    side.set_xlim(0, 1)
    side.set_ylim(len(methods) - 0.5, -0.5)
    side.axis("off")
    side.text(0.0, -0.75, "rate   green  yellow  red", fontsize=8, color=PALETTE["muted"], family="monospace")
    for row, (rate, green, yellow, red) in enumerate(totals):
        side.text(
            0.0,
            row,
            f"{rate:.2%}  {green:>4}  {yellow:>5}  {red:>4}",
            fontsize=9,
            va="center",
            family="monospace",
            color=PALETTE["loss"] if red else PALETTE["ink"],
        )
    handles = [Patch(color=colour, label=f"{zone} year") for zone, colour in ZONE_COLOURS.items()]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.17, 0.04), ncol=3, frameon=False, fontsize=9)
    caption(
        fig,
        "Source: Kenneth R. French Data Library, daily market return (Mkt-RF + RF), 12 November 1929 to "
        "31 August 2026. Zones by the Basel rule for each year's own number of trading days.",
    )
    return fig


# ---------------------------------------------------------------------------- crises
@dataclass(frozen=True)
class CrisisPanel:
    title: str
    days: tuple[date, ...]
    returns: np.ndarray
    var: Mapping[str, np.ndarray]


def plot_crises(panels: Sequence[CrisisPanel]) -> Figure:
    fig = new_figure(14.0, 9.6)
    title_block(
        fig,
        "Four crises, four forecasters: the loss each expected to see on one day in a hundred",
        "Daily returns of the US market (bars) against each method's 99% VaR forecast (lines, as losses below zero). "
        "A bar below a line is an exception. Historical simulation waits for the crisis to enter its window.",
    )
    for index, panel in enumerate(panels):
        row, column = divmod(index, 2)
        ax = fig.add_axes((0.06 + column * 0.48, 0.53 - row * 0.42, 0.42, 0.31))
        colours = np.where(panel.returns < 0, PALETTE["loss"], PALETTE["grid"])
        ax.bar(panel.days, panel.returns * 100, color=colours, width=1.0, lw=0)
        for (name, values), colour in zip(panel.var.items(), METHOD_COLOURS, strict=True):
            ax.plot(panel.days, -values * 100, color=colour, lw=1.3, label=name)
        worst = int(np.argmin(panel.returns))
        ax.annotate(
            f"{panel.days[worst]:%d %b %Y}: {panel.returns[worst]:.1%}",
            xy=(x_of(panel.days[worst]), panel.returns[worst] * 100),
            xytext=(0.55, 0.08),
            textcoords="axes fraction",
            fontsize=8,
            color=PALETTE["loss"],
            arrowprops={"arrowstyle": "->", "color": PALETTE["loss"], "lw": 0.8},
        )
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        style_axes(ax, title=panel.title, ylabel="daily return (%)", grid="y")
        if index == 0:
            ax.legend(frameon=False, fontsize=7.8, loc="lower left")
    caption(
        fig,
        "Source: Kenneth R. French Data Library, daily market return. VaR forecasts from meridian.risk.backtest, "
        "each using returns up to the evening before.",
    )
    return fig


# ---------------------------------------------------------------------------- surprises
@dataclass(frozen=True)
class Surprise:
    day: date
    loss: float
    multiple: float  # the loss over that morning's normal VaR
    event: str


def plot_surprises(surprises: Sequence[Surprise], method: str) -> Figure:
    fig = new_figure(14.0, 7.0)
    title_block(
        fig,
        "The worst surprises in a century: losses measured in units of the VaR forecast that morning",
        f"The day's loss divided by the 99% VaR forecast ({method}) made the evening before. 1987 was the "
        "worst day, but not the worst surprise: markets were already volatile that October.",
    )
    ax = fig.add_axes((0.30, 0.1, 0.66, 0.76))
    y = np.arange(len(surprises))[::-1]
    ax.barh(y, [item.multiple for item in surprises], color=PALETTE["loss"], height=0.62, alpha=0.85)
    for position, item in zip(y, surprises, strict=True):
        ax.text(item.multiple + 0.08, position, f"{item.multiple:.1f}x  ({item.loss:.1%})", va="center", fontsize=8.5)
        ax.text(
            -0.15,
            position,
            f"{item.day:%d %b %Y}" + (f"  {item.event}" if item.event else ""),
            ha="right",
            va="center",
            fontsize=8.8,
            color=PALETTE["ink"],
        )
    ax.axvline(1, color=PALETTE["muted"], lw=0.8, ls="--")
    ax.text(1.05, len(surprises) - 0.4, "the VaR itself", fontsize=7.5, color=PALETTE["muted"])
    ax.set_yticks([])
    ax.set_xlim(0, max(item.multiple for item in surprises) * 1.25)
    style_axes(ax, xlabel="loss over the morning's VaR forecast", grid="x")
    ax.spines["left"].set_visible(False)
    caption(
        fig,
        "Source: Kenneth R. French Data Library, daily market return. Events named only where the cause is "
        "documented; the forecast is RiskMetrics volatility with the normal quantile.",
    )
    return fig


# ---------------------------------------------------------------------------- bias by decade
def plot_bias_heatmap(
    series: Sequence[str], decades: Sequence[int], bias: np.ndarray, band: float, names: Mapping[str, str]
) -> Figure:
    fig = new_figure(14.0, 7.4)
    title_block(
        fig,
        "Is the risk forecast the right size? The RiskMetrics forecast, decade by decade, on real data",
        "The bias statistic - the standard deviation of each day's return over the forecast made the evening before - "
        f"for the market and twelve industries. One is right; above {1 + band:.3f} the forecast was too low. "
        "It was too low in every cell.",
    )
    ax = fig.add_axes((0.2, 0.12, 0.66, 0.72))
    norm = TwoSlopeNorm(vmin=0.9, vcenter=1.0, vmax=1.15)
    image = ax.imshow(bias, aspect="auto", cmap="RdBu_r", norm=norm)
    ax.set_yticks(range(len(series)), [names.get(name, name) for name in series], fontsize=9)
    ax.set_xticks(range(len(decades)), [f"{decade}s" for decade in decades], fontsize=9)
    ax.grid(visible=False)
    for (row, column), value in np.ndenumerate(bias):
        if np.isfinite(value):
            ax.text(
                column,
                row,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=7.8,
                color="white" if value > 1.1 else PALETTE["ink"],
            )
    bar = fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02)
    bar.set_label("bias statistic", fontsize=9)
    caption(
        fig,
        "Source: Kenneth R. French Data Library, daily returns. Forecast: RiskMetrics EWMA, lambda 0.94. "
        "A noisy forecast raises the statistic even when it is unbiased in variance: the cells measure both.",
    )
    return fig


# ---------------------------------------------------------------------------- GARCH and EWMA
def plot_forecast_losses(
    losses: Mapping[str, Mapping[int, float]],
    fit_days: Sequence[date],
    persistence: Sequence[float],
    dof: Sequence[float],
) -> Figure:
    fig = new_figure(14.0, 7.6)
    title_block(
        fig,
        "GARCH against EWMA on a century of returns: a better forecast, by a little",
        "Left: the QLIKE loss of three daily volatility forecasts of the US market, by decade (lower is better). "
        "Right: the GARCH(1,1)-t parameters refitted every year: persistence near one, tails near seven degrees "
        "of freedom.",
    )
    ax = fig.add_axes((0.06, 0.13, 0.48, 0.68))
    names = list(losses)
    decades = [decade for decade in losses[names[0]] if decade]
    x = np.arange(len(decades))
    width = 0.27
    for index, (name, colour) in enumerate(
        zip(names, (PALETTE["slate"], PALETTE["navy"], PALETTE["grid"]), strict=True)
    ):
        ax.bar(
            x + (index - 1) * width,
            [losses[name][d] for d in decades],
            width=width,
            color=colour,
            label=f"{name} ({losses[name][0]:.3f} overall)",
            edgecolor=PALETTE["slate"] if colour == PALETTE["grid"] else "none",
        )
    low = min(min(losses[name][d] for d in decades) for name in names)
    ax.set_ylim(low * 0.9, None)
    ax.set_xticks(x, [f"{d}s" for d in decades], fontsize=8, rotation=45)
    style_axes(ax, ylabel="QLIKE (lower is better)", grid="y")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    top = fig.add_axes((0.62, 0.50, 0.35, 0.31))
    top.plot(fit_days, persistence, color=PALETTE["navy"], lw=1.4)
    top.axhline(1.0, color=PALETTE["loss"], lw=0.8, ls="--")
    style_axes(top, title="persistence (alpha + beta)", grid="y")
    bottom = fig.add_axes((0.62, 0.13, 0.35, 0.26), sharex=top)
    bottom.plot(fit_days, dof, color=PALETTE["teal"], lw=1.4)
    style_axes(bottom, title="Student-t degrees of freedom", grid="y")
    bottom.xaxis.set_major_locator(mdates.YearLocator(20))
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    caption(
        fig,
        "QLIKE (Patton, 2011) against squared daily returns. GARCH fitted with arch on the trailing four "
        "years, refitted yearly; EWMA lambda 0.94; the rolling forecast is the root mean square of a year.",
    )
    return fig


# ---------------------------------------------------------------------------- minimum variance
def plot_minimum_variance(
    summary: Mapping[str, tuple[float, float, float]], days: Sequence[date], delivered: Mapping[str, Sequence[float]]
) -> Figure:
    fig = new_figure(14.0, 7.2)
    title_block(
        fig,
        "Twelve industries, four covariance estimators: with few assets, shrinkage hardly matters",
        "A minimum-variance portfolio of the twelve industries built every month since 1927 from a year of daily "
        "returns: the risk each estimator promised against what the portfolio delivered the next month.",
    )
    ax = fig.add_axes((0.06, 0.14, 0.38, 0.66))
    names = list(summary)
    x = np.arange(len(names))
    promised = [summary[name][0] * 100 for name in names]
    actual = [summary[name][1] * 100 for name in names]
    ax.bar(x - 0.18, promised, width=0.36, color=PALETTE["grid"], edgecolor=PALETTE["slate"], label="promised")
    ax.bar(x + 0.18, actual, width=0.36, color=PALETTE["navy"], label="delivered")
    for xi, name in enumerate(names):
        ax.text(
            xi,
            max(promised[xi], actual[xi]) + 0.2,
            f"{summary[name][2]:.3f}",
            ha="center",
            fontsize=8.5,
            color=PALETTE["ink"],
        )
    ax.set_xticks(x, [textwrap.fill(name, 14) for name in names], fontsize=8)
    ax.set_ylim(0, max(max(promised), max(actual)) * 1.2)
    style_axes(ax, ylabel="mean annualised volatility (%)", grid="y")
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    ax.text(
        0.0,
        1.02,
        "above each pair: delivered over promised",
        transform=ax.transAxes,
        fontsize=8,
        color=PALETTE["muted"],
    )
    right = fig.add_axes((0.52, 0.14, 0.45, 0.66))
    for (name, values), colour in zip(delivered.items(), METHOD_COLOURS, strict=True):
        right.plot(days, np.array(values) * 100, color=colour, lw=0.9, alpha=0.85, label=name)
    right.set_yscale("log")
    right.yaxis.set_major_formatter(lambda value, _: f"{value:g}")
    right.yaxis.set_minor_formatter(lambda value, _: "")
    style_axes(
        right, title="Delivered volatility of each month's portfolio", ylabel="annualised (%), log scale", grid="y"
    )
    right.legend(frameon=False, fontsize=8, loc="upper right")
    caption(
        fig,
        "Source: Kenneth R. French Data Library, 12 industries' daily value-weighted returns. With N = 12 and "
        "T = 252, q = N / T is 0.05: the sample covariance is well conditioned, unlike Day 5's 500 stocks.",
    )
    return fig


# ---------------------------------------------------------------------------- the review
@dataclass(frozen=True)
class ReviewPanel:
    title: str
    labels: tuple[str, ...]
    before: tuple[float, ...]
    after: tuple[float, ...]
    unit: str
    note: str


def plot_review(panels: Sequence[ReviewPanel]) -> Figure:
    fig = new_figure(14.0, 9.6)
    title_block(
        fig,
        "A second reading of Day 5: three of the six faults, before and after",
        "Each panel sets the figure Day 5 produced (grey) beside the corrected one (navy).",
    )
    for index, panel in enumerate(panels):
        row, column = divmod(index, 2)
        ax = fig.add_axes((0.06 + column * 0.49, 0.56 - row * 0.44, 0.40, 0.24))
        x = np.arange(len(panel.labels))
        for xi, (old, new) in enumerate(zip(panel.before, panel.after, strict=True)):
            ax.plot([xi, xi], [old, new], color=PALETTE["grid"], lw=3, zorder=1)
            ax.plot(xi, old, "o", color=PALETTE["muted"], ms=9, zorder=2, label="Day 5" if xi == 0 else None)
            ax.plot(xi, new, "o", color=PALETTE["navy"], ms=9, zorder=3, label="revisited" if xi == 0 else None)
            ax.text(xi - 0.08, old, f"{old:{panel.unit}}", va="center", ha="right", fontsize=8, color=PALETTE["muted"])
            ax.text(
                xi + 0.08, new, f"{new:{panel.unit}}", va="center", fontsize=8, color=PALETTE["ink"], fontweight="bold"
            )
        values = [*panel.before, *panel.after]
        low, high = min(values), max(values)
        pad = (high - low) * 0.25 or abs(high) * 0.05 or 0.05
        ax.set_ylim(low - pad, high + pad)
        ax.set_xlim(-0.5, len(panel.labels) - 0.3)
        ax.set_xticks(x, panel.labels, fontsize=8.5)
        style_axes(ax, title=panel.title, grid="y")
        ax.text(
            0.0,
            -0.2,
            textwrap.fill(panel.note, 92),
            transform=ax.transAxes,
            fontsize=8,
            color=PALETTE["muted"],
            va="top",
        )
        if index == 0:
            ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    caption(
        fig,
        "The other three - a pseudo-inverse promised but not used, half-lives ignored by the forecaster, and "
        "Cornish-Fisher answering outside its domain - raised errors, used defaults or returned a non-quantile.",
    )
    return fig
