"""Charts for the Day 3 revisit: the book of record held to the tax authorities and to its own invariants.

The functions take plain inputs, prepared in :mod:`meridian.tax_reference_gallery`
from the published examples and the engine, so any set of cases can be drawn.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch
from matplotlib.transforms import blended_transform_factory

from .style import PALETTE, caption, new_figure, style_axes, title_block, x_of


def _money(value: float, unit: str) -> str:
    """A signed amount with its unit in front of the digits, dollars escaped from mathtext."""
    sign = "\u2212" if value < 0 else ""
    digits = f"{abs(value):,.0f}" if abs(value) >= 1 or value == 0 else f"{abs(value):,.2f}"
    return sign + unit.replace("$", r"\$") + digits


def _usd(value: float) -> str:
    return _money(value, "$")


RULE_COLOURS = {
    "same day": PALETTE["violet"],
    "bed and breakfast": PALETTE["teal"],
    "section 104": PALETTE["navy"],
    "later acquisition": PALETTE["sky"],
}


# ---------------------------------------------------------------------------- scorecard
@dataclass(frozen=True)
class ScoreRow:
    authority: str  # "IRS" or "HMRC"
    case: str
    figure: str
    published: float
    difference: float  # computed less published, in the authority's unit (cents, pounds or shares)
    unit: str = ""  # "$", "£", or "" for a count of shares
    erratum: bool = False


def plot_scorecard(rows: Sequence[ScoreRow]) -> Figure:
    count = len(rows)
    agreeing = sum(1 for row in rows if abs(row.difference) <= (0.5 if row.authority == "IRS" else 1.0))
    fig = new_figure(14.0, 0.27 * count + 2.6)
    title_block(
        fig,
        f"{agreeing} of {count} published figures reproduced, run exactly as the tax authorities print them",
        "Every number the IRS (Publication 550) and HMRC (CG51560, CG51590, HS284) state in their own worked examples, "
        "against the number the engine computes from the same trades. Dots on the line agree exactly.",
    )
    top, bottom = 1 - 1.45 / fig.get_figheight(), 0.95 / fig.get_figheight()
    ax = fig.add_axes((0.43, bottom, 0.38, top - bottom))
    y = np.arange(count)[::-1]
    ax.axvspan(-0.5, 0.5, color=PALETTE["band"], zorder=0)
    ax.axvline(0, color=PALETTE["gain"], lw=1.0)
    previous = None
    for position, row in zip(y, rows, strict=True):
        colour = PALETTE["accent"] if row.erratum else (PALETTE["navy"] if row.authority == "IRS" else PALETTE["teal"])
        ax.plot(row.difference, position, "o", color=colour, ms=7 if row.erratum else 5.5, zorder=3)
        if row.case != previous:
            ax.axhline(position + 0.5, color=PALETTE["grid"], lw=0.8)
            ax.text(
                0.012,
                position,
                row.case,
                transform=blended_transform_factory(fig.transFigure, ax.transData),
                fontsize=8.5,
                fontweight="bold",
                color=PALETTE["ink"],
                va="center",
            )
            previous = row.case
        ax.text(-1.62, position, row.figure, ha="right", va="center", fontsize=7.6, color=PALETTE["ink"])
        shown = _money(row.published, row.unit) + ("" if row.unit else " shares")
        ax.text(1.62, position, shown, ha="left", va="center", fontsize=7.6, color=PALETTE["muted"])
        if row.erratum:
            ax.annotate(
                "HMRC prints £4,236;\nits own 6,160 − 1,925\nis £4,235",
                xy=(row.difference, position),
                xytext=(0.6, position + 2.6),
                fontsize=8,
                color=PALETTE["accent"],
                fontweight="bold",
                arrowprops={"arrowstyle": "->", "color": PALETTE["accent"]},
            )
    ax.set_xlim(-1.5, 1.5)
    ax.set_ylim(-0.7, count - 0.3)
    ax.set_yticks([])
    ax.set_xticks([-1, -0.5, 0, 0.5, 1])
    style_axes(
        ax, xlabel="computed less published, in the authority's unit (cents for the IRS, pounds for HMRC)", grid="x"
    )
    ax.spines["left"].set_visible(False)
    ax.text(1.62, count - 0.2, "published", fontsize=8, color=PALETTE["muted"], va="bottom", fontweight="bold")
    handles = [
        Line2D([], [], marker="o", ls="", color=PALETTE["navy"], label="IRS, to the cent"),
        Line2D([], [], marker="o", ls="", color=PALETTE["teal"], label="HMRC, to the pound it rounds to"),
        Line2D([], [], marker="o", ls="", color=PALETTE["accent"], label="a published arithmetic slip"),
        Patch(color=PALETTE["band"], label="within half a unit"),
    ]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.03), ncol=4, frameon=False, fontsize=8)
    caption(
        fig,
        "Sources: IRS Publication 550 (2025), Wash Sales; HMRC Capital Gains Manual CG51560, CG51590; "
        "HMRC Helpsheet HS284. Engine: meridian.accounting, unchanged for the examples.",
    )
    return fig


# ---------------------------------------------------------------------------- wash sale timelines
@dataclass(frozen=True)
class Purchase:
    day: date
    quantity: int
    added: float  # disallowed loss added to these shares' basis; 0 if they replace nothing
    replaced: int  # how many of them are replacement shares


@dataclass(frozen=True)
class WashPanel:
    title: str
    sale_day: date
    sold: int
    loss: float  # loss on the shares sold at a loss
    disallowed: float
    purchases: tuple[Purchase, ...]
    sold_from: tuple[date, ...]  # when the shares sold were bought, if outside the window
    lesson: str


def plot_wash_timelines(panels: Sequence[WashPanel]) -> Figure:
    fig = new_figure(14.0, 3.0 * len(panels) + 1.6)
    title_block(
        fig,
        "The wash sale rule on the IRS's own examples: where each disallowed dollar goes",
        "Each panel is one example from Publication 550, run through the engine. The band is the 61-day window; a "
        "loss is disallowed for every share bought inside it, earliest first, and joins those shares' basis.",
    )
    height = (1 - 1.5 / fig.get_figheight()) / len(panels)
    for index, panel in enumerate(panels):
        ax = fig.add_axes((0.05, 1 - 1.25 / fig.get_figheight() - (index + 1) * height + 0.035, 0.66, height - 0.075))
        start, end = panel.sale_day - timedelta(days=45), panel.sale_day + timedelta(days=45)
        ax.axvspan(
            x_of(panel.sale_day - timedelta(days=30)),
            x_of(panel.sale_day + timedelta(days=30)),
            color=PALETTE["band"],
            zorder=0,
        )
        ax.axvline(x_of(panel.sale_day), color=PALETTE["loss"], lw=1.2)
        ax.plot([x_of(panel.sale_day)], [0], marker="v", ms=13, color=PALETTE["loss"], zorder=4)
        ax.text(
            x_of(panel.sale_day),
            -0.62,
            f"sold {panel.sold}\nloss {_usd(panel.loss)}",
            ha="center",
            va="top",
            fontsize=8.5,
            color=PALETTE["loss"],
            fontweight="bold",
        )
        label_x = x_of(start)
        for purchase in panel.purchases:
            if not start <= purchase.day <= end:
                continue
            label_x = max(x_of(purchase.day), label_x + 9)
            matched = purchase.replaced > 0
            colour = PALETTE["teal"] if matched else PALETTE["slate"]
            ax.plot(
                [x_of(purchase.day)],
                [0],
                "o",
                ms=6 + purchase.quantity / 12,
                color=colour,
                alpha=0.95 if matched else 0.45,
                zorder=3,
            )
            label = f"{purchase.quantity} bought"
            if matched:
                label += f"\n+{_usd(purchase.added)} basis"
            if label_x != x_of(purchase.day):
                ax.plot([x_of(purchase.day), label_x], [0.18, 0.5], color=PALETTE["grid"], lw=0.8, zorder=1)
            ax.text(
                label_x,
                0.55,
                label,
                ha="center",
                va="bottom",
                fontsize=8,
                color=colour if matched else PALETTE["muted"],
                fontweight="bold" if matched else "normal",
            )
        earlier = [day for day in panel.sold_from if day < start]
        if earlier:
            when = ", ".join(f"{day:%d %b %Y}" for day in earlier)
            ax.text(
                x_of(start) + 1,
                -0.62,
                "\u2190 shares sold were bought\n" + textwrap.fill(when, 30),
                fontsize=7.5,
                color=PALETTE["muted"],
                va="top",
            )
        ax.set_xlim(x_of(start), x_of(end))
        ax.set_ylim(-1.4, 1.5)
        ax.set_yticks([])
        ax.xaxis_date()
        style_axes(ax, grid=None)
        ax.spines["left"].set_visible(False)
        ax.set_title(panel.title, fontsize=10)
        share = panel.disallowed / panel.loss if panel.loss else 0.0
        fig.text(
            0.74,
            ax.get_position().y1 - 0.01,
            f"{_usd(panel.disallowed)} of {_usd(panel.loss)} disallowed",
            fontsize=11,
            fontweight="bold",
            color=PALETTE["ink"],
            va="top",
        )
        bar = fig.add_axes((0.74, ax.get_position().y1 - 0.065, 0.22, 0.018))
        bar.barh(0, share, color=PALETTE["teal"])
        bar.barh(0, 1 - share, left=share, color=PALETTE["grid"])
        bar.set_xlim(0, 1)
        bar.axis("off")
        fig.text(
            0.74,
            ax.get_position().y1 - 0.085,
            textwrap.fill(panel.lesson, 48),
            fontsize=8.5,
            color=PALETTE["muted"],
            va="top",
        )
    caption(
        fig,
        "Source: IRS Publication 550 (2025), Wash Sales, and More or less stock bought than sold. Every "
        "figure shown is the engine's, and each agrees with the publication to the cent.",
    )
    return fig


# ---------------------------------------------------------------------------- UK identification
@dataclass(frozen=True)
class MatchBar:
    label: str
    sold: float
    by_rule: dict[str, float]
    note: str = ""


def plot_uk_matching(bars: Sequence[MatchBar]) -> Figure:
    fig = new_figure(14.0, 0.62 * len(bars) + 2.8)
    title_block(
        fig,
        "Which shares a UK disposal is matched with, on HMRC's own examples",
        "TCGA 1992 s105-106A: shares bought the same day first, then within the next 30 days, then the section 104 "
        "pool - and only then, if the pool runs out, later purchases. Each bar is one disposal HMRC publishes.",
    )
    top, bottom = 1 - 1.35 / fig.get_figheight(), 0.75 / fig.get_figheight()
    ax = fig.add_axes((0.25, bottom, 0.55, top - bottom))
    y = np.arange(len(bars))[::-1]
    for position, bar in zip(y, bars, strict=True):
        left = 0.0
        for rule, colour in RULE_COLOURS.items():
            quantity = bar.by_rule.get(rule, 0.0)
            if not quantity:
                continue
            width = quantity / bar.sold
            ax.barh(position, width, left=left, color=colour, height=0.62)
            if width > 0.07:
                ax.text(
                    left + width / 2,
                    position,
                    f"{quantity:,.0f}",
                    ha="center",
                    va="center",
                    fontsize=8.5,
                    color="white",
                    fontweight="bold",
                )
            left += width
        ax.text(-0.02, position, bar.label, ha="right", va="center", fontsize=8.8, color=PALETTE["ink"])
        ax.text(
            1.02,
            position,
            f"{bar.sold:,.0f} sold" + (f"\n{bar.note}" if bar.note else ""),
            ha="left",
            va="center",
            fontsize=8,
            color=PALETTE["accent"] if bar.note else PALETTE["muted"],
            fontweight="bold" if bar.note else "normal",
        )
    ax.set_xlim(0, 1)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    style_axes(ax, xlabel="share of the disposal matched under each rule", grid="x")
    ax.spines["left"].set_visible(False)
    handles = [Patch(color=colour, label=rule) for rule, colour in RULE_COLOURS.items()]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=4, frameon=False, fontsize=8.5)
    caption(
        fig,
        "Sources: HMRC CG51560 (identification), CG51590 (pooling examples), HS284 (2025). Rights taken up "
        "are not acquisitions (s127): they join the pool and are never matched under the 30-day rule.",
    )
    return fig


# ---------------------------------------------------------------------------- the section 104 pool
@dataclass(frozen=True)
class PoolStep:
    day: date
    quantity: float
    cost: float
    event: str  # "acquire", "rights" or "dispose"
    moved: float  # shares in or out


@dataclass(frozen=True)
class PoolPanel:
    title: str
    steps: tuple[PoolStep, ...]
    note: str


def plot_pools(panels: Sequence[PoolPanel]) -> Figure:
    fig = new_figure(14.0, 4.1 * len(panels) + 1.4)
    title_block(
        fig,
        "The section 104 pool: one holding, one average cost",
        "Every UK share bought joins one pool at its cost; a disposal takes the pool's average. Rights taken up "
        "join at what was paid for them. Bars are the shares in the pool; the line is its average cost per share.",
    )
    height = (1 - 1.4 / fig.get_figheight()) / len(panels)
    colours = {"acquire": PALETTE["navy"], "rights": PALETTE["violet"], "dispose": PALETTE["loss"]}
    for index, panel in enumerate(panels):
        ax = fig.add_axes((0.06, 1 - 1.2 / fig.get_figheight() - (index + 1) * height + 0.05, 0.62, height - 0.1))
        positions = np.arange(len(panel.steps))
        quantities = [step.quantity for step in panel.steps]
        ax.bar(positions, quantities, color=[colours[step.event] for step in panel.steps], width=0.6, alpha=0.9)
        for x, step in zip(positions, panel.steps, strict=True):
            sign = "−" if step.event == "dispose" else "+"
            ax.text(
                x,
                step.quantity,
                f"{sign}{step.moved:,.0f}\n{step.quantity:,.0f}",
                ha="center",
                va="bottom",
                fontsize=8,
                color=PALETTE["ink"],
            )
        labels = [f"{step.event}\n{step.day:%d %b %Y}" for step in panel.steps]
        ax.set_xticks(positions, labels, fontsize=8)
        ax.set_ylim(0, max(quantities) * 1.75)
        style_axes(ax, ylabel="shares in the pool", grid="y")
        ax.set_title(panel.title, fontsize=10)
        twin = ax.twinx()
        average = [step.cost / step.quantity if step.quantity else np.nan for step in panel.steps]
        twin.plot(positions, average, "-o", color=PALETTE["accent"], lw=2, ms=5)
        for x, value in zip(positions, average, strict=True):
            twin.text(x + 0.12, value, f"£{value:.3f}", fontsize=7.5, color=PALETTE["accent"], va="bottom")
        highest = max(value for value in average if value == value)
        twin.set_ylim(-highest * 1.2, highest * 1.25)  # the line rides above the bars and their labels
        twin.set_yticks([tick for tick in twin.get_yticks() if 0 <= tick <= highest * 1.25])
        twin.set_ylabel("average cost per share (£)", color=PALETTE["accent"], fontsize=9)
        twin.grid(visible=False)
        for spine in ("top",):
            twin.spines[spine].set_visible(False)
        fig.text(0.74, ax.get_position().y1, textwrap.fill(panel.note, 46), fontsize=9, color=PALETTE["ink"], va="top")
    handles: list[Patch | Line2D] = [Patch(color=colour, label=event) for event, colour in colours.items()]
    handles.append(Line2D([], [], color=PALETTE["accent"], marker="o", label="average cost"))
    fig.legend(handles=handles, loc="lower right", ncol=4, frameon=False, fontsize=8.5, bbox_to_anchor=(0.98, 0.0))
    caption(
        fig,
        "Source: HMRC Capital Gains Manual CG51590, Examples 2 and 4, run through meridian.accounting."
        "uk_matching. The pool after each disposal agrees with HMRC to the pound.",
    )
    return fig


# ---------------------------------------------------------------------------- invariants
@dataclass(frozen=True)
class LotBox:
    name: str
    price: float
    sold: bool


def plot_invariants(
    lots: Sequence[LotBox],
    loss: float,
    before: str,
    after: str,
    disallowed: Sequence[float],
    carried: Sequence[float],
    methods: Sequence[str],
    examples: int,
) -> Figure:
    fig = new_figure(14.0, 7.2)
    title_block(
        fig,
        "Property-testing the book: a disallowed loss that went nowhere",
        f"Hypothesis writes random histories and checks what must always hold; here {examples:,} of them. One check "
        "failed before the fix: shares sold "
        "together could replace each other, so a wash-sale loss was added to a lot already gone.",
    )
    for column, (heading, target, colour) in enumerate(
        (
            (f"Before: the loss lands on {before}, sold in the same sale", before, PALETTE["loss"]),
            (f"After: it lands on {after}, the shares still held", after, PALETTE["gain"]),
        )
    ):
        ax = fig.add_axes((0.03 + column * 0.29, 0.14, 0.27, 0.66))
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis("off")
        ax.set_title(textwrap.fill(heading, 38), fontsize=9.5, loc="left", color=colour)
        positions = {}
        for index, lot in enumerate(lots):
            x = 0.6 + index * 3.2
            face = PALETTE["band"] if lot.sold else "white"
            edge = PALETTE["loss"] if lot.sold and lot.price > min(item.price for item in lots) else PALETTE["slate"]
            ax.add_patch(
                FancyBboxPatch((x, 5.6), 2.5, 2.4, boxstyle="round,pad=0.08", facecolor=face, edgecolor=edge, lw=1.4)
            )
            ax.text(x + 1.25, 7.3, lot.name, ha="center", fontsize=11, fontweight="bold", color=PALETTE["ink"])
            ax.text(x + 1.25, 6.6, f"10 @ {_usd(lot.price)}", ha="center", fontsize=9, color=PALETTE["ink"])
            ax.text(
                x + 1.25,
                6.0,
                "sold" if lot.sold else "still held",
                ha="center",
                fontsize=8.5,
                color=PALETTE["loss"] if lot.sold else PALETTE["gain"],
            )
            positions[lot.name] = x + 1.25
        source = next(lot.name for lot in lots if lot.sold and lot.price == max(item.price for item in lots))
        ax.annotate(
            "",
            xy=(positions[target], 5.4),
            xytext=(positions[source], 5.4),
            arrowprops={"arrowstyle": "->", "color": colour, "lw": 2, "connectionstyle": "arc3,rad=0.5"},
        )
        ax.text(5, 2.6, f"{_usd(loss)} loss disallowed", ha="center", fontsize=10, color=colour, fontweight="bold")
        ax.text(
            5,
            1.6,
            "carried in an open lot: " + (_usd(0) + " - lost" if target == before else _usd(loss)),
            ha="center",
            fontsize=9.5,
            color=PALETTE["ink"],
        )
    ax = fig.add_axes((0.67, 0.16, 0.30, 0.58))
    palette = {"fifo": PALETTE["navy"], "lifo": PALETTE["teal"], "hifo": PALETTE["violet"]}
    for method in sorted(set(methods)):
        xs = [d for d, m in zip(disallowed, methods, strict=True) if m == method]
        ys = [c for c, m in zip(carried, methods, strict=True) if m == method]
        ax.scatter(xs, ys, s=16, alpha=0.7, color=palette.get(method, PALETTE["slate"]), label=method.upper())
    top = max([*disallowed, 1.0]) * 1.05
    ax.plot([0, top], [0, top], color=PALETTE["gain"], lw=1, zorder=0)
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    style_axes(
        ax,
        title="After the fix: every disallowed dollar is carried",
        xlabel=r"loss disallowed (\$)",
        ylabel=r"carried in replacement basis (\$)",
        grid="both",
    )
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    caption(
        fig,
        "Invariants checked on every history: trial balance zero; investment sub-ledger equal to the open lots "
        "at historical cost; quantities; disallowed losses equal to the basis carried. Random books, two "
        "currencies, three relief methods.",
    )
    return fig


# ---------------------------------------------------------------------------- the Treasury day count
def plot_treasury_day_count(
    days: Sequence[date], thirty: Sequence[float], actual: Sequence[float], marked: date, face: float, name: str
) -> Figure:
    fig = new_figure(14.0, 7.4)
    title_block(
        fig,
        f"{name}: accrued interest on the convention Treasuries use",
        "The demonstration book carried the Treasury on 30/360, a corporate-bond convention. US Treasuries accrue "
        "actual/actual (ICMA): the coupon is spread over the real days in the period, so February is short.",
    )
    ax = fig.add_axes((0.07, 0.42, 0.88, 0.42))
    ax.plot(days, actual, color=PALETTE["navy"], lw=2.2, label="actual/actual ICMA (now)")
    ax.plot(days, thirty, color=PALETTE["slate"], lw=1.4, ls="--", label="30/360 (before)")
    index = list(days).index(marked)
    ax.axvline(x_of(marked), color=PALETTE["accent"], lw=1)
    ax.annotate(
        f"settlement {marked:%d %b %Y}: \\${actual[index]:,.2f} against \\${thirty[index]:,.2f}",
        xy=(x_of(marked), actual[index]),
        xytext=(x_of(marked) + 12, actual[index] * 0.55),
        fontsize=9,
        color=PALETTE["accent"],
        fontweight="bold",
        arrowprops={"arrowstyle": "->", "color": PALETTE["accent"]},
    )
    style_axes(ax, ylabel=f"accrued on {_usd(face)} face", grid="y")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:,.0f}")
    low = fig.add_axes((0.07, 0.1, 0.88, 0.22), sharex=ax)
    difference = [a - t for a, t in zip(actual, thirty, strict=True)]
    low.fill_between(days, difference, 0, color=PALETTE["teal"], alpha=0.35, lw=0)
    low.plot(days, difference, color=PALETTE["teal"], lw=1.4)
    low.axhline(0, color=PALETTE["muted"], lw=0.8)
    style_axes(low, ylabel=r"ACT/ACT less 30/360 (\$)", grid="y")
    low.xaxis_date()
    caption(
        fig,
        "Coupon 2.875%, paid 15 May and 15 November. The two conventions agree on coupon dates and differ "
        "in between; the gap peaks where 30/360's thirty-day months part from the calendar.",
    )
    return fig
