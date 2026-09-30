"""Charts for the rates engine: validation against QuantLib, curves from instruments, and 36 years of history.

Every function here draws what it is given. The numbers are computed in
``meridian.rates_gallery`` from the analytics, the packaged Treasury and Federal
Reserve data, and QuantLib, so a chart cannot drift from the code it describes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import cast

import matplotlib.dates as mdates
import numpy as np
from matplotlib import colors as mcolors
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from mpl_toolkits.mplot3d import Axes3D

from .style import PALETTE, caption, new_figure, style_axes, title_block, x_of

AREA_COLOURS = {
    "calendars": PALETTE["navy"],
    "day counts": PALETTE["teal"],
    "bonds": PALETTE["violet"],
    "gilts": PALETTE["sky"],
    "curves": PALETTE["slate"],
}
METHOD_COLOURS = {
    "linear": PALETTE["slate"],
    "log_linear": PALETTE["navy"],
    "monotone_cubic": PALETTE["violet"],
    "monotone_convex": PALETTE["teal"],
}
METHOD_NAMES = {
    "linear": "Linear on zero rates",
    "log_linear": "Log-linear discount factors (flat forwards)",
    "monotone_cubic": "Monotone cubic on zero rates",
    "monotone_convex": "Monotone convex (Hagan-West)",
}
EXACT = 1e-17  # where an exact agreement is drawn on a log scale


# ---------------------------------------------------------------------------- validation
@dataclass(frozen=True)
class CheckRow:
    area: str
    name: str
    cases: int
    max_error: float
    tolerance: float
    explained: int


def plot_reconciliation(rows: Sequence[CheckRow], variant_gap_bp: float) -> Figure:
    """Every comparison with QuantLib: the largest difference found, against its tolerance."""
    fig = new_figure(13.5, 11.0)
    title_block(
        fig,
        f"Meridian against QuantLib: {len(rows)} checks, none failed",
        "The largest difference found in each comparison, on a log scale. A dot at the left edge is exact agreement; "
        "the red tick is the tolerance the test enforces.",
    )
    ax = fig.add_axes((0.30, 0.13, 0.52, 0.74))
    positions = np.arange(len(rows))[::-1]
    floor = math.log10(EXACT)
    for y, row in zip(positions, rows, strict=True):
        colour = AREA_COLOURS[row.area]
        if row.max_error == 0:
            ax.scatter([floor + 0.12], [y], s=46, color=colour, zorder=3)
            ax.text(floor + 0.35, y, "exact", va="center", fontsize=7.5, color=colour, fontweight="bold")
        else:
            ax.barh(y, math.log10(row.max_error) - floor, left=floor, height=0.62, color=colour, alpha=0.9)
            ax.text(
                math.log10(row.max_error) + 0.1,
                y,
                f"{row.max_error:.0e}",
                va="center",
                fontsize=7,
                color=PALETTE["muted"],
            )
        if row.tolerance > 0:
            ax.plot([math.log10(row.tolerance)] * 2, [y - 0.38, y + 0.38], color=PALETTE["loss"], lw=1.6)
    ax.set_yticks(positions, [row.name for row in rows], fontsize=8)
    for label, row in zip(ax.get_yticklabels(), rows, strict=True):
        label.set_color(AREA_COLOURS[row.area])
    ax.set_xlim(floor, -6)
    ticks = list(range(-17, -5))
    ax.set_xticks(ticks, [f"1e{tick}" for tick in ticks], fontsize=7.5)
    style_axes(ax, xlabel="largest absolute difference (years, prices per 100, discount factors)", grid="x")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    start = 0
    for area in AREA_COLOURS:
        count = sum(1 for row in rows if row.area == area)
        if not count:
            continue
        if start:
            ax.axhline(positions[start] + 0.5, color=PALETTE["muted"], lw=0.8)
        start += count

    side = fig.add_axes((0.83, 0.13, 0.15, 0.74), sharey=ax)
    side.set_xlim(0, 1)
    side.axis("off")
    side.text(0.02, positions[0] + 1.0, "cases", fontsize=8, color=PALETTE["muted"], fontweight="bold")
    side.text(0.45, positions[0] + 1.0, "explained\nbreaks", fontsize=8, color=PALETTE["muted"], fontweight="bold")
    for y, row in zip(positions, rows, strict=True):
        side.text(0.02, y, f"{row.cases:,}", va="center", fontsize=8, color=PALETTE["ink"])
        if row.explained:
            side.text(0.45, y, f"{row.explained}", va="center", fontsize=8, color=PALETTE["accent"], fontweight="bold")

    legend: list[Patch | Line2D] = [Patch(color=colour, label=area) for area, colour in AREA_COLOURS.items()]
    legend.append(Line2D([], [], color=PALETTE["loss"], lw=1.6, label="tolerance"))
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.35, 1.0), ncol=6, frameon=False, fontsize=8.5)
    caption(
        fig,
        "Calendars: every weekday 1990-2060 (TARGET and Xetra from 1999). Day counts: generated date pairs, month ends "
        "oversampled. Bonds: generated ACT/ACT ICMA and 30/360 bonds priced at a yield.\nGilts: every settlement day "
        "through two ex-dividend periods. Separately, QuantLib's blended convex-monotone curve sits within "
        f"{variant_gap_bp:.1f} bp of pure Hagan-West in forwards: a variant of the method, not a break.",
    )
    return fig


@dataclass(frozen=True)
class BreakSet:
    calendar: str
    before: tuple[date, ...]
    after: tuple[tuple[date, str], ...]  # (day, reason label)


def plot_calendar_breaks(sets: Sequence[BreakSet], reason_colours: Mapping[str, str]) -> Figure:
    """Every weekday on which Meridian and QuantLib disagreed, before and after the calendars learnt history."""
    fig = new_figure(14.0, 8.4)
    before_total = sum(len(item.before) for item in sets)
    after_total = sum(len(item.after) for item in sets)
    title_block(
        fig,
        f"What QuantLib found in the calendars: {before_total} disagreements, {after_total} left - all explained",
        "Each mark is a weekday, 1990-2060, on which one calendar trades and the other does not. Above each line: "
        "version 1.0.0. Below: now, coloured by the documented reason the two still differ.",
    )
    ax = fig.add_axes((0.08, 0.18, 0.70, 0.68))
    for row, item in enumerate(sets):
        base = len(sets) - 1 - row
        ax.axhline(base, color=PALETTE["grid"], lw=0.8, zorder=0)
        if item.before:
            ax.scatter([x_of(day) for day in item.before], [base + 0.22] * len(item.before), marker="|", s=90,
                       color=PALETTE["loss"], alpha=0.55, lw=1.2)  # fmt: skip
        for label, colour in reason_colours.items():
            days = [day for day, reason in item.after if reason == label]
            if days:
                ax.scatter(
                    [x_of(day) for day in days], [base - 0.22] * len(days), marker="|", s=90, color=colour, lw=1.4
                )
    ax.set_yticks(range(len(sets)), [item.calendar for item in reversed(sets)], fontsize=10, fontweight="bold")
    ax.set_ylim(-0.7, len(sets) - 0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator(10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(x_of(date(1989, 6, 1)), x_of(date(2061, 6, 1)))
    ax.axvline(x_of(date(2026, 10, 1)), color=PALETTE["muted"], lw=0.8, ls="--")
    ax.text(x_of(date(2026, 10, 1)), len(sets) - 0.35, " today", fontsize=8, color=PALETTE["muted"], va="bottom")
    style_axes(ax, grid="x")
    ax.tick_params(axis="y", length=0)

    counts = fig.add_axes((0.80, 0.18, 0.18, 0.68), sharey=ax)
    for row, item in enumerate(sets):
        base = len(sets) - 1 - row
        counts.barh(base + 0.18, len(item.before), height=0.32, color=PALETTE["loss"], alpha=0.55)
        counts.barh(base - 0.18, len(item.after), height=0.32, color=PALETTE["teal"])
        counts.text(
            len(item.before) + 3, base + 0.18, str(len(item.before)), va="center", fontsize=8, color=PALETTE["loss"]
        )
        counts.text(
            len(item.after) + 3, base - 0.18, str(len(item.after)), va="center", fontsize=8, color=PALETTE["teal"]
        )
    style_axes(counts, title="disagreements", grid="x")
    counts.tick_params(axis="y", labelleft=False, length=0)
    counts.set_xlim(0, max(len(item.before) for item in sets) * 1.25)

    handles = [Line2D([], [], color=PALETTE["loss"], marker="|", ls="", markersize=12, mew=1.5, alpha=0.6,
                      label="v1.0.0 (fixed since)")]  # fmt: skip
    handles += [
        Line2D([], [], color=c, marker="|", ls="", markersize=12, mew=1.5, label=label)
        for label, c in reason_colours.items()
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=3, frameon=False, fontsize=8.5)
    caption(
        fig,
        "Fixed: rules applied before they existed (Martin Luther King Jr. Day before 1998, TARGET's Easter before "
        "2000, "
        "Japan's Happy Monday reforms), and closures no rule predicts (9/11, Hurricane Sandy, state funerals, "
        "jubilees).",
    )
    return fig


def plot_equinox_arbiter(
    years: Sequence[int],
    march_hours: Sequence[float],
    september_hours: Sequence[float],
    march_disputed: Sequence[bool],
    september_disputed: Sequence[bool],
) -> Figure:
    """When the equinox falls in Tokyo, and the years QuantLib's formula puts the holiday on the wrong day."""
    fig = new_figure(13.0, 6.8)
    title_block(
        fig,
        "When two references disagree, the astronomy decides",
        "The time of day in Tokyo at which the Sun crosses the equator (Meeus, chapter 27). Japan's holiday is that "
        "calendar day. Circled: years in which QuantLib's formula names a different day.",
    )
    for index, (label, hours, disputed) in enumerate(
        (
            ("Vernal equinox (March)", march_hours, march_disputed),
            ("Autumnal equinox (September)", september_hours, september_disputed),
        )
    ):
        ax = fig.add_axes((0.06 + index * 0.48, 0.14, 0.42, 0.68))
        ax.axvspan(years[0] - 1, 1999.5, color=PALETTE["band"], zorder=0)
        ax.text(1994.75, 24.6, "before 2000", ha="center", fontsize=8, color=PALETTE["muted"])
        ax.scatter(years, hours, s=18, color=PALETTE["navy"], zorder=3)
        flagged = [(year, hour) for year, hour, bad in zip(years, hours, disputed, strict=True) if bad]
        if flagged:
            flagged_years, flagged_hours = zip(*flagged, strict=True)
            ax.scatter(
                flagged_years, flagged_hours, s=120, facecolors="none", edgecolors=PALETTE["accent"], lw=1.8, zorder=4
            )
        ax.set_ylim(0, 24)
        ax.set_yticks([0, 6, 12, 18, 24], ["00:00", "06:00", "12:00", "18:00", "24:00"])
        style_axes(ax, title=label, xlabel="year", ylabel="time of the equinox, Tokyo (JST)" if index == 0 else None)
        count = sum(disputed)
        ax.text(0.99, 1.03, f"{count} year{'s' if count != 1 else ''} disputed", transform=ax.transAxes, ha="right",
                fontsize=9, color=PALETTE["accent"], fontweight="bold")  # fmt: skip
    caption(
        fig,
        "The equinox comes about six hours later each year and resets with each leap day, so the dots fall in four "
        "diagonal lines. Every disputed year is before 2000, at any hour: QuantLib's constant for 1980-1999 is off by "
        "about a day. In 1990 the equinox came at 06:19 on 21 March in Tokyo, the day Japan observed.",
    )
    return fig


