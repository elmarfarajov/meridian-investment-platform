"""Charts for market data on real FX: what the quality engine learnt from 27 years of central bank fixings.

The functions draw what they are given; ``meridian.fx_gallery`` computes it from the
packaged ECB and Federal Reserve data, the currency regimes and the quality engine.
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

from .style import PALETTE, caption, new_figure, style_axes, title_block, x_of

RULE_COLOURS = {
    "stale_mark": PALETTE["sky"],
    "robust_outlier": PALETTE["navy"],
    "spike_reversal": PALETTE["violet"],
    "missing_days": PALETTE["slate"],
    "peg_band": PALETTE["loss"],
}
RULE_NAMES = {
    "stale_mark": "stale mark",
    "robust_outlier": "robust outlier",
    "spike_reversal": "spike and reversal",
    "missing_days": "missing days",
    "peg_band": "outside its band",
}
REGIME_COLOURS = {
    "float": "#C9D6E6",
    "currency board": PALETTE["navy"],
    "ERM II": PALETTE["teal"],
    "unilateral peg": PALETTE["violet"],
    "crawling peg": PALETTE["sky"],
    "floor": PALETTE["accent"],
}


# ---------------------------------------------------------------------------- the waterfall
@dataclass(frozen=True)
class StageBar:
    name: str
    by_rule: Mapping[str, int]
    explained: int
    lesson: str


def plot_findings_waterfall(stages: Sequence[StageBar], observations: int, currencies: int, years: str) -> Figure:
    fig = new_figure(14.0, 8.0)
    first = sum(stages[0].by_rule.values())
    last = sum(stages[-1].by_rule.values()) - stages[-1].explained
    title_block(
        fig,
        f"The quality engine on real data: {first:,} findings, {last} left for a person",
        f"Day 2's FX rules, run over {observations:,} ECB fixings of {currencies} currencies ({years}). Each bar "
        "adds one thing the rules were not told: most findings were facts about currencies, not faults in the data.",
    )
    ax = fig.add_axes((0.06, 0.24, 0.90, 0.60))
    positions = np.arange(len(stages))
    for x, stage in zip(positions, stages, strict=True):
        bottom = 0.0
        for rule, colour in RULE_COLOURS.items():
            count = stage.by_rule.get(rule, 0)
            if not count:
                continue
            ax.bar(x, count, bottom=bottom, color=colour, width=0.62)
            bottom += count
        if stage.explained:
            ax.bar(x, stage.explained, bottom=bottom - stage.explained, width=0.62, facecolor="none",
                   edgecolor=PALETTE["gain"], hatch="///", lw=0)  # fmt: skip
        total = sum(stage.by_rule.values())
        label = f"{total:,}" if not stage.explained else f"{total - stage.explained} open\n+{stage.explained} explained"
        ax.text(x, total + first * 0.015, label, ha="center", va="bottom", fontsize=10, fontweight="bold",
                color=PALETTE["ink"])  # fmt: skip
        if x > 0:
            previous = sum(stages[x - 1].by_rule.values()) - stages[x - 1].explained
            shown = total - stage.explained
            ax.annotate("", xy=(x - 0.32, shown), xytext=(x - 0.68, previous),
                        arrowprops={"arrowstyle": "->", "color": PALETTE["muted"], "lw": 1.0})  # fmt: skip
    ax.set_xticks(positions, [stage.name for stage in stages], fontsize=9)
    ax.set_ylim(0, first * 1.15)
    style_axes(ax, ylabel="findings", grid="y")
    handles = [Patch(color=colour, label=RULE_NAMES[rule]) for rule, colour in RULE_COLOURS.items()]
    handles.append(Patch(facecolor="none", edgecolor=PALETTE["gain"], hatch="///", label="explained by a market event"))
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=8.5, ncol=2)
    for x, stage in zip(positions, stages, strict=True):
        ax.text(x, -0.09, textwrap.fill(stage.lesson, 30), transform=ax.get_xaxis_transform(), ha="center", va="top",
                fontsize=8, color=PALETTE["muted"], style="italic")  # fmt: skip
    caption(fig, "Source: European Central Bank, euro foreign exchange reference rates. Rules: robust outlier, spike "
                 "and reversal, stale mark and missing days, as in Day 2, then made aware step by step.")  # fmt: skip
    return fig


# ---------------------------------------------------------------------------- lifecycles
@dataclass(frozen=True)
class Lifeline:
    currency: str
    first: date
    last: date
    segments: tuple[tuple[date, date, str], ...]  # (start, end, regime kind)
    gaps: tuple[tuple[date, date], ...]
    ending: str  # "" while still fixed


def plot_lifecycles(lines: Sequence[Lifeline], today: date) -> Figure:
    fig = new_figure(14.0, 11.5)
    title_block(
        fig,
        "Forty-one currencies against the euro: what each was, and when it stopped",
        "Every currency the ECB has fixed since 1999. Colour is the regime the central bank ran; a currency that "
        "joined the euro ends at its irrevocable conversion rate, and a suspension leaves a gap.",
    )
    ax = fig.add_axes((0.07, 0.07, 0.74, 0.84))
    for row, line in enumerate(lines):
        y = len(lines) - 1 - row
        for start, end, kind in line.segments:
            ax.barh(y, x_of(end) - x_of(start), left=x_of(start), height=0.66, color=REGIME_COLOURS[kind], lw=0)
        for start, end in line.gaps:
            ax.barh(y, x_of(end) - x_of(start), left=x_of(start), height=0.66, color="white",
                    edgecolor=PALETTE["loss"], hatch="////", lw=0.4)  # fmt: skip
        if line.ending:
            ax.text(x_of(line.last) + 40, y, line.ending, va="center", fontsize=7.2, color=PALETTE["ink"])
    ax.set_yticks(range(len(lines)), [line.currency for line in reversed(lines)], fontsize=8)
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.YearLocator(3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(x_of(date(1998, 9, 1)), x_of(date(2030, 6, 1)))
    ax.set_ylim(-0.7, len(lines) - 0.3)
    ax.axvline(x_of(today), color=PALETTE["muted"], lw=0.8, ls="--")
    style_axes(ax, grid="x")
    ax.tick_params(axis="y", length=0)
    handles = [Patch(color=colour, label=kind) for kind, colour in REGIME_COLOURS.items()]
    handles.append(Patch(facecolor="white", edgecolor=PALETTE["loss"], hatch="////", label="fixing suspended"))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.82, 0.90), frameon=False, fontsize=9,
               title="regime against the euro", title_fontsize=9)  # fmt: skip
    caption(fig, "Sources: ECB reference rates; the Council of the EU's conversion-rate regulations; the national "
                 "central banks. Each regime is a record in meridian.refdata.currency_regimes.")  # fmt: skip
    return fig


# ---------------------------------------------------------------------------- pegs and bands
@dataclass(frozen=True)
class BandPanel:
    title: str
    days: tuple[date, ...]
    deviation_pct: tuple[float, ...]
    band_pct: float | None
    floor: bool
    note: str


def plot_bands(panels: Sequence[BandPanel]) -> Figure:
    fig = new_figure(14.0, 9.6)
    title_block(
        fig,
        "A pegged rate is supposed to look stale",
        "Each managed currency's fixing as a distance from its central rate, inside the band its central bank "
        "defended. A rule that called these frozen feeds was wrong for 25 years.",
    )
    grid = fig.add_gridspec(2, 3, left=0.06, right=0.98, top=0.86, bottom=0.08, hspace=0.42, wspace=0.18)
    for index, panel in enumerate(panels):
        ax = fig.add_subplot(grid[index // 3, index % 3])
        x = [x_of(day) for day in panel.days]
        if panel.band_pct:
            ax.axhspan(-panel.band_pct, panel.band_pct, color=PALETTE["band"], zorder=0)
            ax.axhline(panel.band_pct, color=PALETTE["teal"], lw=0.8, ls="--")
            ax.axhline(-panel.band_pct, color=PALETTE["teal"], lw=0.8, ls="--")
        if panel.floor:
            ax.axhspan(-100, 0, color="#F7E3D2", zorder=0)
            ax.axhline(0, color=PALETTE["accent"], lw=1.2)
        ax.plot(x, panel.deviation_pct, color=PALETTE["navy"], lw=1.0)
        ax.axhline(0, color=PALETTE["muted"], lw=0.5)
        values = np.asarray(panel.deviation_pct)
        span = max(float(np.max(np.abs(values))), panel.band_pct or 0) * 1.25 or 1
        ax.set_ylim(-span if not panel.floor else -span * 0.4, span)
        ax.xaxis_date()
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=5))
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        style_axes(ax, title=panel.title, ylabel="% from central" if index % 3 == 0 else None, grid="y")
        ax.text(0.02, 0.04, panel.note, transform=ax.transAxes, fontsize=7.8, color=PALETTE["muted"])
    caption(fig, "Source: ECB reference rates. Bands and central rates: Danmarks Nationalbank, Bulgarian National "
                 "Bank, Latvijas Banka, Narodna banka Slovenska, the SNB and the CNB.")  # fmt: skip
    return fig


# ---------------------------------------------------------------------------- volatility history
def plot_volatility_map(currencies: Sequence[str], years: Sequence[int], volatility: np.ndarray) -> Figure:
    fig = new_figure(14.0, 10.0)
    title_block(
        fig,
        "Twenty-seven years of the euro, currency by currency",
        "Annualised volatility of each ECB fixing, year by year. Blank: not fixed that year. The pegs are the "
        "quiet rows; 2008, 2015 (the franc) and 2018-2023 (the lira, the rouble) are the loud columns.",
    )
    ax = fig.add_axes((0.07, 0.08, 0.84, 0.81))
    masked = np.ma.masked_invalid(volatility * 100)
    image = ax.imshow(masked, aspect="auto", cmap="magma_r", vmin=0, vmax=25, interpolation="nearest")
    ax.set_yticks(range(len(currencies)), currencies, fontsize=8)
    ax.set_xticks(range(len(years)), [str(year) if year % 3 == 0 else "" for year in years], fontsize=8)
    style_axes(ax, grid=None)
    for row in range(volatility.shape[0]):
        for column in range(volatility.shape[1]):
            value = volatility[row, column]
            if np.isfinite(value) and value * 100 >= 20:
                ax.text(column, row, f"{value * 100:.0f}", ha="center", va="center", fontsize=6.5, color="white")
    bar = fig.add_axes((0.925, 0.08, 0.012, 0.81))
    fig.colorbar(image, cax=bar).set_label("annualised volatility, %", fontsize=8.5)
    return fig


# ---------------------------------------------------------------------------- resolution and staleness
@dataclass(frozen=True)
class StalePoint:
    currency: str
    expected: float
    observed: float
    regime: str


def plot_staleness(points: Sequence[StalePoint]) -> Figure:
    fig = new_figure(13.0, 8.6)
    title_block(
        fig,
        "How often should a rate not move? The model against 27 years of fixings",
        "For each currency, the share of fixings unchanged from the day before: expected from its volatility and "
        "the resolution of its quote, erf(tick / 2 sqrt(2) sigma), against what the ECB actually printed.",
    )
    ax = fig.add_axes((0.08, 0.10, 0.62, 0.76))
    for point in points:
        colour = REGIME_COLOURS.get(point.regime, PALETTE["navy"]) if point.regime != "float" else PALETTE["slate"]
        ax.scatter(point.expected * 100, point.observed * 100, s=60, color=colour, edgecolor="white", lw=0.6, zorder=3)
        if point.regime != "float" or point.observed > 0.08 or point.currency in {"ISK", "TRL", "JPY", "USD"}:
            ax.annotate(point.currency, (point.expected * 100, point.observed * 100), textcoords="offset points",
                        xytext=(5, 3), fontsize=8, color=PALETTE["ink"])  # fmt: skip
    top = max(max(point.expected, point.observed) for point in points) * 100 * 1.1
    ax.plot([0, top], [0, top], color=PALETTE["accent"], lw=1.2, ls="--")
    ax.text(1.4, 1.0, "observed = expected", rotation=37, color=PALETTE["accent"], fontsize=8.5)
    ax.set_xscale("symlog", linthresh=0.5)
    ax.set_yscale("symlog", linthresh=0.5)
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    style_axes(ax, xlabel="expected share unchanged, % (symmetric log)", ylabel="observed share unchanged, %",
               grid="both")  # fmt: skip
    side = fig.add_axes((0.74, 0.10, 0.24, 0.76))
    side.axis("off")
    side.text(0, 0.98, "What the model explains", fontsize=10, fontweight="bold", color=PALETTE["ink"], va="top")
    lines = [
        "Floating currencies sit near the line:",
        "an unchanged fixing is as rare as their",
        "volatility and four decimals make it.",
        "",
        "Pegged currencies sit high on both axes:",
        "the rate is meant not to move, and the",
        "rule now expects it.",
        "",
        "Coarse quotes (the krona to one decimal,",
        "the old lira to thousands) repeat often",
        "for the same reason - resolution, not",
        "a frozen feed.",
        "",
        "Above the line: more repeats than the",
        "data can explain. That is where a stale",
        "source hides - and the krona's 19",
        "unchanged days of October 2008 are one.",
    ]
    for index, line in enumerate(lines):
        side.text(0, 0.90 - index * 0.045, line, fontsize=8.6, color=PALETTE["muted"], va="top")
    return fig


# ---------------------------------------------------------------------------- events
@dataclass(frozen=True)
class EventPanel:
    pair: str
    title: str
    days: tuple[date, ...]
    rates: tuple[float, ...]
    flagged: tuple[tuple[date, float, str], ...]  # day, rate, "explained" or "open"
    excluded: tuple[tuple[date, date], ...]
    marker: date


def plot_events(panels: Sequence[EventPanel]) -> Figure:
    fig = new_figure(14.0, 10.0)
    title_block(
        fig,
        "Real days, real findings: what the engine saw, and what it was told",
        "Each fixing around a documented event, with the engine's findings. Green: explained by the event register. "
        "Red: left open. Shaded: days the statistics stand aside (a managed regime, or the window after one).",
    )
    grid = fig.add_gridspec(2, 3, left=0.06, right=0.98, top=0.86, bottom=0.07, hspace=0.42, wspace=0.2)
    for index, panel in enumerate(panels):
        ax = fig.add_subplot(grid[index // 3, index % 3])
        for start, end in panel.excluded:
            ax.axvspan(x_of(start), x_of(end), color=PALETTE["band"], lw=0, zorder=0)
        ax.plot([x_of(day) for day in panel.days], panel.rates, color=PALETTE["navy"], lw=1.1)
        ax.axvline(x_of(panel.marker), color=PALETTE["accent"], lw=0.9, ls="--")
        for day, rate, status in panel.flagged:
            colour = PALETTE["gain"] if status == "explained" else PALETTE["loss"]
            ax.scatter([x_of(day)], [rate], s=34, color=colour, edgecolor="white", lw=0.6, zorder=4)
        ax.xaxis_date()
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=4))
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        style_axes(ax, title=f"{panel.pair}: {panel.title}", grid="y")
        ax.title.set_fontsize(9.5)
    handles = [
        Line2D([], [], marker="o", ls="", color=PALETTE["gain"], label="finding explained by the event"),
        Line2D([], [], marker="o", ls="", color=PALETTE["loss"], label="finding left open"),
        Patch(color=PALETTE["band"], label="statistics stand aside"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, 0.0))
    return fig


# ---------------------------------------------------------------------------- two central banks
@dataclass(frozen=True)
class GapSeries:
    pair: str
    days: tuple[date, ...]
    gaps: tuple[float, ...]
    next_move: tuple[float, ...]
    median_abs: float
    correlation: float
    largest: tuple[tuple[date, float, str], ...]


def plot_two_sources(series: Sequence[GapSeries]) -> Figure:
    fig = new_figure(14.0, 10.0)
    headline = series[0]
    title_block(
        fig,
        "Two central banks, one exchange rate: the ECB's fix against the Fed's",
        "The same rates fixed 3h45 apart - 14:15 in Frankfurt, noon in New York. The gap is not an error: the "
        "later fix has seen more of the day, and already shows part of tomorrow's ECB move.",
    )
    top = fig.add_axes((0.06, 0.55, 0.90, 0.30))
    x = [x_of(day) for day in headline.days]
    top.plot(x, headline.gaps, color=PALETTE["navy"], lw=0.5, alpha=0.8)
    top.axhline(0, color=PALETTE["muted"], lw=0.6)
    for day, gap, label in headline.largest:
        top.annotate(label, (x_of(day), gap), textcoords="offset points", xytext=(8, 4 if gap > 0 else -3),
                     fontsize=7.8, color=PALETTE["accent"], fontweight="bold")  # fmt: skip
        top.scatter([x_of(day)], [gap], color=PALETTE["accent"], s=22, zorder=4)
    top.set_ylim(min(headline.gaps) * 1.25, max(headline.gaps) * 1.25)
    top.xaxis_date()
    style_axes(top, title=f"{headline.pair}: Fed noon minus ECB 14:15, basis points, every day both fixed",
               ylabel="bp", grid="y")  # fmt: skip

    for index, item in enumerate(series):
        ax = fig.add_axes((0.06 + index * 0.235, 0.08, 0.20, 0.34))
        sample = slice(None, None, 3)
        ax.scatter(item.next_move[sample], item.gaps[sample], s=3, color=PALETTE["teal"], alpha=0.35, lw=0)
        limit = 150
        ax.set_xlim(-limit, limit)
        ax.set_ylim(-limit, limit)
        ax.axhline(0, color=PALETTE["muted"], lw=0.5)
        ax.axvline(0, color=PALETTE["muted"], lw=0.5)
        style_axes(ax, title=item.pair, xlabel="next ECB move, bp", ylabel="Fed - ECB, bp" if index == 0 else None,
                   grid="both")  # fmt: skip
        ax.text(0.04, 0.95, f"median |gap| {item.median_abs:.0f} bp\ncorrelation {item.correlation:.2f}",
                transform=ax.transAxes, fontsize=8, va="top", color=PALETTE["ink"],
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85})  # fmt: skip
    caption(fig, "Sources: ECB reference rates (14:15 CET); Federal Reserve H.10 noon buying rates in New York, via "
                 "FRED. GBPUSD, USDCHF and USDJPY are ECB crosses of two euro fixings.")  # fmt: skip
    return fig


@dataclass(frozen=True)
class Fix:
    name: str
    hour_utc_winter: float
    hour_utc_summer: float
    colour: str


def plot_fixing_clock(fixes: Sequence[Fix], gaps: Sequence[tuple[str, float, float]]) -> Figure:
    fig = new_figure(14.0, 6.8)
    title_block(
        fig,
        "When is 'the' price? The world's FX fixes on one UTC day",
        "A golden copy that blends sources must blend the same moment. Each fix in UTC, winter and summer: "
        "daylight saving moves them, and not on the same weekends.",
    )
    ax = fig.add_axes((0.05, 0.36, 0.90, 0.46))
    for row, fix in enumerate(fixes):
        y = len(fixes) - 1 - row
        ax.plot([fix.hour_utc_summer], [y], marker="o", ms=15, color=fix.colour, mfc="white", mew=2)
        ax.plot([fix.hour_utc_winter], [y], marker="o", ms=9, color=fix.colour)
        if fix.hour_utc_summer == fix.hour_utc_winter:
            ax.text(fix.hour_utc_winter + 0.35, y, "no daylight saving", va="center", fontsize=8,
                    color=PALETTE["muted"])  # fmt: skip
        ax.text(-0.3, y, fix.name, ha="right", va="center", fontsize=9.5, color=PALETTE["ink"], fontweight="bold")
    ax.set_xlim(-0.2, 24)
    ax.set_xticks(range(0, 25, 2), [f"{hour:02d}:00" for hour in range(0, 25, 2)], fontsize=8)
    ax.set_yticks([])
    ax.set_ylim(-0.7, len(fixes) - 0.3)
    style_axes(ax, xlabel="UTC", grid="x")
    ax.spines["left"].set_visible(False)
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=PALETTE["slate"], ms=9, label="winter"),
                       Line2D([], [], marker="o", ls="", color=PALETTE["slate"], mfc="white", mew=2, ms=9,
                              label="summer")], loc="upper right", frameon=False, fontsize=8.5)  # fmt: skip
    low = fig.add_axes((0.25, 0.08, 0.50, 0.17))
    labels = [label for label, _, _ in gaps]
    low.barh(range(len(gaps)), [value for _, value, _ in gaps], color=PALETTE["teal"], height=0.5, label="usual")
    low.barh([index + 0.0 for index in range(len(gaps))], [value for _, _, value in gaps], color="none",
             edgecolor=PALETTE["accent"], height=0.5, lw=1.5, label="when US and EU clocks disagree")  # fmt: skip
    low.set_yticks(range(len(gaps)), labels, fontsize=8.5)
    style_axes(low, xlabel="hours between the fixes", grid="x")
    low.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=8)
    return fig


# ---------------------------------------------------------------------------- the review fixes
def plot_pence_trap(days: Sequence[date], raw: Sequence[float], correct: Sequence[float], naive: Sequence[float],
                    ex_days: Sequence[date], payout_correct: float, payout_naive: float) -> Figure:  # fmt: skip
    fig = new_figure(13.5, 7.6)
    title_block(
        fig,
        "The pence trap: a sterling dividend on a share quoted in pence",
        f"London quotes in pence (GBX); dividends are declared in pounds. Set against the price as it stands, a "
        f"payout of {payout_correct:.2%} reads as {payout_naive:.4%} - and the adjusted history barely moves.",
    )
    ax = fig.add_axes((0.07, 0.12, 0.62, 0.72))
    x = [x_of(day) for day in days]
    ax.plot(x, raw, color=PALETTE["muted"], lw=1.0, label="raw close, pence")
    ax.plot(x, correct, color=PALETTE["teal"], lw=2.0, label="total-return adjusted, dividend in pence (correct)")
    ax.plot(x, naive, color=PALETTE["loss"], lw=1.2, ls="--", label="adjusted with the dividend read as pence")
    for day in ex_days:
        ax.axvline(x_of(day), color=PALETTE["accent"], lw=0.8, ls=":")
    ax.xaxis_date()
    style_axes(ax, ylabel="pence", grid="y")
    ax.legend(loc="upper left", frameon=False, fontsize=8.5)
    side = fig.add_axes((0.73, 0.12, 0.25, 0.72))
    side.bar([0, 1], [payout_correct * 100, payout_naive * 100], color=[PALETTE["teal"], PALETTE["loss"]], width=0.6)
    side.set_xticks([0, 1], ["in pence\n(correct)", "as declared\n(v1.1.0)"])
    for index, value in enumerate([payout_correct * 100, payout_naive * 100]):
        side.text(index, value, f"{value:.3f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")
    style_axes(side, title="Each dividend as a share of the price", ylabel="%", grid="y")
    caption(fig, "A demonstration series: a 1,950p share paying 19.8p twice a year. The same restatement converts a "
                 "dollar dividend through an exchange rate, which it requires.")  # fmt: skip
    return fig


def plot_missing_ex_date(days: Sequence[date], before: Sequence[float], after: Sequence[float], ex_date: date,
                         flagged_before: int, flagged_after: int) -> Figure:  # fmt: skip
    fig = new_figure(13.5, 6.6)
    title_block(
        fig,
        "A 4-for-1 split on a day the feed had no print",
        "The event was matched to a price on its ex-date; with no price that day it was never divided out, and the "
        "split scored as the worst bad tick of the year. Every event between two prints now counts.",
    )
    ax = fig.add_axes((0.07, 0.14, 0.88, 0.70))
    x = [x_of(day) for day in days]
    ax.bar(x, np.asarray(before) * 100, width=0.9, color=PALETTE["loss"], alpha=0.55,
           label=f"v1.1.0: {flagged_before} finding(s)")  # fmt: skip
    ax.bar(x, np.asarray(after) * 100, width=0.5, color=PALETTE["teal"], label=f"now: {flagged_after} finding(s)")
    ax.axvline(x_of(ex_date), color=PALETTE["accent"], lw=1.0, ls="--")
    ax.text(x_of(ex_date), min(before) * 100 * 0.9, "  ex-date: no print", color=PALETTE["accent"], fontsize=9,
            fontweight="bold")  # fmt: skip
    ax.xaxis_date()
    style_axes(ax, ylabel="adjusted daily log return, %", grid="y")
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    return fig


# ---------------------------------------------------------------------------- the work queue
def plot_open_findings(rows: Sequence[tuple[str, date, str, str]], explained: int) -> Figure:
    fig = new_figure(14.0, max(6.0, 0.38 * len({row[0] for row in rows}) + 2.6))
    title_block(
        fig,
        f"What is left for a person: {len(rows)} findings from 27 years, after {explained} were explained",
        "Every open finding, by currency and date - the work queue a data team would take to the source. "
        "The krona frozen in October 2008 is a genuine fault in the ECB's history.",
    )
    ax = fig.add_axes((0.10, 0.06, 0.86, 0.82))
    currencies = sorted({row[0] for row in rows})
    lookup = {currency: index for index, currency in enumerate(currencies)}
    for pair, day, rule, _ in rows:
        ax.scatter([x_of(day)], [lookup[pair]], s=46, color=RULE_COLOURS.get(rule, PALETTE["slate"]),
                   edgecolor="white", lw=0.6, zorder=3)  # fmt: skip
    ax.set_yticks(range(len(currencies)), currencies, fontsize=8.5)
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.YearLocator(3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(x_of(date(1998, 6, 1)), x_of(date(2027, 1, 1)))
    style_axes(ax, grid="x")
    handles = [Line2D([], [], marker="o", ls="", color=colour, label=RULE_NAMES[rule])
               for rule, colour in RULE_COLOURS.items() if any(row[2] == rule for row in rows)]  # fmt: skip
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=8.5, ncol=4)
    return fig
