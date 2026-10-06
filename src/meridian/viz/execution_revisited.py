"""Charts for the Day 8 revisit: execution against the paper, and liquidation on a century of real prices.

The functions take plain inputs, prepared in :mod:`meridian.execution_revisited_gallery`.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from matplotlib.figure import Figure
from scipy import stats

from .style import PALETTE, caption, new_figure, style_axes, title_block

SCHEDULE_COLOURS = {"even": PALETTE["slate"], "the paper's": PALETTE["navy"], "urgent": PALETTE["teal"]}
SOURCE = "Source: Kenneth R. French Data Library (CRSP), daily returns of the US market and 12 industries, 1926-2026."


# ---------------------------------------------------------------------------- the paper
def plot_paper_example(
    trajectories: Mapping[str, Sequence[float]],
    direct: Mapping[str, Sequence[float]],
    frontier: Sequence[tuple[float, float]],
    points: Mapping[str, tuple[float, float]],
    kappa: float,
) -> Figure:
    fig = new_figure(14.0, 6.6)
    title_block(
        fig,
        "Almgren and Chriss's own example, reproduced",
        f"\\$50m of a \\$50 stock sold over five days (their Table 1). The paper: kappa ~ 0.6 a day, kappa T ~ 3. "
        f"Here: kappa = {kappa:.3f}, kappa T = {kappa * 5:.2f}. Rings: a conic solver's minimum, found without the "
        "closed form.",
    )
    left = fig.add_axes((0.06, 0.15, 0.40, 0.62))
    days = np.arange(6)
    for name, holdings in trajectories.items():
        colour = SCHEDULE_COLOURS.get(name, PALETTE["navy"])
        left.plot(days, np.array(holdings) / 1e6, color=colour, lw=2, marker="o", ms=5, label=name)
        left.plot(
            days,
            np.array(direct[name]) / 1e6,
            ls="none",
            marker="o",
            ms=12,
            mfc="none",
            mec=PALETTE["accent"],
            mew=1.2,
        )
    left.set_xticks(days)
    left.yaxis.set_major_formatter(lambda value, _: f"{value:.1f}m")
    style_axes(left, title="Shares still held", xlabel="end of day", grid="y")
    left.legend(frameon=False, fontsize=9)

    right = fig.add_axes((0.56, 0.15, 0.40, 0.62))
    xs = np.array([sd for _, sd in frontier]) / 1e6
    ys = np.array([e for e, _ in frontier]) / 1e6
    right.plot(xs, ys, color=PALETTE["grid"], lw=2.5, zorder=1)
    for name, (expected, deviation) in points.items():
        colour = SCHEDULE_COLOURS.get(name, PALETTE["navy"])
        right.plot(deviation / 1e6, expected / 1e6, "o", color=colour, ms=9, zorder=3)
        right.text(
            deviation / 1e6 + 0.03,
            expected / 1e6 + 0.04,
            f"{name}\nE \\${expected / 1e6:.2f}m, sd \\${deviation / 1e6:.2f}m",
            fontsize=8.5,
            color=colour,
        )
    right.xaxis.set_major_formatter(lambda value, _: f"\\${value:.1f}m")
    right.yaxis.set_major_formatter(lambda value, _: f"\\${value:.1f}m")
    style_axes(
        right, title="The efficient frontier", xlabel="standard deviation of cost", ylabel="expected cost", grid="both"
    )
    caption(
        fig,
        "Almgren, R. and Chriss, N. (2000), 'Optimal execution of portfolio transactions', Journal of Risk, Table 1: "
        "sigma = 0.95, eta = 2.5e-6, gamma = 2.5e-7, epsilon = 0.0625; the paper's lambda = 1e-6.",
    )
    return fig


# ---------------------------------------------------------------------------- the century
@dataclass(frozen=True)
class DecadeCoverage:
    decade: int
    raw: float
    corrected: float
    autocorrelation: float
    weeks: int


def plot_century_bound(decades: Sequence[DecadeCoverage], pooled: Mapping[str, tuple[float, float]]) -> Figure:
    fig = new_figure(14.0, 7.4)
    title_block(
        fig,
        "How often a liquidation cost more than Almgren-Chriss's 95% bound, every week since 1927",
        "The paper's example sold over each five-day week of the US market, the volatility forecast the evening "
        "before. A random walk breaks the bound one week in twenty; the market broke it more often when its daily "
        "returns moved together.",
    )
    x = np.arange(len(decades))
    top = fig.add_axes((0.06, 0.40, 0.62, 0.42))
    top.bar(x - 0.19, [d.raw for d in decades], width=0.36, color=PALETTE["loss"], label="random-walk variance")
    top.bar(
        x + 0.19,
        [d.corrected for d in decades],
        width=0.36,
        color=PALETTE["navy"],
        label="restated for autocorrelation",
    )
    n = int(np.median([d.weeks for d in decades]))
    band = 1.96 * np.sqrt(0.05 * 0.95 / n)
    top.axhspan(0.05 - band, 0.05 + band, color=PALETTE["band"], zorder=0)
    top.axhline(0.05, color=PALETTE["accent"], lw=1.2)
    top.text(len(decades) - 0.5, 0.052, "5% promised", ha="right", fontsize=8.5, color=PALETTE["accent"])
    top.set_xticks(x, [""] * len(x))
    top.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    style_axes(top, ylabel="weeks over the bound (market, sellers)", grid="y")
    top.legend(frameon=False, fontsize=8.5, loc="upper left")

    bottom = fig.add_axes((0.06, 0.14, 0.62, 0.20), sharex=top)
    rho = [d.autocorrelation for d in decades]
    bottom.bar(x, rho, width=0.6, color=[PALETTE["violet"] if r > 0 else PALETTE["sky"] for r in rho])
    bottom.axhline(0, color=PALETTE["muted"], lw=0.8)
    bottom.set_xticks(x, [f"{d.decade}s" for d in decades], fontsize=9)
    style_axes(bottom, ylabel="lag-one\nautocorrelation", grid="y")

    side = fig.add_axes((0.75, 0.14, 0.22, 0.68))
    side.axis("off")
    side.text(0.0, 1.0, "All 13 series, 67,769 weeks", fontsize=11, fontweight="bold", color=PALETTE["ink"], va="top")
    y = 0.88
    for label, (raw, corrected) in pooled.items():
        side.text(0.0, y, label, fontsize=9.5, color=PALETTE["muted"], va="top")
        side.text(0.0, y - 0.06, f"{raw:.1%}", fontsize=16, color=PALETTE["loss"], fontweight="bold", va="top")
        side.text(0.45, y - 0.06, f"{corrected:.1%}", fontsize=16, color=PALETTE["navy"], fontweight="bold", va="top")
        y -= 0.20
    side.text(
        0.0,
        y,
        textwrap.fill(
            "Left: random-walk variance. Right: restated with the autocorrelation of the year before. What is left "
            "over 5% is fat tails and the forecast's own error.",
            40,
        ),
        fontsize=8.5,
        color=PALETTE["muted"],
        va="top",
    )
    caption(fig, "Band: where 5% would fall by chance in a decade of weeks (95%). " + SOURCE)
    return fig


def plot_cost_tails(z: np.ndarray, control: np.ndarray, coverage: Mapping[str, float]) -> Figure:
    fig = new_figure(14.0, 6.6)
    title_block(
        fig,
        "The cost of a liquidation is not normal: wider, and fatter in the tails",
        "(C - E) / sqrt(V) for every week and series since 1927, against the standard normal the model assumes, "
        "and against a simulated random walk whose volatility is forecast the same way.",
    )
    left = fig.add_axes((0.06, 0.15, 0.40, 0.62))
    bins = np.linspace(-6, 6, 121)
    left.hist(z, bins=bins, density=True, color=PALETTE["navy"], alpha=0.75, label="the century")
    left.hist(control, bins=bins, density=True, histtype="step", color=PALETTE["teal"], lw=1.4, label="random walk")
    grid = np.linspace(-6, 6, 400)
    left.plot(grid, stats.norm.pdf(grid), color=PALETTE["accent"], lw=1.6, label="normal (the model)")
    left.set_yscale("log")
    left.set_ylim(1e-5, 1)
    left.axvline(1.645, color=PALETTE["muted"], ls=":", lw=1)
    style_axes(left, title="Density, log scale", xlabel="standardised cost (seller)", grid="y")
    left.legend(frameon=False, fontsize=8.5, loc="upper left")

    right = fig.add_axes((0.56, 0.15, 0.40, 0.62))
    probabilities = np.linspace(0.001, 0.999, 999)
    expected = stats.norm.ppf(probabilities)
    right.plot(expected, np.quantile(z, probabilities), color=PALETTE["navy"], lw=2, label="the century")
    right.plot(expected, np.quantile(control, probabilities), color=PALETTE["teal"], lw=1.4, label="random walk")
    right.plot([-3.5, 3.5], [-3.5, 3.5], color=PALETTE["grid"], lw=1.2)
    y = 0.95
    for label, value in coverage.items():
        right.text(0.03, y, f"{label}: {value:.1%}", transform=right.transAxes, fontsize=9, color=PALETTE["ink"])
        y -= 0.07
    style_axes(right, title="Quantiles against the normal", xlabel="normal quantile", ylabel="observed", grid="both")
    right.legend(frameon=False, fontsize=8.5, loc="lower right")
    caption(fig, "Dotted: the paper's 95% bound, 1.645 standard deviations. " + SOURCE)
    return fig


# ---------------------------------------------------------------------------- POV and allocation
def plot_pov(minutes: np.ndarray, old: np.ndarray, new: np.ndarray, target: float) -> Figure:
    fig = new_figure(14.0, 5.8)
    title_block(
        fig,
        f"A {target:.0%} POV order, as Day 8 traded it and as it is traded now",
        "Participation is the order's share of all the volume, its own included - the definition the pre-trade "
        "model and the cost analysis use. Day 8 traded a tenth of everyone else's volume, which is 9.1% of the total.",
    )
    ax = fig.add_axes((0.06, 0.16, 0.90, 0.60))
    ax.plot(minutes, old, color=PALETTE["muted"], lw=1.2, label=f"Day 8: {np.nanmean(old):.2%} on average")
    ax.plot(minutes, new, color=PALETTE["navy"], lw=1.6, label=f"revisited: {np.nanmean(new):.2%} on average")
    ax.axhline(target, color=PALETTE["accent"], lw=1.2)
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.1%}")
    ax.set_ylim(target * 0.85, target * 1.08)
    style_axes(ax, xlabel="minute of the session", ylabel="share of the minute's volume", grid="y")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    caption(fig, "One order of 2m shares in a stock trading 2m a day, too large to finish: it trades every minute.")
    return fig


def plot_allocation(deviations: np.ndarray, case: Sequence[tuple[str, float, float]], examples: int) -> Figure:
    fig = new_figure(14.0, 6.0)
    title_block(
        fig,
        "Allocation, property-tested",
        f"{examples:,} random blocks and fills: every filled share goes to an account that asked for it, at one "
        "price, nobody past their request, each within a share of their exact pro-rata part.",
    )
    left = fig.add_axes((0.06, 0.15, 0.40, 0.60))
    left.hist(deviations, bins=np.linspace(-1, 1, 41), color=PALETTE["navy"])
    left.axvline(-1, color=PALETTE["loss"], lw=1)
    left.axvline(1, color=PALETTE["loss"], lw=1)
    style_axes(left, title="Shares allocated less the exact pro-rata part", xlabel="shares", grid="y")

    right = fig.add_axes((0.56, 0.15, 0.40, 0.60))
    names = [name for name, _, _ in case]
    y = np.arange(len(case))[::-1]
    right.barh(y + 0.18, [asked for _, asked, _ in case], height=0.34, color=PALETTE["grid"], label="requested")
    right.barh(y - 0.18, [got for _, _, got in case], height=0.34, color=PALETTE["navy"], label="allocated")
    for yi, (_, asked, got) in zip(y, case, strict=True):
        right.text(max(asked, got) + 8, yi, f"{got:g} of {asked:g}", va="center", fontsize=8.5)
    right.set_yticks(y, names)
    right.set_xlim(0, max(asked for _, asked, _ in case) * 1.35)
    style_axes(right, title="The block Day 8 could not allocate: 1,990 shares filled", grid="x")
    right.legend(frameon=False, fontsize=8.5, loc="lower right")
    caption(
        fig,
        "Requests in fractions of a share: the odd share by largest remainder took an account past its request and "
        "was lost, and the block failed its own check. The half share no account can take goes to the error account.",
    )
    return fig


# ---------------------------------------------------------------------------- the review
@dataclass(frozen=True)
class ReviewPanel:
    title: str
    labels: tuple[str, ...]
    before: tuple[float, ...]
    after: tuple[float, ...]
    unit: str  # a format spec
    note: str


def plot_review(panels: Sequence[ReviewPanel]) -> Figure:
    fig = new_figure(14.0, 5.6)
    title_block(
        fig,
        "A second reading of Day 8: the figures the faults changed",
        "Each panel sets the figure Day 8 produced (grey) beside the corrected one (navy).",
    )
    for index, panel in enumerate(panels):
        ax = fig.add_axes((0.05 + index * 0.33, 0.30, 0.27, 0.48))
        x = np.arange(len(panel.labels))
        for xi, (old, new) in enumerate(zip(panel.before, panel.after, strict=True)):
            ax.plot([xi, xi], [old, new], color=PALETTE["grid"], lw=3, zorder=1)
            ax.plot(xi, old, "o", color=PALETTE["muted"], ms=9, zorder=2, label="Day 8" if xi == 0 else None)
            ax.plot(xi, new, "o", color=PALETTE["navy"], ms=9, zorder=3, label="revisited" if xi == 0 else None)
            ax.text(xi - 0.08, old, f"{old:{panel.unit}}", va="center", ha="right", fontsize=8, color=PALETTE["muted"])
            ax.text(
                xi + 0.08, new, f"{new:{panel.unit}}", va="center", fontsize=8, color=PALETTE["ink"], fontweight="bold"
            )
        values = [*panel.before, *panel.after]
        low, high = min(values), max(values)
        pad = (high - low) * 0.3 or abs(high) * 0.1 or 1.0
        ax.set_ylim(low - pad, high + pad)
        ax.set_xlim(-0.6, len(panel.labels) - 0.4)
        ax.set_xticks(x, panel.labels, fontsize=8.5)
        style_axes(ax, title=panel.title, grid="y")
        ax.text(0.0, -0.18, textwrap.fill(panel.note, 58), transform=ax.transAxes, fontsize=8, color=PALETTE["muted"])
        ax.texts[-1].set_verticalalignment("top")
        if index == 0:
            ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    return fig