# ---------------------------------------------------------------------------- curves from instruments
def plot_sofr_curve(
    tenors: Sequence[str],
    pillar_times: Sequence[float],
    quotes: Sequence[float],
    zero_times: Sequence[float],
    zeros_log_linear: Sequence[float],
    forwards_log_linear: Sequence[float],
    forwards_convex: Sequence[float],
    repricing_bp: Sequence[float],
    valuation: date,
) -> Figure:
    fig = new_figure(13.5, 8.6)
    title_block(
        fig,
        f"A USD SOFR curve from twenty swaps, {valuation:%d %B %Y}",
        "Each quote is an overnight index swap with its real dates: spot T+2, annual periods rolled modified following "
        "on the SIFMA calendar, ACT/360. The bootstrap reprices every one of them.",
    )
    ax = fig.add_axes((0.07, 0.36, 0.90, 0.50))
    ax.step(zero_times, np.array(forwards_log_linear) * 100, where="post", color=PALETTE["navy"], lw=1.1, alpha=0.55,
            label="instantaneous forward, log-linear (a staircase)")  # fmt: skip
    ax.plot(
        zero_times,
        np.array(forwards_convex) * 100,
        color=PALETTE["teal"],
        lw=2.2,
        label="instantaneous forward, monotone convex",
    )
    ax.plot(
        zero_times, np.array(zeros_log_linear) * 100, color=PALETTE["violet"], lw=2.2, label="zero rate (continuous)"
    )
    ax.scatter(
        pillar_times, np.array(quotes) * 100, color=PALETTE["accent"], s=34, zorder=5, label="OIS quote (par, ACT/360)"
    )
    for time, quote, tenor in zip(pillar_times, quotes, tenors, strict=True):
        if tenor in {"1W", "6M", "2Y", "5Y", "10Y", "20Y", "30Y", "50Y"}:
            ax.annotate(
                tenor,
                (time, quote * 100),
                textcoords="offset points",
                xytext=(0, 8),
                ha="center",
                fontsize=7.5,
                color=PALETTE["muted"],
            )
    style_axes(ax, ylabel="per cent", xlabel="maturity, years", grid="both")
    ax.set_xlim(0, 51)
    ax.legend(loc="lower right", frameon=False, fontsize=8.5)

    low = fig.add_axes((0.07, 0.08, 0.90, 0.19))
    errors = np.abs(np.asarray(repricing_bp, dtype=float))
    for index, error in enumerate(errors):
        if error < 1e-14:  # exact to the last bit
            low.scatter([index], [1.6e-14], color=PALETTE["teal"], s=28, zorder=3)
            low.text(index, 3e-14, "exact", ha="center", fontsize=7, color=PALETTE["teal"], fontweight="bold")
        else:
            low.bar(index, error, color=PALETTE["teal"], width=0.62)
    low.set_yscale("log")
    low.set_ylim(1e-14, 1e-8)
    low.set_xticks(range(len(tenors)), tenors, fontsize=8)
    style_axes(
        low, title="Repricing error of each instrument on the finished curve (basis points, log scale)", grid="y"
    )
    low.axhline(1e-10, color=PALETTE["loss"], lw=1.0, ls="--")
    low.text(
        len(tenors) - 0.5,
        1.4e-10,
        "one ten-billionth of a basis point",
        ha="right",
        fontsize=7.5,
        color=PALETTE["loss"],
    )
    caption(
        fig,
        "Illustrative quotes: the US Treasury par curve of the day plus typical SOFR swap spreads (cleared swap "
        "quotes are "
        "not free). The same strip built by QuantLib's PiecewiseLogLinearDiscount agrees to 2e-13 in discount factors.",
    )
    return fig


