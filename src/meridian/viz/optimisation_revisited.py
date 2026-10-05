"""Charts for the Day 7 revisit: the tax code as the IRS writes it, and harvesting on a century of real returns.

The functions take plain inputs, prepared in :mod:`meridian.optimisation_revisited_gallery`.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import matplotlib.dates as mdates
import numpy as np
from matplotlib.figure import Figure

from .style import PALETTE, caption, new_figure, style_axes, title_block, x_of

MANAGER_COLOURS = {
    "buy and hold": PALETTE["slate"],
    "tax-blind": PALETTE["loss"],
    "tax-aware": PALETTE["sky"],
    "tax-aware, harvesting": PALETTE["teal"],
}
SOURCE = "Source: Kenneth R. French Data Library (CRSP), 12 industry portfolios, value-weighted, July 1926 - 2026."


# ---------------------------------------------------------------------------- a century of tax drag
@dataclass(frozen=True)
class DecadeBars:
    label: str
    index_return: float
    drag: Mapping[str, float]  # manager -> annual tax drag
    saved: float  # harvesting's drag below tax-blind's
    tracking: float  # harvesting's pre-tax return over tax-blind's
    harvested: float  # losses realised over the decade, fraction of the starting value


def short_label(label: str) -> str:
    """``1931-1940`` as ``1930s``; a window that is not a decade as ``2016-25``."""
    first, last = (int(part) for part in label.split("-"))
    if first % 10 == 1 and last == first + 9:
        return f"{first - 1}s"
    return f"{first}-{last % 100:02d}"


def plot_century_drag(decades: Sequence[DecadeBars]) -> Figure:
    fig = new_figure(14.0, 7.6)
    title_block(
        fig,
        "What tax cost an index account, decade by decade since 1931",
        "Four managers of the same $5m account, tracking the US market through its twelve industries under today's "
        "tax code. Tax drag: the pre-tax return less the after-tax return on liquidation at the decade's end.",
    )
    managers = list(decades[0].drag)
    x = np.arange(len(decades))
    top = fig.add_axes((0.06, 0.70, 0.90, 0.13))
    returns = [item.index_return for item in decades]
    top.bar(x, returns, width=0.6, color=[PALETTE["gain"] if r >= 0 else PALETTE["loss"] for r in returns])
    for xi, value in zip(x, returns, strict=True):
        top.text(xi, value + 0.006, f"{value:.1%}", ha="center", fontsize=8, color=PALETTE["ink"])
    top.set_xticks(x, [""] * len(x))
    top.set_ylim(0, max(returns) * 1.35)
    top.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    style_axes(top, ylabel="index, a year", grid="y")

    ax = fig.add_axes((0.06, 0.16, 0.90, 0.48))
    width = 0.8 / len(managers)
    for position, manager in enumerate(managers):
        values = [item.drag[manager] * 1e4 for item in decades]
        ax.bar(
            x - 0.4 + width * (position + 0.5),
            values,
            width=width * 0.92,
            color=MANAGER_COLOURS.get(manager, PALETTE["navy"]),
            label=manager,
        )
        for xi, value in zip(x, values, strict=True):
            if value < 5:  # a bar too short to see: say what it is
                ax.text(
                    xi - 0.4 + width * (position + 0.5),
                    value + 3,
                    f"{value:.0f}",
                    ha="center",
                    fontsize=7.5,
                    color=MANAGER_COLOURS.get(manager, PALETTE["navy"]),
                )
    for xi, item in zip(x, decades, strict=True):
        high = max(item.drag.values()) * 1e4
        ax.text(xi, high + 8, f"saved {item.saved * 1e4:.0f} bp", ha="center", fontsize=8, color=PALETTE["teal"])
    ax.set_xticks(x, [item.label for item in decades], fontsize=9)
    ax.set_ylim(0, max(max(item.drag.values()) for item in decades) * 1e4 * 1.18)
    style_axes(ax, ylabel="tax drag, basis points a year", grid="y")
    ax.legend(frameon=False, ncol=4, loc="upper left", fontsize=9)
    caption(
        fig,
        "Saved: the harvesting manager's drag below the tax-blind manager's. Tax drag rises with the return itself - "
        "most of what an index account pays is the long-term gain on liquidation. " + SOURCE,
    )
    return fig


def plot_century_saved(decades: Sequence[DecadeBars]) -> Figure:
    fig = new_figure(14.0, 6.8)
    title_block(
        fig,
        "Harvesting saved tax in every decade - most when the market fell",
        "The tax the harvesting manager avoided, set apart from what its trades did to the pre-tax return; and the "
        "losses it found to harvest.",
    )
    x = np.arange(len(decades))
    left = fig.add_axes((0.06, 0.17, 0.52, 0.62))
    saved = [item.saved * 1e4 for item in decades]
    tracking = [item.tracking * 1e4 for item in decades]
    left.bar(x - 0.2, saved, width=0.38, color=PALETTE["teal"], label="tax saved (tax alpha)")
    left.bar(x + 0.2, tracking, width=0.38, color=PALETTE["grid"], label="pre-tax difference (tracking luck)")
    for xi, value in zip(x, saved, strict=True):
        left.text(xi - 0.2, value + 1.5, f"{value:.0f}", ha="center", fontsize=8, color=PALETTE["teal"])
    left.axhline(0, color=PALETTE["muted"], lw=0.8)
    left.set_xticks(x, [item.label.replace("-", "-\n") for item in decades], fontsize=8)
    style_axes(left, ylabel="against the tax-blind manager, bp a year", grid="y")
    left.legend(frameon=False, fontsize=8.5, loc="upper right")

    right = fig.add_axes((0.67, 0.17, 0.30, 0.62))
    harvested = [item.harvested for item in decades]
    right.scatter(harvested, saved, s=60, color=PALETTE["teal"], zorder=3)
    placed: list[tuple[float, float]] = []
    for item, h, s in sorted(zip(decades, harvested, saved, strict=True), key=lambda row: -row[2]):
        y = s + 0.8
        while any(abs(h - px) < 0.03 and abs(y - py) < 1.6 for px, py in placed):
            y -= 1.6  # below the label already there
        placed.append((h, y))
        right.text(h + 0.006, y, short_label(item.label), fontsize=8, color=PALETTE["ink"])
    right.xaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    right.set_xlim(-0.01, max(harvested) * 1.25)
    right.set_ylim(min(0, min(saved)) - 3, max(saved) * 1.2)
    style_axes(
        right,
        title="Losses harvested and tax saved",
        xlabel="losses harvested over the decade, share of the account",
        ylabel="tax saved, bp a year",
        grid="both",
    )
    caption(
        fig,
        "Harvested losses offset the client's other short-term gains (2% of the account a year) at 40.8% and return "
        "at 23.8% when the lower basis is sold: the saving is the difference, and deferral. " + SOURCE,
    )
    return fig


# ---------------------------------------------------------------------------- one decade up close
def plot_decade_account(
    label: str,
    note: str,
    days: Sequence[date],
    index_level: Sequence[float],
    harvested: Sequence[float],
    carryforward: Sequence[float],
    wealth: Mapping[str, Sequence[float]],
) -> Figure:
    fig = new_figure(14.0, 7.4)
    title_block(
        fig,
        f"Harvesting through the Depression: the account month by month, {label}",
        textwrap.fill(
            "The market fell by two thirds, recovered and fell again. Every fall was a loss to harvest; most of it "
            "could not be used at once, and was carried forward. " + note,
            175,
        ),
    )
    top = fig.add_axes((0.06, 0.50, 0.60, 0.32))
    top.plot(days, index_level, color=PALETTE["navy"], lw=1.6)
    top.axhline(1.0, color=PALETTE["muted"], lw=0.8, ls=":")
    top.yaxis.set_major_formatter(lambda value, _: f"{value:.1f}")
    style_axes(top, ylabel="index, start = 1", grid="y")
    top.xaxis.set_major_locator(mdates.YearLocator(2))
    top.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    bottom = fig.add_axes((0.06, 0.13, 0.60, 0.30), sharex=top)
    bottom.fill_between(days, harvested, color=PALETTE["teal"], alpha=0.25, lw=0)
    bottom.plot(days, harvested, color=PALETTE["teal"], lw=1.6, label="losses harvested, to date")
    bottom.plot(days, carryforward, color=PALETTE["violet"], lw=1.6, label="loss carried forward, after each year")
    bottom.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    style_axes(bottom, ylabel="share of $5m", grid="y")
    bottom.legend(frameon=False, fontsize=8.5, loc="upper left")

    side = fig.add_axes((0.73, 0.13, 0.24, 0.69))
    names = list(wealth)
    finals = [wealth[name][-1] for name in names]
    y = np.arange(len(names))[::-1]
    side.barh(y, finals, color=[MANAGER_COLOURS.get(name, PALETTE["navy"]) for name in names], height=0.6)
    for yi, value in zip(y, finals, strict=True):
        side.text(value + 0.005, yi, f"{value:.3f}", va="center", fontsize=8.5, color=PALETTE["ink"])
    side.set_yticks(y, [textwrap.fill(name, 14) for name in names], fontsize=8.5)
    side.set_xlim(min(finals) * 0.97, max(finals) * 1.02)
    style_axes(side, title="After tax, on liquidation\n($1 invested)", grid="x")
    caption(fig, "Index: the cap-weighted market of the twelve industries, dividends reinvested. " + SOURCE)
    return fig


# ---------------------------------------------------------------------------- the holding period
def plot_holding_period(
    purchases: Sequence[date], calendar_days: Sequence[int], example: tuple[date, date, date]
) -> Figure:
    fig = new_figure(14.0, 6.6)
    bought, anniversary, first_long = example
    title_block(
        fig,
        "Long-term means after the anniversary, not after 365 days",
        "IRS Publication 550: shares bought on 5 February 2024 and sold on 5 February 2025 are short-term - "
        "366 days, because 2024 had a 29 February. Day 3 and Day 7 counted 365 and called them long-term.",
    )
    top = fig.add_axes((0.05, 0.60, 0.90, 0.20))
    start, end = x_of(bought) - 20, x_of(first_long) + 20
    top.plot([x_of(bought), x_of(first_long)], [0, 0], color=PALETTE["grid"], lw=6, solid_capstyle="butt")
    leap = date(2024, 2, 29)
    marks = [
        (bought, "bought\n5 Feb 2024", PALETTE["navy"]),
        (leap, "29 Feb 2024", PALETTE["muted"]),
        (anniversary, "sold 5 Feb 2025: 366 days,\nshort-term (365-day rule: long)", PALETTE["loss"]),
        (first_long, "6 Feb 2025:\nfirst long-term day", PALETTE["gain"]),
    ]
    for index, (day, text, colour) in enumerate(marks):
        top.plot(x_of(day), 0, "o", color=colour, ms=10, zorder=3)
        offset = 0.55 if index % 2 == 0 else -0.55
        top.text(x_of(day), offset, text, ha="center", va="center", fontsize=8.5, color=colour)
    top.set_xlim(start, end)
    top.set_ylim(-1.1, 1.1)
    top.axis("off")

    ax = fig.add_axes((0.05, 0.14, 0.90, 0.36))
    x = [x_of(day) for day in purchases]
    days = np.array(calendar_days)
    wrong = days > 366
    ax.scatter(np.array(x)[~wrong], days[~wrong], s=2, color=PALETTE["navy"], label="366 days: the rules agree")
    ax.scatter(
        np.array(x)[wrong], days[wrong], s=2, color=PALETTE["loss"], label="367 days: the 365-day count was a day early"
    )
    ax.set_ylim(365.4, 367.6)
    ax.set_yticks([366, 367])
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    share = float(wrong.mean())
    style_axes(
        ax,
        title=f"Days from purchase to the first long-term sale: one purchase date in {1 / share:.1f} "
        f"({share:.0%}) is a day later than the count",
        xlabel="purchase date",
        grid="y",
    )
    ax.legend(frameon=False, fontsize=8.5, loc="upper right", markerscale=5)
    caption(
        fig,
        "The holding period starts the day after purchase and includes the day of sale; a lot bought on 29 February "
        "has its anniversary on 28 February.",
    )
    return fig


# ---------------------------------------------------------------------------- the carryover
@dataclass(frozen=True)
class CarryoverCase:
    title: str
    realised: str  # what was realised, in words
    day7: tuple[float, float, float]  # (short carried, long carried, deduction's value)
    irs: tuple[float, float, float]


def plot_carryover(cases: Sequence[CarryoverCase]) -> Figure:
    fig = new_figure(14.0, 6.0)
    title_block(
        fig,
        "The capital loss carryover, as Schedule D computes it",
        "Day 7's ledger against the revisited one (which now agrees with Day 3's book of record on every random "
        "history tried). Short-term losses go first into the $3,000 deduction; what is left keeps its character.",
    )
    for index, case in enumerate(cases):
        ax = fig.add_axes((0.06 + index * 0.48, 0.17, 0.40, 0.56))
        labels = ["carried short-term", "carried long-term", "deduction saves"]
        x = np.arange(3)
        ax.bar(x - 0.19, case.day7, width=0.36, color=PALETTE["muted"], label="Day 7")
        ax.bar(x + 0.19, case.irs, width=0.36, color=PALETTE["navy"], label="revisited (Schedule D)")
        for xi, (old, new) in enumerate(zip(case.day7, case.irs, strict=True)):
            ax.text(xi - 0.19, old + 80, f"\\${old:,.0f}", ha="center", fontsize=8, color=PALETTE["muted"])
            ax.text(
                xi + 0.19, new + 80, f"\\${new:,.0f}", ha="center", fontsize=8, color=PALETTE["ink"], fontweight="bold"
            )
        ax.set_xticks(x, labels, fontsize=9)
        ax.set_ylim(0, max(*case.day7, *case.irs) * 1.22)
        ax.yaxis.set_major_formatter(lambda value, _: f"\\${value:,.0f}")
        style_axes(ax, title=case.title, grid="y")
        ax.text(0.0, -0.14, case.realised, transform=ax.transAxes, fontsize=8.5, color=PALETTE["muted"], va="top")
        if index == 0:
            ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    caption(
        fig,
        "The deduction offsets ordinary income, so it saves the 37% ordinary rate; the 3.8% net investment income "
        "tax is charged only on a positive net and a loss saves none of it.",
    )
    return fig


# ---------------------------------------------------------------------------- two solvers
def plot_solver_agreement(cases: Mapping[str, tuple[Sequence[float], Sequence[float]]]) -> Figure:
    fig = new_figure(14.0, 6.2)
    title_block(
        fig,
        "Two unrelated algorithms, one rebalance",
        "The same rebalances solved by Clarabel (interior point, the house solver) and SCS (first-order operator "
        "splitting): weight after the trades, asset by asset.",
    )
    for index, (name, (first, second)) in enumerate(cases.items()):
        ax = fig.add_axes((0.06 + index * 0.32, 0.17, 0.26, 0.56))
        a, b = np.array(first), np.array(second)
        low, high = min(a.min(), b.min()), max(a.max(), b.max())
        pad = (high - low) * 0.1
        ax.plot([low - pad, high + pad], [low - pad, high + pad], color=PALETTE["grid"], lw=1)
        ax.scatter(a, b, s=36, color=PALETTE["navy"], zorder=3)
        gap = float(np.abs(a - b).max()) * 1e4
        ax.set_xlim(low - pad, high + pad)
        ax.set_ylim(low - pad, high + pad)
        ax.xaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
        ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
        style_axes(ax, title=name, xlabel="Clarabel", ylabel="SCS" if index == 0 else None, grid="both")
        ax.text(
            0.04,
            0.94,
            f"largest gap {gap:.2f} bp",
            transform=ax.transAxes,
            fontsize=8.5,
            color=PALETTE["teal"],
            va="top",
        )
    caption(
        fig,
        "The demonstration account. SCS stops short of interior-point precision. Where a solve has discrete repair "
        "rounds, that noise can choose a different path: in the tax-blind rebalance SCS's trace purchases set off five "
        "wash-sale repairs Clarabel never needed - the reason Clarabel leads the solver chain.",
    )
    return fig
