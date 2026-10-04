"""Charts for the Day 4 revisit: performance against a reference library and a century of real returns.

The functions take plain inputs, prepared in :mod:`meridian.century_gallery`.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import matplotlib.dates as mdates
import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.transforms import blended_transform_factory

from .style import PALETTE, caption, new_figure, style_axes, title_block, x_of

INDUSTRY_COLOURS = {
    "NoDur": "#8FA9C9",
    "Durbl": "#B9C7D9",
    "Manuf": PALETTE["slate"],
    "Enrgy": "#C58B4E",
    "Chems": "#9C7FB8",
    "BusEq": PALETTE["navy"],
    "Telcm": PALETTE["sky"],
    "Utils": "#7FB3AA",
    "Shops": PALETTE["teal"],
    "Hlth": PALETTE["gain"],
    "Money": PALETTE["violet"],
    "Other": "#D7DEE8",
}
EFFECT_COLOURS = {"allocation": PALETTE["navy"], "selection": PALETTE["teal"], "interaction": PALETTE["violet"]}
METHOD_COLOURS = {
    "carino": PALETTE["navy"],
    "menchero": PALETTE["teal"],
    "grap": PALETTE["violet"],
    "frongello": PALETTE["sky"],
}
METHOD_NAMES = {"carino": "Cariño", "menchero": "Menchero", "grap": "GRAP", "frongello": "Frongello"}


# ---------------------------------------------------------------------------- reconciliation
@dataclass(frozen=True)
class ReferenceRow:
    dataset: str
    measure: str
    meridian: float
    empyrical: float
    recombined: float | None
    agrees: bool


def plot_reference(rows: Sequence[ReferenceRow]) -> Figure:
    count = len(rows)
    agreeing = sum(1 for row in rows if row.agrees)
    fig = new_figure(14.0, 0.29 * count + 2.8)
    title_block(
        fig,
        f"Every measure against empyrical: {agreeing} agree to 1e-10, {count - agreeing} differ by a convention "
        "that accounts for every digit",
        "Meridian's statistics against empyrical (pyfolio's library) and scipy, on the demonstration account and a "
        "century of US returns. Where they differ, the measure recombined their way lands back on their figure.",
    )
    top, bottom = 1 - 1.5 / fig.get_figheight(), 0.85 / fig.get_figheight()
    ax = fig.add_axes((0.36, bottom, 0.40, top - bottom))
    y = np.arange(count)[::-1]
    span = 0.5
    ax.axvspan(-span * 0.02, span * 0.02, color=PALETTE["band"], zorder=0)
    ax.axvline(0, color=PALETTE["gain"], lw=1)
    previous = None
    for position, row in zip(y, rows, strict=True):
        scale = max(abs(row.empyrical), 1e-12)
        gap = (row.meridian - row.empyrical) / scale
        shown = float(np.clip(gap, -span, span))
        if row.agrees:
            ax.plot(0, position, "o", color=PALETTE["navy"], ms=6, zorder=3)
        else:
            ax.plot(shown, position, "o", color=PALETTE["accent"], ms=6, zorder=3)
            if row.recombined is not None:
                back = (row.recombined - row.empyrical) / scale
                ax.annotate(
                    "",
                    xy=(back, position),
                    xytext=(shown, position),
                    arrowprops={"arrowstyle": "->", "color": PALETTE["teal"], "lw": 1.2},
                )
                ax.plot(back, position, "D", color=PALETTE["teal"], ms=5, zorder=4)
        if row.dataset != previous:
            ax.axhline(position + 0.5, color=PALETTE["grid"], lw=0.8)
            ax.text(
                0.012,
                position + 0.15,
                row.dataset,
                transform=blended_transform_factory(fig.transFigure, ax.transData),
                fontsize=9,
                fontweight="bold",
                color=PALETTE["ink"],
                va="bottom",
            )
            previous = row.dataset
        ax.text(-span * 1.04, position, row.measure, ha="right", va="center", fontsize=8.2, color=PALETTE["ink"])
        ax.text(
            span * 1.04,
            position,
            f"{row.meridian:,.4f}   {row.empyrical:,.4f}",
            ha="left",
            va="center",
            fontsize=8,
            color=PALETTE["muted"],
            family="monospace",
        )
    ax.text(
        span * 1.04,
        count - 0.2,
        "Meridian   empyrical",
        fontsize=8,
        color=PALETTE["muted"],
        fontweight="bold",
        family="monospace",
        va="bottom",
    )
    ax.set_xlim(-span, span)
    ax.set_ylim(-0.7, count - 0.1)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:+.0%}")
    style_axes(ax, xlabel="Meridian less empyrical, relative to empyrical's figure (clipped at ±50%)", grid="x")
    ax.spines["left"].set_visible(False)
    handles = [
        Line2D([], [], marker="o", ls="", color=PALETTE["navy"], label="agrees to 1e-10"),
        Line2D([], [], marker="o", ls="", color=PALETTE["accent"], label="differs by a convention"),
        Line2D([], [], marker="D", ls="", color=PALETTE["teal"], label="recombined empyrical's way"),
    ]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=3, frameon=False, fontsize=8.5)
    caption(
        fig,
        "Conventions: annual return by calendar time (GIPS) against period count; geometric against "
        "arithmetic Sharpe and Sortino; Jensen's alpha against the regression intercept. "
        "Reference: empyrical-reloaded 0.5; scipy.stats for skewness and kurtosis.",
    )
    return fig


# ---------------------------------------------------------------------------- the benchmark rebuilt
def plot_rebuilt_market(
    months: Sequence[date],
    rebuilt: Sequence[float],
    published: Sequence[float],
    by_decade: Mapping[int, float],
    largest: tuple[date, float],
    correlation: float,
) -> Figure:
    fig = new_figure(14.0, 8.6)
    gaps = np.array(rebuilt) - np.array(published)
    title_block(
        fig,
        "The US market rebuilt from twelve industries, against the market Fama and French publish",
        f"Each industry weighted by its firms times their average size at the start of the month: an index built the "
        f"way a provider builds one. {len(months):,} months, {np.sqrt(np.mean(gaps**2)) * 1e4:.0f} bp a month apart, "
        f"correlation {correlation:.5f}.",
    )
    ax = fig.add_axes((0.06, 0.47, 0.66, 0.40))
    growth_r, growth_p = np.cumprod(1.0 + np.array(rebuilt)), np.cumprod(1.0 + np.array(published))
    ax.plot(months, growth_p, color=PALETTE["slate"], lw=2.2, label="published market (Mkt-RF + RF)")
    ax.plot(months, growth_r, color=PALETTE["navy"], lw=1.2, ls="--", label="rebuilt from its twelve industries")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(lambda value, _: f"${value:,.0f}")
    style_axes(ax, ylabel="growth of $1 (log scale)", grid="y")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.text(x_of(months[-1]), growth_r[-1], f"  ${growth_r[-1]:,.0f}", fontsize=9, color=PALETTE["navy"], va="bottom")
    ax.text(x_of(months[-1]), growth_p[-1], f"  ${growth_p[-1]:,.0f}", fontsize=9, color=PALETTE["slate"], va="top")
    low = fig.add_axes((0.06, 0.10, 0.66, 0.28), sharex=ax)
    low.bar(months, gaps * 1e4, width=25, color=np.where(gaps > 0, PALETTE["teal"], PALETTE["loss"]), lw=0)
    month, gap = largest
    low.annotate(
        f"{month:%B %Y}: {gap * 1e4:+.0f} bp\nthe top of the technology bubble",
        xy=(x_of(month), gap * 1e4),
        xytext=(x_of(date(1975, 1, 1)), gap * 1e4 * 0.85),
        fontsize=8.5,
        color=PALETTE["accent"],
        fontweight="bold",
        arrowprops={"arrowstyle": "->", "color": PALETTE["accent"]},
    )
    style_axes(low, ylabel="rebuilt less published (bp)", grid="y")
    low.xaxis.set_major_locator(mdates.YearLocator(10))
    low.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    side = fig.add_axes((0.79, 0.10, 0.18, 0.77))
    decades = list(by_decade)
    side.barh(range(len(decades)), [by_decade[d] * 1e4 for d in decades], color=PALETTE["slate"], height=0.6)
    side.set_yticks(range(len(decades)), [f"{d}s" for d in decades], fontsize=8.5)
    side.invert_yaxis()
    for index, decade in enumerate(decades):
        side.text(by_decade[decade] * 1e4 + 0.5, index, f"{by_decade[decade] * 1e4:.1f}", va="center", fontsize=8)
    style_axes(side, title="Gap by decade (rms, bp a month)", grid="x")
    caption(
        fig,
        "Source: Kenneth R. French Data Library (CRSP): 12 industry portfolios, number of firms and average "
        "firm size; Fama-French market factor. The gap is the universe difference between the two tables.",
    )
    return fig


# ---------------------------------------------------------------------------- industry weights
def plot_industry_weights(
    months: Sequence[date], weights: Mapping[str, Sequence[float]], names: Mapping[str, str]
) -> Figure:
    fig = new_figure(14.0, 7.6)
    title_block(
        fig,
        "A century of the US market's composition: what a cap-weighted benchmark asks you to own",
        "Each industry's share of the market's value at the start of every month since July 1926. The benchmark is "
        "not a fixed thing: it is whatever the market's largest companies happen to be.",
    )
    ax = fig.add_axes((0.06, 0.1, 0.72, 0.76))
    keys = list(weights)
    ax.stackplot(
        months, *[np.array(weights[key]) * 100 for key in keys], colors=[INDUSTRY_COLOURS[k] for k in keys], lw=0
    )
    ax.set_xlim(x_of(months[0]), x_of(months[-1]))
    ax.set_ylim(0, 100)
    style_axes(ax, ylabel="share of market value (%)", grid=None)
    for year, text in (
        (1929, "1929: utilities\nand industry"),
        (1980, "1980: energy\nat its peak"),
        (2000, "2000: the\ntechnology bubble"),
    ):
        ax.axvline(x_of(date(year, 6, 30)), color="white", lw=0.8, alpha=0.7)
        ax.text(x_of(date(year, 6, 30)), 101, text, ha="center", va="bottom", fontsize=8, color=PALETTE["muted"])
    handles = [Patch(color=INDUSTRY_COLOURS[key], label=f"{names[key]} ({weights[key][-1]:.0%})") for key in keys[::-1]]
    fig.legend(
        handles=handles,
        loc="center left",
        bbox_to_anchor=(0.795, 0.48),
        frameon=False,
        fontsize=9,
        title="Latest weight",
        title_fontsize=9,
    )
    caption(
        fig,
        "Source: Kenneth R. French Data Library (CRSP), 12 industry portfolios: number of firms times average "
        "firm size. Industries follow the library's SIC-based definitions.",
    )
    return fig


# ---------------------------------------------------------------------------- decade attribution
@dataclass(frozen=True)
class DecadeBar:
    label: str
    portfolio: float
    benchmark: float
    effects: Mapping[str, float]


def plot_decades(bars: Sequence[DecadeBar], century: tuple[float, float]) -> Figure:
    fig = new_figure(14.0, 7.8)
    p, b = century
    title_block(
        fig,
        "Every stock in equal weight against the cap-weighted market, decade by decade",
        f"Brinson-Fachler by industry. Allocation is weighting industries by their number of firms; selection "
        f"is holding each industry's stocks equally rather than by size. Over the century: {p:.2%} a year "
        f"against {b:.2%}.",
    )
    ax = fig.add_axes((0.07, 0.14, 0.88, 0.70))
    x = np.arange(len(bars))
    width = 0.24
    for offset, (effect, colour) in zip((-1, 0, 1), EFFECT_COLOURS.items(), strict=True):
        ax.bar(x + offset * width, [bar.effects[effect] * 100 for bar in bars], width=width, color=colour, label=effect)
    active = [(bar.portfolio - bar.benchmark) * 100 for bar in bars]
    ax.plot(x, active, "D", color=PALETTE["accent"], ms=8, zorder=5, label="active return (linked total)")
    ax.axhline(0, color=PALETTE["muted"], lw=0.8)
    ax.set_xticks(x, [f"{bar.label}\n{bar.portfolio:+.0%}\nvs {bar.benchmark:+.0%}" for bar in bars], fontsize=8.5)
    style_axes(ax, ylabel="effect over the decade (percentage points)", grid="y")
    ax.legend(frameon=False, fontsize=9, ncol=4, loc="upper right")
    ax.text(
        0.99,
        0.90,
        "under each decade: equal-weighted return vs cap-weighted",
        transform=ax.transAxes,
        ha="right",
        fontsize=8,
        color=PALETTE["muted"],
    )
    caption(
        fig,
        "Source: Kenneth R. French Data Library: equal- and value-weighted returns, number of firms and size of "
        "12 industries. Each decade linked on its own (Cariño); the 1920s are July 1926 to December 1929.",
    )
    return fig


# ---------------------------------------------------------------------------- linking methods
def plot_linking(
    short: Mapping[str, Mapping[str, float]],
    short_active: float,
    short_label: str,
    long: Mapping[str, Mapping[str, float]],
    long_active: float,
    long_label: str,
    growth_note: str = "",
) -> Figure:
    fig = new_figure(14.0, 7.0)
    title_block(
        fig,
        "Four linking methods, one total: the longer the horizon, the more the choice matters",
        "Each method links monthly Brinson effects to the compounded active return with nothing left over. Over a "
        "year they differ by tens of basis points; over a century they move up to a fifth of the answer.",
    )
    effects = list(EFFECT_COLOURS)
    for column, (data, active, label, unit) in enumerate(
        ((short, short_active, short_label, "bp"), (long, long_active, long_label, "share"))
    ):
        ax = fig.add_axes((0.06 + column * 0.48, 0.14, 0.42, 0.66))
        x = np.arange(len(effects))
        width = 0.2
        for index, method in enumerate(data):
            values = [data[method][effect] * (1e4 if unit == "bp" else 100 / active) for effect in effects]
            ax.bar(
                x + (index - 1.5) * width, values, width=width, color=METHOD_COLOURS[method], label=METHOD_NAMES[method]
            )
        ax.axhline(0, color=PALETTE["muted"], lw=0.8)
        ax.set_xticks(x, effects)
        subtitle = f"active return {active * 1e4:+,.0f} bp" if unit == "bp" else growth_note
        style_axes(
            ax,
            title=f"{label}: {subtitle}",
            ylabel="linked effect (bp)" if unit == "bp" else "share of the active return (%)",
            grid="y",
        )
        if column == 0:
            ax.legend(frameon=False, fontsize=9, loc="lower left")
    caption(
        fig,
        "Equal-weighted against cap-weighted US market by industry, monthly effects. Cariño (1999), Menchero "
        "(2000), GRAP (1997), Frongello (2002); Frongello's totals equal GRAP's, as its recursion unrolls to it.",
    )
    return fig


# ---------------------------------------------------------------------------- drawdowns
@dataclass(frozen=True)
class Episode:
    peak: date
    trough: date
    recovery: date | None
    depth: float


def plot_century_drawdowns(days: Sequence[date], underwater: Sequence[float], episodes: Sequence[Episode]) -> Figure:
    fig = new_figure(14.0, 6.8)
    title_block(
        fig,
        "A century of drawdowns in the US market: how far below its last peak, every month since 1926",
        "Total return, dividends reinvested, before inflation. The Depression took 83.7% and fifteen years to recover; "
        "every later fall was shallower, and the longest still took four to seven years.",
    )
    ax = fig.add_axes((0.06, 0.12, 0.90, 0.72))
    values = np.array(underwater) * 100
    ax.fill_between(days, values, 0, color=PALETTE["loss"], alpha=0.25, lw=0)
    ax.plot(days, values, color=PALETTE["loss"], lw=0.9)
    ordered = sorted(episodes, key=lambda item: item.trough)
    for index, episode in enumerate(ordered):
        years = ((episode.recovery or days[-1]) - episode.peak).days / 365.25
        text = (
            f"{episode.depth:.1%}\n{episode.peak:%b %Y} to {episode.trough:%b %Y}\n"
            f"{'recovered ' + format(episode.recovery, '%b %Y') if episode.recovery else 'not yet recovered'} "
            f"({years:.1f} years)"
        )
        # a label runs about eight years to the right; one whose neighbour is closer goes to the left instead
        crowded = index + 1 < len(ordered) and (ordered[index + 1].trough - episode.trough).days < 9 * 365
        offset, align, drop = (-400, "right", 16) if crowded else (400, "left", 6)
        ax.annotate(
            text,
            xy=(x_of(episode.trough), episode.depth * 100),
            xytext=(x_of(episode.trough) + offset, episode.depth * 100 - drop),
            fontsize=8,
            ha=align,
            color=PALETTE["ink"],
            arrowprops={"arrowstyle": "-", "color": PALETTE["muted"], "lw": 0.8},
        )
    ax.set_ylim(-100, 3)
    style_axes(ax, ylabel="below the last peak (%)", grid="y")
    ax.xaxis.set_major_locator(mdates.YearLocator(10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    caption(
        fig,
        "Source: Kenneth R. French Data Library, the Fama-French market return (Mkt-RF + RF), monthly. "
        "Drawdown episodes from meridian.performance.statistics.drawdown_episodes.",
    )
    return fig


# ---------------------------------------------------------------------------- rolling Sharpe
def plot_rolling_sharpe(
    days: Sequence[date], sharpe: Sequence[float], volatility: Sequence[float], decades: Mapping[str, float]
) -> Figure:
    fig = new_figure(14.0, 7.4)
    title_block(
        fig,
        "Ten years at a time: the reward the US market paid per unit of risk",
        "Rolling 120-month Sharpe ratio of the market over Treasury bills, and its volatility. A decade is long enough "
        "to feel permanent and short enough to mislead: the ratio has ranged from below zero to above one.",
    )
    ax = fig.add_axes((0.06, 0.44, 0.66, 0.42))
    ax.plot(days, sharpe, color=PALETTE["navy"], lw=1.6)
    ax.axhline(0, color=PALETTE["muted"], lw=0.8)
    ax.fill_between(days, sharpe, 0, where=np.array(sharpe) < 0, color=PALETTE["loss"], alpha=0.2, lw=0)
    style_axes(ax, ylabel="Sharpe ratio, trailing 10 years", grid="y")
    low = fig.add_axes((0.06, 0.10, 0.66, 0.26), sharex=ax)
    low.plot(days, np.array(volatility) * 100, color=PALETTE["slate"], lw=1.2)
    style_axes(low, ylabel="volatility (%)", grid="y")
    low.xaxis.set_major_locator(mdates.YearLocator(10))
    low.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    side = fig.add_axes((0.79, 0.10, 0.18, 0.76))
    labels = list(decades)
    values = [decades[key] for key in labels]
    side.barh(
        range(len(labels)), values, color=[PALETTE["gain"] if v > 0 else PALETTE["loss"] for v in values], height=0.6
    )
    side.set_yticks(range(len(labels)), labels, fontsize=8.5)
    side.invert_yaxis()
    side.axvline(0, color=PALETTE["muted"], lw=0.8)
    for index, value in enumerate(values):
        side.text(
            max(value, 0.0) + 0.03,
            index,
            f"{value:.2f}",
            va="center",
            ha="left",
            fontsize=8,
            color=PALETTE["loss"] if value < 0 else PALETTE["ink"],
        )
    style_axes(side, title="Sharpe ratio by decade", grid="x")
    caption(
        fig,
        "Source: Kenneth R. French Data Library: Mkt-RF (the market over the one-month bill), monthly, "
        "annualised with twelve periods. Arithmetic Sharpe on excess returns, as Sharpe (1994) defines it.",
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
        "A second reading of Day 4: four faults, before and after",
        "Each panel sets the figure Day 4 produced (grey) beside the corrected one (navy). None was large on the "
        "demonstration account; each would have been wrong on a client's statement.",
    )
    for index, panel in enumerate(panels):
        row, column = divmod(index, 2)
        ax = fig.add_axes((0.06 + column * 0.49, 0.56 - row * 0.44, 0.40, 0.24))
        x = np.arange(len(panel.labels))
        for xi, (old, new) in enumerate(zip(panel.before, panel.after, strict=True)):
            ax.plot([xi, xi], [old, new], color=PALETTE["grid"], lw=3, zorder=1)
            ax.plot(xi, old, "o", color=PALETTE["muted"], ms=9, zorder=2, label="Day 4" if xi == 0 else None)
            ax.plot(xi, new, "o", color=PALETTE["navy"], ms=9, zorder=3, label="revisited" if xi == 0 else None)
            ax.text(xi + 0.08, old, f"{old:{panel.unit}}", va="center", fontsize=8, color=PALETTE["muted"])
            ax.text(
                xi + 0.08, new, f"{new:{panel.unit}}", va="center", fontsize=8, color=PALETTE["ink"], fontweight="bold"
            )
        values = [*panel.before, *panel.after]
        low, high = min(values), max(values)
        pad = (high - low) * 0.25 or abs(high) * 0.01 or 0.01
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
        "XIRR: Microsoft's published example. Capture: a portfolio at 1.5x and 2x the benchmark's daily "
        "returns. Trailing year and short-period Sharpe: the demonstration account.",
    )
    return fig