def plot_interpolation_forwards(
    times: Sequence[float],
    forwards: Mapping[str, Sequence[float]],
    pillar_times: Sequence[float],
    quantlib_convex: Sequence[float] | None = None,
) -> Figure:
    fig = new_figure(13.5, 8.8)
    title_block(
        fig,
        "Four interpolators, one set of quotes: what each says about the forward curve",
        "Every panel reprices the same twenty SOFR swaps exactly. They differ only in what they assume between the "
        "pillars, and the instantaneous forward is where the assumption shows.",
    )
    grid = fig.add_gridspec(2, 2, left=0.06, right=0.98, top=0.86, bottom=0.09, hspace=0.35, wspace=0.12)
    everything = np.concatenate([np.asarray(values) for values in forwards.values()]) * 100
    low, high = float(everything.min()) - 0.15, float(everything.max()) + 0.15
    for index, (method, values) in enumerate(forwards.items()):
        ax = fig.add_subplot(grid[index // 2, index % 2])
        for pillar in pillar_times:
            ax.axvline(pillar, color=PALETTE["grid"], lw=0.6, zorder=0)
        colour = METHOD_COLOURS[method]
        if method == "log_linear":
            ax.step(times, np.asarray(values) * 100, where="post", color=colour, lw=1.8)
        else:
            ax.plot(times, np.asarray(values) * 100, color=colour, lw=2.0)
        if method == "monotone_convex" and quantlib_convex is not None:
            ax.plot(times, np.asarray(quantlib_convex) * 100, color=PALETTE["accent"], lw=1.0, ls="--",
                    label="QuantLib ConvexMonotone (its default blend)")  # fmt: skip
            ax.legend(loc="lower right", frameon=False, fontsize=7.5)
        ax.set_ylim(low, high)
        ax.set_xlim(0, 50)
        style_axes(ax, title=METHOD_NAMES[method], ylabel="forward, per cent" if index % 2 == 0 else None,
                   xlabel="maturity, years" if index >= 2 else None, grid="y")  # fmt: skip
        verdicts = {
            "linear": "kinks at every pillar; forwards jump",
            "log_linear": "flat between pillars; jumps at them",
            "monotone_cubic": "smooth zeros, but forwards still kink",
            "monotone_convex": "continuous, positive, local",
        }
        ax.text(0.99, 0.95, verdicts[method], transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
                color=colour, fontweight="bold")  # fmt: skip
    caption(
        fig,
        "Grey lines: the pillar dates. The US Treasury has built its official par curve with monotone convex since "
        "December 2021.",
    )
    return fig


def plot_locality(
    times: Sequence[float], responses: Mapping[str, Sequence[float]], bumped_time: float, bumped_label: str
) -> Figure:
    fig = new_figure(13.5, 8.0)
    title_block(
        fig,
        f"Locality: raise the {bumped_label} quote by one basis point and watch the forwards",
        "The change in the instantaneous forward curve after rebuilding. A local method moves forwards only near the "
        "bumped pillar; a non-local one sends ripples to maturities no hedge would expect.",
    )
    grid = fig.add_gridspec(len(responses), 1, left=0.07, right=0.97, top=0.86, bottom=0.09, hspace=0.25)
    limit = max(float(np.max(np.abs(values))) for values in responses.values()) * 1.1
    for index, (method, values) in enumerate(responses.items()):
        ax = fig.add_subplot(grid[index, 0])
        colour = METHOD_COLOURS[method]
        array = np.asarray(values)
        ax.fill_between(times, 0, array, color=colour, alpha=0.25, lw=0)
        ax.plot(times, array, color=colour, lw=1.6)
        ax.axvline(bumped_time, color=PALETTE["accent"], lw=1.0, ls="--")
        ax.axhline(0, color=PALETTE["muted"], lw=0.6)
        ax.set_ylim(-limit, limit)
        ax.set_xlim(0, 40)
        far = (
            float(np.max(np.abs(array[np.asarray(times) > bumped_time * 2.2])))
            if np.any(np.asarray(times) > bumped_time * 2.2)
            else 0.0
        )
        style_axes(ax, ylabel="bp", grid="y")
        ax.text(0.30, 0.90, METHOD_NAMES[method], transform=ax.transAxes, fontsize=9.5, fontweight="bold",
                color=colour, va="top",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.9})  # fmt: skip
        ax.text(0.995, 0.88, f"largest move beyond {bumped_time * 2.2:.0f}y: {far:.3f} bp", transform=ax.transAxes,
                ha="right", va="top", fontsize=8, color=PALETTE["muted"])  # fmt: skip
        if index < len(responses) - 1:
            ax.tick_params(labelbottom=False)
        else:
            ax.set_xlabel("maturity, years")
    return fig


def plot_jacobian(labels: Sequence[str], matrices: Mapping[str, np.ndarray]) -> Figure:
    fig = new_figure(14.0, 7.6)
    title_block(
        fig,
        "The Jacobian: how each quote moves each point of the zero curve",
        "d(zero rate at pillar) / d(quote), by rebuilding the curve with each quote bumped. Everything sits on or "
        "below "
        "the diagonal when a quote cannot move the curve before its own maturity; monotone convex leaks a little "
        "upwards.",
    )
    norm = mcolors.TwoSlopeNorm(vmin=-0.5, vcenter=0.0, vmax=1.5)
    image = None
    for index, (method, matrix) in enumerate(matrices.items()):
        ax = fig.add_axes((0.05 + index * 0.46, 0.12, 0.40, 0.70))
        image = ax.imshow(np.asarray(matrix).T, cmap="RdBu_r", norm=norm, aspect="auto")
        ax.set_xticks(range(len(labels)), labels, rotation=90, fontsize=7.5)
        ax.set_yticks(range(len(labels)), labels, fontsize=7.5)
        style_axes(
            ax,
            title=METHOD_NAMES[method],
            xlabel="quote bumped",
            ylabel="zero rate at pillar" if index == 0 else None,
            grid=None,
        )
        # matrix[i][j] is quote i's effect on pillar j: j < i is a later quote moving an earlier pillar
        backwards = float(np.max(np.abs(np.tril(np.asarray(matrix), -1))))
        note = f"largest effect of a quote on an\nearlier pillar: {backwards:.3f} bp per bp"
        ax.text(0.98, 0.97, note, transform=ax.transAxes,
                ha="right", va="top", fontsize=8.5, color=PALETTE["ink"],
                bbox={"facecolor": "white", "edgecolor": PALETTE["grid"], "alpha": 0.95})  # fmt: skip
    if image is not None:
        bar = fig.add_axes((0.93, 0.12, 0.012, 0.70))
        fig.colorbar(image, cax=bar).set_label("basis points of zero rate per basis point of quote", fontsize=8)
    return fig


def plot_bucketed_dv01(
    labels: Sequence[str], contributions: Mapping[str, Sequence[float]], hedges: Sequence[float], total: float
) -> Figure:
    fig = new_figure(13.5, 8.0)
    title_block(
        fig,
        "Risk in the instruments that hedge it: bucketed DV01 of a swap book",
        f"Change in value for a one basis point rise in each quote, the others held. The buckets sum to the parallel "
        f"DV01 of {total:,.0f} dollars.",
    )
    ax = fig.add_axes((0.07, 0.43, 0.90, 0.43))
    positions = np.arange(len(labels))
    bottom_positive = np.zeros(len(labels))
    bottom_negative = np.zeros(len(labels))
    palette = [PALETTE["navy"], PALETTE["teal"], PALETTE["violet"], PALETTE["sky"]]
    for colour, (name, values) in zip(palette, contributions.items(), strict=False):
        array = np.asarray(values)
        base = np.where(array >= 0, bottom_positive, bottom_negative)
        ax.bar(positions, array, bottom=base, color=colour, width=0.68, label=name)
        bottom_positive += np.where(array >= 0, array, 0)
        bottom_negative += np.where(array < 0, array, 0)
    ax.axhline(0, color=PALETTE["ink"], lw=0.8)
    ax.set_xticks(positions, labels, fontsize=8)
    style_axes(ax, ylabel="dollars per basis point", grid="y")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False, fontsize=8.5, ncol=4)

    low = fig.add_axes((0.07, 0.07, 0.90, 0.20), sharex=ax)
    hedge_array = np.asarray(hedges) / 1e6
    low.bar(
        positions, hedge_array, color=[PALETTE["gain"] if h > 0 else PALETTE["loss"] for h in hedge_array], width=0.68
    )
    low.axhline(0, color=PALETTE["ink"], lw=0.8)
    for x, value in zip(positions, hedge_array, strict=True):
        if abs(value) > 0.5:
            low.text(
                x,
                value,
                f"{value:+,.0f}m",
                ha="center",
                va="bottom" if value > 0 else "top",
                fontsize=7,
                color=PALETTE["ink"],
            )
    style_axes(
        low,
        title="The hedge: notional of each quoted swap to receive (+) or pay (-) to flatten every bucket",
        ylabel="$ million",
        grid="y",
    )
    return fig


