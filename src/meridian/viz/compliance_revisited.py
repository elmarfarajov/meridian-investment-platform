"""Charts for the Day 6 revisit: compliance that cannot be talked past, and a century of a sector limit.

The functions take plain inputs, prepared in :mod:`meridian.compliance_revisited_gallery`.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import matplotlib.dates as mdates
import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from .style import PALETTE, caption, new_figure, style_axes, title_block, x_of

INDUSTRY_COLOURS = {
    "Business equipment": PALETTE["navy"],
    "Manufacturing": PALETTE["slate"],
    "Energy": "#C58B4E",
    "Utilities": "#7FB3AA",
    "Consumer non-durables": "#8FA9C9",
    "Finance": PALETTE["violet"],
    "Telecoms": PALETTE["sky"],
    "Other": "#B9A68C",
}


# ---------------------------------------------------------------------------- the guarantee
@dataclass(frozen=True)
class GuaranteeBar:
    label: str
    old: int
    new: int


def plot_guarantee(
    orders: int, bars: Sequence[GuaranteeBar], examples: Sequence[tuple[str, str, str]], totals: tuple[int, int]
) -> Figure:
    fig = new_figure(14.0, 7.2)
    total_old, total_new = totals
    title_block(
        fig,
        f"Orders the pre-trade check let through although they made a hard limit worse: {total_old} of {orders:,}, "
        f"now {total_new}",
        "Random portfolios and random orders, each judged twice - by Day 6's rule (a breach measured by its "
        "utilisation, the rule's heaviest group only) and by the revisited one (excess past the limit, every group).",
    )
    ax = fig.add_axes((0.07, 0.14, 0.45, 0.66))
    y = np.arange(len(bars))[::-1]
    ax.barh(y + 0.18, [bar.old for bar in bars], height=0.34, color=PALETTE["loss"], label="Day 6")
    ax.barh(y - 0.18, [bar.new for bar in bars], height=0.34, color=PALETTE["gain"], label="revisited")
    for position, bar in zip(y, bars, strict=True):
        ax.text(bar.old + 0.5, position + 0.18, str(bar.old), va="center", fontsize=9, color=PALETTE["loss"])
        ax.text(bar.new + 0.5, position - 0.18, str(bar.new), va="center", fontsize=9, color=PALETTE["gain"])
    ax.set_yticks(y, [textwrap.fill(bar.label, 26) for bar in bars], fontsize=9)
    style_axes(ax, xlabel="orders let through that made the limit worse", grid="x")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    right = fig.add_axes((0.58, 0.14, 0.40, 0.66))
    right.axis("off")
    right.set_title("How each slipped through", loc="left", fontsize=11)
    for index, (name, before, after) in enumerate(examples):
        top = 0.92 - index * 0.32
        right.text(0.0, top, name, fontsize=10, fontweight="bold", color=PALETTE["ink"], transform=right.transAxes)
        right.text(
            0.0,
            top - 0.06,
            textwrap.fill("Day 6: " + before, 70),
            fontsize=8.6,
            color=PALETTE["loss"],
            transform=right.transAxes,
            va="top",
        )
        right.text(
            0.0,
            top - 0.17,
            textwrap.fill("Now: " + after, 70),
            fontsize=8.6,
            color=PALETTE["gain"],
            transform=right.transAxes,
            va="top",
        )
    caption(
        fig,
        "Hard limits: single issuer 10%, single sector 40%, no tobacco, cash between 1% and 10%. An order "
        "counts when an independent measure of every issuer's and sector's excess grew and the check said "
        "'allowed' or 'warning'.",
    )
    return fig


# ---------------------------------------------------------------------------- the register per issuer
@dataclass(frozen=True)
class RegisterBar:
    group: str
    opened: date
    closed: date | None
    kind: str
    hidden: bool  # missed by the register of one record per rule


def plot_register(bars: Sequence[RegisterBar], last: date, old_count: int, new_count: int, rule: str) -> Figure:
    fig = new_figure(14.0, 6.2)
    hidden = sum(1 for bar in bars if bar.hidden)
    title_block(
        fig,
        f"One breach per issuer: the register held {old_count} breaches, it holds {new_count}",
        f"'{rule}', breach by breach. Day 6 kept one record per rule, judged by the heaviest issuer; the {hidden} "
        "highlighted breaches were a second issuer over the limit while the first was too, and went unrecorded.",
    )
    ax = fig.add_axes((0.1, 0.22, 0.86, 0.6))
    groups = list(dict.fromkeys(bar.group for bar in bars))
    for bar in bars:
        row = groups.index(bar.group)
        end = bar.closed or last
        colour = PALETTE["accent"] if bar.hidden else (PALETTE["loss"] if bar.kind == "active" else PALETTE["slate"])
        ax.barh(row, max((end - bar.opened).days, 1), left=x_of(bar.opened), height=0.5, color=colour)
    ax.set_yticks(range(len(groups)), groups, fontsize=10)
    ax.invert_yaxis()
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    style_axes(ax, grid="x")
    handles = [
        Patch(color=PALETTE["slate"], label="passive breach, recorded by Day 6"),
        Patch(color=PALETTE["loss"], label="active breach, recorded by Day 6"),
        Patch(color=PALETTE["accent"], label="breach Day 6's register did not record"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3)
    caption(
        fig,
        "The demonstration account's daily post-trade checks since April 2024, replayed through both "
        "registers. A breach is now keyed by rule and group (migration 0010 stores the group).",
    )
    return fig


# ---------------------------------------------------------------------------- a century of the sector limit
def plot_century_limit(
    months: Sequence[date],
    largest: Sequence[float],
    leaders: Sequence[str],
    limit: float,
    warning: float,
    breaches: Sequence[tuple[date, date | None]],
    peak_2000: tuple[date, float],
) -> Figure:
    fig = new_figure(14.0, 7.0)
    title_block(
        fig,
        "A 40% limit on any one industry, applied to the US market since 1926: broken once, in 2025",
        "The weight of the market's largest industry at the start of every month, coloured by which industry it "
        "was. An index fund holding the market would have been in passive breach only since August 2025.",
    )
    ax = fig.add_axes((0.06, 0.12, 0.72, 0.72))
    values = np.array(largest) * 100
    for name in dict.fromkeys(leaders):
        mask = np.array([leader == name for leader in leaders])
        ax.scatter(
            np.array(months)[mask], values[mask], s=5, color=INDUSTRY_COLOURS.get(name, PALETTE["muted"]), label=name
        )
    ax.axhline(limit * 100, color=PALETTE["loss"], lw=1.2)
    ax.axhline(warning * 100, color=PALETTE["accent"], lw=1.0, ls="--")
    ax.text(x_of(months[0]), limit * 100 + 0.6, "limit 40%", color=PALETTE["loss"], fontsize=8.5)
    ax.text(x_of(months[0]), warning * 100 + 0.6, "warning 35%", color=PALETTE["accent"], fontsize=8.5)
    for opened, closed in breaches:
        ax.axvspan(x_of(opened), x_of(closed or months[-1]), color=PALETTE["loss"], alpha=0.15, lw=0)
    day, value = peak_2000
    # the peak ringed and joined to its note: a plain line, which every backend draws
    note_x = x_of(date(1993, 1, 1))
    ax.plot([note_x + 200, x_of(day) - 120], [31.2, value * 100 - 0.4], color=PALETTE["muted"], lw=0.9)
    ax.plot([x_of(day)], [value * 100], "o", ms=11, mfc="none", mec=PALETTE["accent"], mew=1.5)
    ax.text(
        note_x,
        30.5,
        f"March 2000: {value:.1%}\nthe technology bubble stayed short of the warning",
        fontsize=8.5,
        color=PALETTE["ink"],
        ha="right",
    )
    ax.set_ylim(10, 50)
    ax.xaxis.set_major_locator(mdates.YearLocator(10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    style_axes(ax, ylabel="largest industry's share of the market (%)", grid="y")
    ax.legend(
        frameon=False,
        fontsize=8.5,
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        markerscale=3,
        title="largest industry",
        title_fontsize=9,
    )
    caption(
        fig,
        "Source: Kenneth R. French Data Library (CRSP), 12 industry portfolios: firms times average size. "
        "Checked with meridian.compliance; breaches from its register, all passive and none traded.",
    )
    return fig


# ---------------------------------------------------------------------------- concentration
def plot_effective_number(months: Sequence[date], effective: Sequence[float], top_two: Sequence[float]) -> Figure:
    fig = new_figure(14.0, 6.6)
    title_block(
        fig,
        "The US market has never been so concentrated in so few industries",
        "The effective number of industries - one over the sum of squared weights, twelve if all were equal - and "
        "the weight of the two largest together, every month since 1926.",
    )
    ax = fig.add_axes((0.06, 0.12, 0.88, 0.72))
    ax.plot(months, effective, color=PALETTE["navy"], lw=1.6, label="effective number of industries (left)")
    style_axes(ax, ylabel="effective number of industries", grid="y")
    twin = ax.twinx()
    twin.plot(months, np.array(top_two) * 100, color=PALETTE["accent"], lw=1.2, label="two largest together (right)")
    twin.set_ylabel("two largest industries (%)", color=PALETTE["accent"], fontsize=9)
    twin.grid(visible=False)
    low = int(np.argmin(effective))
    ax.plot([x_of(months[low])], [effective[low]], "o", ms=10, mfc="none", mec=PALETTE["accent"], mew=1.5)
    ax.text(
        x_of(months[low]) - 300,
        effective[low] + 0.1,
        f"{months[low]:%B %Y}: {effective[low]:.1f}",
        fontsize=9,
        color=PALETTE["navy"],
        ha="right",
        va="bottom",
    )
    ax.xaxis.set_major_locator(mdates.YearLocator(10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    lines = ax.get_legend_handles_labels()[0] + twin.get_legend_handles_labels()[0]
    ax.legend(
        handles=lines, labels=[str(line.get_label()) for line in lines], frameon=False, fontsize=9, loc="upper right"
    )
    caption(
        fig,
        "Source: Kenneth R. French Data Library (CRSP), 12 industry portfolios. The effective number is "
        "the inverse Herfindahl index of the industries' market weights.",
    )
    return fig


# ---------------------------------------------------------------------------- the capped index
def plot_capped(
    months: Sequence[date],
    monthly_gap: Sequence[float],
    cumulative_gap: Sequence[float],
    binding: Sequence[bool],
    summary: Mapping[str, str],
    cap: float,
    since: date,
) -> Figure:
    fig = new_figure(14.0, 6.6)
    title_block(
        fig,
        f"What a {cap:.0%} cap on any industry would have cost an index fund: nothing for 95 years, then 0.5%",
        "A capped index rebalanced monthly to market weights with no industry above the cap, against the market. "
        f"Bars: each month's return difference; line: the cumulative difference since {since:%Y}. "
        "Shaded: the cap bound.",
    )
    ax = fig.add_axes((0.06, 0.12, 0.62, 0.72))
    chosen = [index for index, month in enumerate(months) if month >= since]
    days = [months[index] for index in chosen]
    for index in chosen:
        if binding[index]:
            ax.axvspan(x_of(months[index]) - 15, x_of(months[index]) + 15, color=PALETTE["accent"], alpha=0.2, lw=0)
    gaps = np.array([monthly_gap[index] for index in chosen]) * 1e4
    ax.bar(days, gaps, width=20, color=np.where(gaps >= 0, PALETTE["gain"], PALETTE["loss"]), alpha=0.7)
    base = cumulative_gap[chosen[0] - 1] if chosen[0] else 0.0
    ax.plot(
        days,
        (np.array([cumulative_gap[index] for index in chosen]) - base) * 1e4,
        color=PALETTE["navy"],
        lw=2,
        label="cumulative difference",
    )
    ax.axhline(0, color=PALETTE["muted"], lw=0.8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    style_axes(ax, ylabel="capped less market (bp)", grid="y")
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    side = fig.add_axes((0.72, 0.12, 0.26, 0.72))
    side.axis("off")
    for index, (label, value) in enumerate(summary.items()):
        side.text(0.0, 0.95 - index * 0.13, label, fontsize=9, color=PALETTE["muted"], transform=side.transAxes)
        side.text(
            0.0,
            0.89 - index * 0.13,
            value,
            fontsize=13,
            fontweight="bold",
            color=PALETTE["ink"],
            transform=side.transAxes,
        )
    caption(
        fig,
        "Source: Kenneth R. French Data Library, 12 industries' value-weighted returns, firms and size. The "
        "cap redistributes the excess pro rata among the other industries, as capped indices do.",
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
    fig = new_figure(14.0, 5.6)
    title_block(
        fig,
        "A second reading of Day 6: the figures the faults changed",
        "Each panel sets the figure Day 6 produced (grey) beside the corrected one (navy).",
    )
    for index, panel in enumerate(panels):
        ax = fig.add_axes((0.05 + index * 0.33, 0.30, 0.27, 0.48))
        x = np.arange(len(panel.labels))
        for xi, (old, new) in enumerate(zip(panel.before, panel.after, strict=True)):
            ax.plot([xi, xi], [old, new], color=PALETTE["grid"], lw=3, zorder=1)
            ax.plot(xi, old, "o", color=PALETTE["muted"], ms=9, zorder=2, label="Day 6" if xi == 0 else None)
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
        ax.text(
            0.0,
            -0.18,
            textwrap.fill(panel.note, 58),
            transform=ax.transAxes,
            fontsize=8,
            color=PALETTE["muted"],
            va="top",
        )
        if index == 0:
            ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    return fig