# ---------------------------------------------------------------------------- 36 years of history
EVENTS: tuple[tuple[date, str], ...] = (
    (date(1994, 2, 4), "1994: the bond massacre"),
    (date(2001, 1, 3), "2001: cuts after the dot-com bust"),
    (date(2008, 9, 15), "2008: Lehman"),
    (date(2008, 12, 16), "zero lower bound"),
    (date(2013, 5, 22), "2013: taper tantrum"),
    (date(2020, 3, 15), "2020: COVID"),
    (date(2022, 3, 16), "2022: hikes begin"),
    (date(2022, 7, 6), "2-10 inverts"),
)


def plot_treasury_heatmap(days: Sequence[date], labels: Sequence[str], yields: np.ndarray) -> Figure:
    fig = new_figure(14.5, 7.8)
    title_block(
        fig,
        f"The US Treasury curve, every business day from {days[0].year} to {days[-1]:%B %Y}",
        f"{len(days):,} published par curves. Colour is the yield; each row is a constant maturity. White: a "
        "maturity the Treasury was not publishing (the 20-year before 1993, the 30-year from 2002 to 2006, the "
        "1-month before 2001).",
    )
    ax = fig.add_axes((0.07, 0.10, 0.84, 0.74))
    extent = (x_of(days[0]), x_of(days[-1]), -0.5, len(labels) - 0.5)
    image = ax.imshow(
        np.asarray(yields).T * 100,
        aspect="auto",
        origin="lower",
        extent=extent,
        cmap="viridis",
        interpolation="nearest",
    )
    ax.set_yticks(range(len(labels)), labels)
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.YearLocator(4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    style_axes(ax, ylabel="maturity", grid=None)
    for index, (day, label) in enumerate(EVENTS):
        ax.axvline(x_of(day), color="white", lw=0.8, alpha=0.8)
        ax.text(x_of(day), len(labels) - 0.6 - (index % 3) * 0.9, " " + label, color="white", fontsize=7.5, va="top",
                fontweight="bold")  # fmt: skip
    bar = fig.add_axes((0.925, 0.10, 0.012, 0.74))
    fig.colorbar(image, cax=bar).set_label("par yield, per cent", fontsize=8.5)
    caption(fig, "Source: US Department of the Treasury, Daily Treasury Par Yield Curve Rates (public domain).")
    return fig


def plot_treasury_surface(
    days: Sequence[date], tenors: Sequence[float], labels: Sequence[str], yields: np.ndarray
) -> Figure:
    fig = new_figure(14.0, 8.0)
    title_block(
        fig,
        "Thirty-six years of the yield curve as a landscape",
        "Month-end par yields, 3 months to 10 years: time runs left to right, maturity front to back. The two valleys "
        "are the zero lower bound of 2009-2015 and of 2020-2021.",
    )
    ax = cast(Axes3D, fig.add_axes((-0.12, -0.18, 1.12, 1.18), projection="3d"))
    time_axis = np.array([x_of(day) for day in days])
    tenor_axis = np.log(np.asarray(tenors))
    grid_time, grid_tenor = np.meshgrid(time_axis, tenor_axis, indexing="ij")
    surface = ax.plot_surface(grid_time, grid_tenor, np.asarray(yields) * 100, cmap="viridis", linewidth=0,
                              antialiased=True, rstride=1, cstride=1, alpha=0.96)  # fmt: skip
    ax.set_yticks(tenor_axis, labels, fontsize=7.5)
    years = [date(year, 1, 1) for year in range(1990, days[-1].year + 1, 6)]
    ax.set_xticks([x_of(day) for day in years], [str(day.year) for day in years], fontsize=8)
    ax.zaxis.set_tick_params(labelsize=8)
    ax.view_init(elev=24, azim=-58)
    ax.set_box_aspect((2.8, 1.0, 0.75), zoom=1.25)
    ax.xaxis.pane.set_facecolor("white")
    ax.yaxis.pane.set_facecolor("white")
    ax.zaxis.pane.set_facecolor("white")
    bar = fig.add_axes((0.93, 0.25, 0.012, 0.45))
    fig.colorbar(surface, cax=bar).set_label("par yield, per cent", fontsize=8.5)
    return fig


def plot_pca(
    labels: Sequence[str], loadings: np.ndarray, explained: Sequence[float], volatility_bp: Sequence[float], days: int
) -> Figure:
    fig = new_figure(14.0, 7.2)
    title_block(
        fig,
        "Level, slope and curvature: three factors move the Treasury curve",
        f"Principal components of {days:,} daily changes in par yields since 1990. After Litterman and Scheinkman "
        "(1991): the first three explain nearly everything, and each has a shape a trader would name.",
    )
    names = ("Level", "Slope", "Curvature")
    colours = (PALETTE["navy"], PALETTE["teal"], PALETTE["violet"])
    ax = fig.add_axes((0.06, 0.12, 0.56, 0.70))
    for index in range(3):
        ax.plot(range(len(labels)), loadings[:, index], color=colours[index], lw=2.4, marker="o", ms=5,
                label=f"{names[index]}: {explained[index] * 100:.1f}% of variance, "
                f"{volatility_bp[index]:.0f} bp a year")  # fmt: skip
    ax.axhline(0, color=PALETTE["muted"], lw=0.7)
    ax.set_xticks(range(len(labels)), labels)
    style_axes(
        ax,
        title="The loadings: how each maturity moves with each factor",
        ylabel="loading",
        xlabel="maturity",
        grid="y",
    )
    ax.legend(loc="lower left", frameon=False, fontsize=8.5)

    scree = fig.add_axes((0.70, 0.12, 0.28, 0.70))
    shown = np.asarray(explained[: len(labels)]) * 100
    bars = scree.bar(range(1, len(shown) + 1), shown, color=[*colours, *[PALETTE["grid"]] * (len(shown) - 3)])
    cumulative = np.cumsum(shown)
    scree.plot(range(1, len(shown) + 1), cumulative, color=PALETTE["accent"], marker="o", ms=4, lw=1.6)
    for bar, value in zip(bars[:3], shown[:3], strict=True):
        scree.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.5,
            f"{value:.1f}%",
            ha="center",
            fontsize=8.5,
            color=PALETTE["ink"],
        )
    scree.text(
        3.2,
        cumulative[2] + 2.5,
        f"{cumulative[2]:.1f}% with three",
        fontsize=9,
        color=PALETTE["accent"],
        fontweight="bold",
    )
    scree.set_ylim(0, 108)
    style_axes(scree, title="Variance explained", xlabel="component", ylabel="per cent", grid="y")
    caption(
        fig,
        "Maturities published continuously since 1990. Daily changes in basis points; eigenvectors oriented to read "
        "as their names.",
    )
    return fig


def plot_pca_history(
    ends: Sequence[date], shares: np.ndarray, score_days: Sequence[date], level: Sequence[float], slope: Sequence[float]
) -> Figure:
    fig = new_figure(14.0, 8.4)
    title_block(
        fig,
        "The factors through time",
        "Above: the share of variance each factor explains in rolling two-year windows. Below: the cumulative level "
        "and "
        "slope factors - the curve's history told in two numbers.",
    )
    top = fig.add_axes((0.07, 0.52, 0.90, 0.32))
    stacked = np.asarray(shares) * 100
    top.stackplot([x_of(day) for day in ends], stacked.T, colors=[PALETTE["navy"], PALETTE["teal"], PALETTE["violet"]],
                  labels=["level", "slope", "curvature"], alpha=0.92)  # fmt: skip
    top.set_ylim(40, 100)
    top.xaxis_date()
    style_axes(top, ylabel="per cent explained", grid="y")
    top.legend(loc="lower left", ncol=3, frameon=False, fontsize=8.5)
    top.tick_params(labelbottom=False)

    bottom = fig.add_axes((0.07, 0.10, 0.90, 0.36), sharex=top)
    x = [x_of(day) for day in score_days]
    bottom.plot(x, np.cumsum(level) / 100, color=PALETTE["navy"], lw=1.4, label="level (cumulative, per cent)")
    bottom.plot(x, np.cumsum(slope) / 100, color=PALETTE["teal"], lw=1.4, label="slope (cumulative, per cent)")
    bottom.axhline(0, color=PALETTE["muted"], lw=0.6)
    for day, _ in EVENTS:
        bottom.axvline(x_of(day), color=PALETTE["grid"], lw=0.8, zorder=0)
    bottom.xaxis_date()
    bottom.xaxis.set_major_locator(mdates.YearLocator(4))
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    style_axes(bottom, ylabel="factor score, cumulative", grid="y")
    bottom.legend(loc="lower left", frameon=False, fontsize=8.5)
    caption(
        fig,
        "Scores are daily projections of curve changes on the full-sample loadings. Grey lines: the events marked on "
        "the heatmap.",
    )
    return fig


@dataclass(frozen=True)
class FitPanel:
    day: date
    tenors: tuple[float, ...]
    par_yields: tuple[float, ...]
    grid: tuple[float, ...]
    svensson: tuple[float, ...]
    nelson_siegel: tuple[float, ...]
    gsw: tuple[float, ...]
    svensson_rmse: float
    nelson_siegel_rmse: float
    note: str


def plot_nss_fits(panels: Sequence[FitPanel]) -> Figure:
    fig = new_figure(14.0, 9.4)
    title_block(
        fig,
        "Nelson-Siegel and Svensson fitted to the real Treasury curve, beside the Federal Reserve's own fit",
        "Dots: the Treasury's published par yields. Lines: par yields of each fitted curve. The Fed's curve (GSW) is "
        "fitted to off-the-run coupon bonds, not to these points: a second opinion of the same market.",
    )
    grid = fig.add_gridspec(2, 2, left=0.06, right=0.98, top=0.86, bottom=0.08, hspace=0.34, wspace=0.14)
    for index, panel in enumerate(panels):
        ax = fig.add_subplot(grid[index // 2, index % 2])
        ax.plot(
            panel.grid,
            np.asarray(panel.gsw) * 100,
            color=PALETTE["accent"],
            lw=1.4,
            ls="--",
            label="Federal Reserve GSW",
        )
        ax.plot(panel.grid, np.asarray(panel.nelson_siegel) * 100, color=PALETTE["slate"], lw=1.4,
                label=f"Nelson-Siegel, RMSE {panel.nelson_siegel_rmse:.1f} bp")  # fmt: skip
        ax.plot(panel.grid, np.asarray(panel.svensson) * 100, color=PALETTE["teal"], lw=2.4,
                label=f"Svensson, RMSE {panel.svensson_rmse:.1f} bp")  # fmt: skip
        ax.scatter(
            panel.tenors,
            np.asarray(panel.par_yields) * 100,
            color=PALETTE["navy"],
            s=30,
            zorder=5,
            label="Treasury par yield",
        )
        ax.set_xscale("log")
        ax.set_xticks([0.25, 1, 2, 5, 10, 30], ["3M", "1Y", "2Y", "5Y", "10Y", "30Y"])
        style_axes(
            ax, title=f"{panel.day:%d %B %Y} - {panel.note}", ylabel="per cent" if index % 2 == 0 else None, grid="both"
        )
        ax.legend(loc="best", frameon=False, fontsize=7.5)
    caption(
        fig,
        "Sources: US Treasury par yield curve; Gurkaynak, Sack and Wright (2007), Federal Reserve Board FEDS 2006-28.",
    )
    return fig


def plot_nss_history(
    days: Sequence[date], gaps_bp: Mapping[str, Sequence[float]], rmse_bp: Sequence[float], formula_error_bp: float
) -> Figure:
    fig = new_figure(14.0, 8.0)
    title_block(
        fig,
        "Our Svensson fit against the Federal Reserve's, every quarter since 1990",
        f"Zero-coupon yield from our fit to the Treasury's par curve, minus the Fed's GSW yield. The formula itself "
        f"reproduces every published GSW yield from its parameters to {formula_error_bp:.3f} bp.",
    )
    top = fig.add_axes((0.07, 0.42, 0.90, 0.42))
    x = [x_of(day) for day in days]
    for colour, (label, values) in zip(
        (PALETTE["navy"], PALETTE["teal"], PALETTE["violet"]), gaps_bp.items(), strict=False
    ):
        top.plot(
            x, values, color=colour, lw=1.2, label=f"{label} zero: median gap {np.nanmedian(np.abs(values)):.1f} bp"
        )
    top.axhline(0, color=PALETTE["muted"], lw=0.7)
    top.xaxis_date()
    style_axes(top, ylabel="ours minus GSW, bp", grid="y")
    top.legend(loc="upper left", frameon=False, fontsize=8.5, ncol=3)
    top.tick_params(labelbottom=False)

    bottom = fig.add_axes((0.07, 0.10, 0.90, 0.24), sharex=top)
    bottom.fill_between(x, 0, rmse_bp, color=PALETTE["teal"], alpha=0.35, lw=0)
    bottom.plot(x, rmse_bp, color=PALETTE["teal"], lw=1.0)
    bottom.xaxis_date()
    bottom.xaxis.set_major_locator(mdates.YearLocator(4))
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    style_axes(bottom, title="How well six parameters fit that day's par curve (RMSE, bp)", ylabel="bp", grid="y")
    caption(
        fig,
        "The gap is two fits of different bonds - bills and on-the-runs are in the Treasury's curve, not in GSW's - "
        "not an error in either.",
    )
    return fig


# ---------------------------------------------------------------------------- gilts
def plot_gilt(days: Sequence[date], accrued: Sequence[float], clean: Sequence[float], dirty: Sequence[float],
              ex_windows: Sequence[tuple[date, date]], name: str) -> Figure:  # fmt: skip
    fig = new_figure(13.5, 8.0)
    title_block(
        fig,
        f"A gilt goes ex-dividend: {name}",
        "Seven business days before each coupon the gilt trades without it. Accrued interest turns negative, the dirty "
        "price drops by about a coupon, and the clean price - what the screen shows - barely notices.",
    )
    top = fig.add_axes((0.07, 0.50, 0.90, 0.34))
    x = [x_of(day) for day in days]
    top.plot(x, dirty, color=PALETTE["navy"], lw=1.8, label="dirty price (what is paid)")
    top.plot(x, clean, color=PALETTE["teal"], lw=1.8, label="clean price (what is quoted)")
    for start, end in ex_windows:
        top.axvspan(x_of(start), x_of(end), color=PALETTE["accent"], alpha=0.15, lw=0)
    top.xaxis_date()
    style_axes(top, ylabel="per 100 nominal", grid="y")
    top.legend(loc="upper left", frameon=False, fontsize=8.5)
    top.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    bottom = fig.add_axes((0.07, 0.10, 0.60, 0.30))
    values = np.asarray(accrued)
    bottom.fill_between(x, 0, values, where=values >= 0, color=PALETTE["gain"], alpha=0.35, lw=0, interpolate=True)
    bottom.fill_between(x, 0, values, where=values < 0, color=PALETTE["loss"], alpha=0.45, lw=0, interpolate=True)
    bottom.plot(x, values, color=PALETTE["ink"], lw=1.0)
    bottom.axhline(0, color=PALETTE["muted"], lw=0.7)
    for start, end in ex_windows:
        bottom.axvspan(x_of(start), x_of(end), color=PALETTE["accent"], alpha=0.15, lw=0)
        bottom.text(
            x_of(end),
            float(values.max()) * 0.92,
            " ex-dividend",
            fontsize=7.5,
            color=PALETTE["accent"],
            fontweight="bold",
        )
    if ex_windows:
        # a close-up of the first ex period, day by day
        start, end = ex_windows[0]
        chosen = [i for i, day in enumerate(days) if (start - (end - start) * 1.2) <= day <= end + (end - start) * 1.4]
        inset = fig.add_axes((0.73, 0.10, 0.24, 0.30))
        inset.axvspan(x_of(start), x_of(end), color=PALETTE["accent"], alpha=0.15, lw=0)
        inset.plot([x[i] for i in chosen], values[chosen], color=PALETTE["ink"], lw=1.0, marker="o", ms=3.5)
        inset.axhline(0, color=PALETTE["muted"], lw=0.7)
        cum = max((i for i in chosen if days[i] < start), default=chosen[0])
        ex = min((i for i in chosen if days[i] >= start), default=chosen[-1])
        inset.annotate(
            f"{days[cum]:%d %b}: +{values[cum]:.2f}\nlast day cum",
            (x[cum], values[cum]),
            xytext=(-6, -26),
            textcoords="offset points",
            ha="right",
            fontsize=7.5,
            color=PALETTE["gain"],
            fontweight="bold",
        )
        inset.annotate(
            f"{days[ex]:%d %b}: {values[ex]:.2f}\nfirst day ex",
            (x[ex], values[ex]),
            xytext=(8, 14),
            textcoords="offset points",
            fontsize=7.5,
            color=PALETTE["loss"],
            fontweight="bold",
        )
        inset.xaxis_date()
        inset.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        inset.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
        inset.tick_params(labelsize=6.5)
        style_axes(inset, title="Close-up: January, one business day per point", grid="y")
        inset.title.set_fontsize(9)
    bottom.xaxis_date()
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    style_axes(
        bottom,
        title="Accrued interest: earned by the seller, or owed to the buyer in the ex period",
        ylabel="per 100",
        grid="y",
    )
    caption(
        fig,
        "Priced at a 4.5% yield by the DMO's formula, ACT/ACT ICMA; matches QuantLib's exCouponPeriod to 1e-13 on "
        "every day shown.",
    )
    return fig


def legend_patch(colour: str, label: str) -> Rectangle:
    return Rectangle((0, 0), 1, 1, color=colour, label=label)
