"""Charts for compliance: how close to every limit, when the limits broke, and what trading would be stopped.

A compliance officer's day, one chart per question:

* **Where are we against every limit?** The limit-utilisation panel: each rule's
  distance to its limit, with its warning level.
* **When did we break them, and who broke them?** The breach timeline, active
  and passive; the register by cause, severity and resolution; a month-by-month
  map of utilisation.
* **What do the funds hide?** Issuer exposure direct and looked through, and the
  Microsoft limit over time.
* **What would a pre-trade check have stopped?** Today's test orders with the
  largest permissible size; the book's own history replayed, order by order and
  as baskets.
* **How is a rule read?** The parse tree of a rule of the mandate language.
* **The page the compliance committee reads.**

Colours follow status: green passes, amber warns, red breaches; violet marks an
active breach (a trade caused it), sky a passive one (the market did).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, Patch

from .accounting import _margins
from .style import PALETTE, caption, new_figure, style_axes, title_block, x_of

STATUS_COLOURS = {
    "pass": PALETTE["gain"],
    "warning": "#D9A21B",
    "breach": PALETTE["loss"],
    "not evaluable": PALETTE["grid"],
}
KIND_COLOURS = {"active": PALETTE["violet"], "passive": PALETTE["sky"]}
DECISION_COLOURS = {
    "allowed": PALETTE["gain"],
    "warning": "#D9A21B",
    "override required": PALETTE["accent"],
    "blocked": PALETTE["loss"],
}
_UTILISATION = LinearSegmentedColormap.from_list(
    "utilisation", ["#F4F7FB", "#CFE8DB", "#8CC5A6", "#F2D48A", "#E07A29", "#B3202C"], N=256
)

UtilisationRow = tuple[
    str, str, str, float | None, str, str, str
]  # id, title, category, utilisation, status, value, limit


def _pct(value: float, places: int = 1) -> str:
    return f"{value:.{places}%}"


def _percent_axis(axis, which: str = "y", places: int = 0) -> None:  # type: ignore[no-untyped-def]
    formatter = lambda value, _: f"{value:.{places}%}"  # noqa: E731
    (axis.yaxis if which == "y" else axis.xaxis).set_major_formatter(formatter)


# ---------------------------------------------------------------------------- 1. limit utilisation
def plot_limit_utilisation(
    rows: Sequence[UtilisationRow], warn_levels: Mapping[str, float], day: date, counts: Mapping[str, int]
) -> Figure:
    """Every rule's utilisation of its limit, grouped by category, with the warning level marked."""
    figure = new_figure(15.8, 10.0)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, left=0.27, right=0.86))
    axis = figure.add_subplot(grid[0])
    positions = []
    labels = []
    position = 0.0
    previous_category = None
    for row in rows:
        rule_id, title, category, used, status, value, limit = row
        if category != previous_category:
            if previous_category is not None:
                position += 0.7
            axis.text(
                -0.005,
                position - 0.62,
                category.upper(),
                transform=axis.get_yaxis_transform(),
                ha="right",
                fontsize=7.5,
                color=PALETTE["muted"],
                weight="bold",
            )
            previous_category = category
        width = 0.0 if used is None else min(used, 1.35)
        axis.barh(position, width, height=0.62, color=STATUS_COLOURS[status])
        if used is not None and used > 1.35:
            axis.text(1.35, position, " >", va="center", fontsize=8, color=PALETTE["loss"], weight="bold")
        if rule_id in warn_levels:
            axis.plot(
                [warn_levels[rule_id]] * 2, [position - 0.36, position + 0.36], color=PALETTE["ink"], linewidth=1.3
            )
        axis.text(
            1.02,
            position,
            f"{value}  (limit {limit})",
            transform=axis.get_yaxis_transform(),
            va="center",
            fontsize=8,
            color=PALETTE["ink"],
            clip_on=False,
        )
        positions.append(position)
        labels.append(title)
        position += 1.0
    axis.axvline(1.0, color=PALETTE["loss"], linewidth=1.4)
    axis.text(1.0, -1.0, "limit", ha="center", fontsize=8, color=PALETTE["loss"])
    axis.set_yticks(positions, labels=labels, fontsize=8.6)
    axis.invert_yaxis()
    axis.set_xlim(0, 1.4)
    _percent_axis(axis, "x")
    style_axes(axis, title="Utilisation: the share of each limit in use", grid="x")
    handles = [Patch(color=STATUS_COLOURS[s], label=f"{s} ({counts.get(s, 0)})") for s in ("pass", "warning", "breach")]
    handles.append(Patch(color=PALETTE["ink"], label="warning level"))
    axis.legend(handles=handles, loc="lower right", fontsize=8)
    title_block(
        figure,
        f"Headroom against every rule of the mandate, {day:%d %B %Y}",
        "A bar at 100% is at its limit. Lower limits are drawn the same way (limit over value), so every bar reads "
        "alike: "
        "the further right, the closer to a breach.",
    )
    caption(
        figure,
        "Utilisation of a 'no holdings' rule is zero while nothing is held. The tick is the early-warning level.",
    )
    return figure


# ---------------------------------------------------------------------------- 2. breach timeline
def plot_breach_timeline(
    rules: Sequence[tuple[str, str]],
    breaches: Sequence[tuple[str, date, date | None, str, str]],
    start: date,
    end: date,
) -> Figure:
    """``rules``: (rule_id, title); ``breaches``: (rule_id, opened, closed, kind, severity)."""
    figure = new_figure(15.8, 7.8)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, left=0.25))
    axis = figure.add_subplot(grid[0])
    row_of = {rule_id: index for index, (rule_id, _) in enumerate(rules)}
    for rule_id, opened, closed, kind, severity in breaches:
        row = row_of[rule_id]
        finish = closed or end
        axis.barh(
            row,
            max((finish - opened).days, 1),
            left=x_of(opened),
            height=0.56,
            color=KIND_COLOURS[kind],
            edgecolor=PALETTE["ink"] if severity == "hard" else "none",
            linewidth=1.0,
            alpha=0.95,
        )
    axis.set_yticks(range(len(rules)), labels=[title for _, title in rules], fontsize=8.4)
    axis.invert_yaxis()
    axis.set_xlim(x_of(start), x_of(end))
    axis.xaxis_date()
    style_axes(axis, title="Every breach, from the day it opened to the day it closed", grid="x")
    handles = [
        Patch(color=KIND_COLOURS["active"], label="active: a trade caused it"),
        Patch(color=KIND_COLOURS["passive"], label="passive: the market moved"),
        Patch(facecolor="white", edgecolor=PALETTE["ink"], label="outlined: a hard limit"),
    ]
    axis.legend(handles=handles, loc="lower right", fontsize=8)
    title_block(
        figure,
        "The breach register over two and a half years",
        "The demonstration book was traded before the mandate engine existed. Replayed through the mandate, most "
        "breaches are passive - prices carried a position over a line - and most close within days.",
    )
    caption(
        figure,
        "Rules that were never breached have empty rows. Breaches open on the first day in breach and close on the "
        "first day back within.",
    )
    return figure


# ---------------------------------------------------------------------------- 3. utilisation heatmap
def plot_utilisation_heatmap(rule_titles: Sequence[str], months: Sequence[str], matrix: np.ndarray) -> Figure:
    """``matrix``: rules x months, the highest utilisation of the month (NaN if not evaluable)."""
    figure = new_figure(15.8, 8.6)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.1, left=0.25, right=0.92))
    axis = figure.add_subplot(grid[0])
    shown = np.clip(np.nan_to_num(matrix, nan=0.0), 0, 1.3)
    image = axis.imshow(shown, cmap=_UTILISATION, vmin=0, vmax=1.3, aspect="auto")
    for (row, column), value in np.ndenumerate(matrix):
        if np.isfinite(value) and value > 1.0:
            axis.text(column, row, "x", ha="center", va="center", fontsize=7, color="white", weight="bold")
    axis.set_yticks(range(len(rule_titles)), labels=rule_titles, fontsize=8.2)
    axis.set_xticks(range(len(months)), labels=months, fontsize=6.8, rotation=90)
    axis.grid(visible=False)
    axis.set_title("Highest utilisation in each month (x: breached)")
    bar = figure.colorbar(image, ax=axis, fraction=0.02, pad=0.01)
    bar.ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    title_block(
        figure,
        "Month by month: which limits are close, and which were crossed",
        "Concentration and sector limits run hot throughout - the account holds a few large technology names directly "
        "and again inside its index funds. Allocation limits break only when a client deposit lands.",
    )
    caption(
        figure,
        "Utilisation above 100% is a breach. Risk-metric rules start once the risk model has ninety days of history.",
    )
    return figure


# ---------------------------------------------------------------------------- 4. the Microsoft limit
def plot_issuer_limits(
    days: Sequence[date],
    direct: Sequence[float],
    looked: Sequence[float],
    limits: Mapping[str, float],
    issuer: str,
) -> Figure:
    figure = new_figure(15.8, 7.4)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, right=0.86))
    axis = figure.add_subplot(grid[0])
    looked_array, direct_array = np.asarray(looked), np.asarray(direct)
    axis.fill_between(
        days,
        limits["look-through limit"],
        looked_array,
        where=looked_array > limits["look-through limit"],
        color=PALETTE["violet"],
        alpha=0.25,
        linewidth=0,
        label="over the look-through limit",
    )
    axis.fill_between(
        days,
        limits["direct limit"],
        direct_array,
        where=direct_array > limits["direct limit"],
        color=PALETTE["loss"],
        alpha=0.35,
        linewidth=0,
        label="over the direct limit",
    )
    axis.plot(days, looked, color=PALETTE["violet"], linewidth=1.8, label=f"{issuer} including index funds")
    axis.plot(days, direct, color=PALETTE["navy"], linewidth=1.8, label=f"{issuer} held directly")
    styles = {
        "direct limit": ("--", PALETTE["navy"]),
        "look-through limit": ("--", PALETTE["violet"]),
        "direct warning": (":", PALETTE["navy"]),
        "look-through warning": (":", PALETTE["violet"]),
    }
    for label, level in limits.items():
        line, colour = styles[label]
        axis.axhline(level, color=colour, linestyle=line, linewidth=1.0)
        axis.text(
            1.01,
            level,
            f"{label} {level:.1%}",
            transform=axis.get_yaxis_transform(),
            va="center",
            fontsize=7.8,
            color=colour,
            clip_on=False,
        )
    _percent_axis(axis, places=0)
    style_axes(axis, title=f"{issuer} as a share of the account")
    axis.legend(loc="upper left", fontsize=8.5, ncol=2)
    axis.set_xlim(x_of(days[0]), x_of(days[-1]))
    title_block(
        figure,
        "What the index funds hide: one issuer, two limits",
        "Held directly, Microsoft stays mostly under its hard limit. Counted with the Microsoft inside the S&P 500 and "
        "world funds it is half as large again, and the soft look-through limit is where the breaches happen.",
    )
    caption(
        figure,
        "Shaded: the days Microsoft itself was over a limit. The register may attribute a breach to Apple on days "
        "Apple was heavier still.",
    )
    return figure


# ---------------------------------------------------------------------------- 5. what the funds hide
def plot_look_through(rows: Sequence[tuple[str, float, float]], exclusions: Sequence[tuple[str, str, float]]) -> Figure:
    """``rows``: (issuer, direct, looked through); ``exclusions``: (constituent, industry, weight via funds)."""
    figure = new_figure(15.8, 7.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.6, 1.0], wspace=0.35, **_margins(figure, bottom=1.0, left=0.1))
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(rows))
    direct = np.array([row[1] for row in rows])
    looked = np.array([row[2] for row in rows])
    axis.barh(positions, direct, height=0.62, color=PALETTE["navy"], label="held directly")
    axis.barh(
        positions,
        looked - direct,
        left=direct,
        height=0.62,
        color=PALETTE["violet"],
        alpha=0.75,
        label="inside index funds",
    )
    for position, (_, _, total) in enumerate(rows):
        axis.text(total, position, f" {total:.1%}", va="center", fontsize=8)
    axis.set_yticks(positions, labels=[row[0] for row in rows], fontsize=8.5)
    axis.invert_yaxis()
    axis.set_xlim(0, float(looked.max()) * 1.2)
    _percent_axis(axis, "x")
    style_axes(axis, title="The largest issuers, direct and looked through", grid="x")
    axis.legend(loc="lower right", fontsize=8)
    side = figure.add_subplot(grid[1])
    side.axis("off")
    side.set_title("Excluded industries reached through the funds", loc="left")
    lines = [f"{name}  ({industry})  {weight:.2%}" for name, industry, weight in exclusions] or ["none"]
    for index, line in enumerate(lines):
        side.text(0.0, 0.9 - 0.09 * index, line, fontsize=9.5, transform=side.transAxes, color=PALETTE["ink"])
    side.text(
        0.0,
        0.9 - 0.09 * (len(lines) + 1),
        "The direct exclusion rule passes; the look-through rule\nwarns. An index fund cannot exclude one company:\n"
        "the choice is a waiver, a different fund, or a limit.",
        fontsize=8.5,
        transform=side.transAxes,
        color=PALETTE["muted"],
    )
    title_block(
        figure,
        "Look-through: the companies inside the index funds",
        "Each fund is replaced by its index's constituents in their weights on the day. Microsoft and Apple are held "
        "twice over; a tobacco company the mandate excludes turns up inside the world fund.",
    )
    caption(figure, "Constituent weights from the Day 4 benchmark on the report date.")
    return figure


# ---------------------------------------------------------------------------- 6. the register
def plot_register(
    by_rule: Sequence[tuple[str, int, int, int, int]],
    durations: Mapping[str, Sequence[int]],
    resolutions: Mapping[str, int],
) -> Figure:
    """``by_rule``: (title, active count, passive count, active days, passive days)."""
    figure = new_figure(15.8, 7.8)
    grid = figure.add_gridspec(
        1, 3, width_ratios=[1.5, 1.0, 0.9], wspace=0.38, **_margins(figure, bottom=1.0, left=0.14)
    )
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(by_rule))
    active = np.array([row[1] for row in by_rule])
    passive = np.array([row[2] for row in by_rule])
    axis.barh(positions, active, height=0.6, color=KIND_COLOURS["active"], label="active")
    axis.barh(positions, passive, left=active, height=0.6, color=KIND_COLOURS["passive"], label="passive")
    for position, row in enumerate(by_rule):
        axis.text(row[1] + row[2], position, f"  {row[3] + row[4]} days", va="center", fontsize=8)
    axis.set_yticks(positions, labels=[row[0] for row in by_rule], fontsize=8.4)
    axis.invert_yaxis()
    axis.set_xlim(0, float((active + passive).max()) * 1.45)
    style_axes(axis, title="Breaches by rule, and days spent in breach", grid="x")
    axis.legend(loc="lower right", fontsize=8)
    spread = figure.add_subplot(grid[1])
    for index, (kind, values) in enumerate(durations.items()):
        jitter = np.random.default_rng(index).uniform(-0.15, 0.15, len(values))
        spread.scatter(
            index + jitter,
            values,
            s=34,
            color=KIND_COLOURS[kind],
            edgecolor=PALETTE["surface"],
            linewidth=0.8,
            zorder=3,
        )
        if values:
            spread.plot(
                [index - 0.25, index + 0.25], [float(np.median(values))] * 2, color=PALETTE["ink"], linewidth=1.5
            )
    spread.set_yscale("log")
    spread.set_xticks(range(len(durations)), labels=list(durations))
    spread.set_xlim(-0.6, len(durations) - 0.4)
    style_axes(spread, title="How long they lasted (days, log)")
    ends = figure.add_subplot(grid[2])
    names = list(resolutions)
    ends.bar(
        range(len(names)),
        [resolutions[name] for name in names],
        color=[PALETTE["teal"], PALETTE["slate"], PALETTE["loss"]][: len(names)],
        width=0.6,
    )
    for position, name in enumerate(names):
        ends.text(
            position, resolutions[name], f"{resolutions[name]}", ha="center", va="bottom", fontsize=9, weight="bold"
        )
    ends.set_xticks(range(len(names)), labels=[name.replace("resolved by ", "by ") for name in names], fontsize=8.5)
    style_axes(ends, title="How they ended")
    title_block(
        figure,
        "The breach register: cause, duration, and resolution",
        "Active breaches came from trades and should never have happened; passive ones came from prices and are cured "
        "within a grace period. The line is each group's median duration.",
    )
    caption(
        figure, "Passive breaches have thirty calendar days to be cured; active ones must be reversed the same day."
    )
    return figure


# ---------------------------------------------------------------------------- 7. pre-trade decisions
def plot_pretrade(rows: Sequence[tuple[str, str, str, float, float, str, str]]) -> Figure:
    """``rows``: (order id, side, instrument, amount, maximum, decision, reason)."""
    figure = new_figure(15.8, 7.4)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, left=0.22, right=0.7))
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(rows))
    for position, (_, _, _, amount, maximum, decision, reason) in enumerate(rows):
        axis.barh(position, maximum, height=0.62, color=PALETTE["grid"])
        axis.barh(position, amount, height=0.3, color=DECISION_COLOURS[decision])
        axis.plot([maximum, maximum], [position - 0.34, position + 0.34], color=PALETTE["ink"], linewidth=1.4)
        axis.text(
            1.01,
            position,
            f"{decision}" + (f" - {reason}" if reason else ""),
            transform=axis.get_yaxis_transform(),
            va="center",
            fontsize=8.2,
            color=PALETTE["ink"],
            clip_on=False,
        )
    axis.set_yticks(positions, labels=[f"{side} {instrument}" for _, side, instrument, *_ in rows], fontsize=8.8)
    axis.invert_yaxis()
    axis.xaxis.set_major_formatter(lambda value, _: f"{value / 1e3:,.0f}k")
    style_axes(
        axis, title="The order requested (coloured), and the largest the hard limits allow (grey, tick)", grid="x"
    )
    handles = [Patch(color=colour, label=name) for name, colour in DECISION_COLOURS.items()]
    axis.legend(handles=handles, loc="lower right", fontsize=8)
    title_block(
        figure,
        "Pre-trade: every order checked before it is sent",
        "Each order is applied to today's portfolio and every rule is run again. Hard limits block, soft limits need "
        "an "
        "override, and the checker finds the largest size that would pass by bisection.",
    )
    caption(
        figure, "Tracking error and volatility are re-forecast by the Day 5 risk model for each proposed portfolio."
    )
    return figure


# ---------------------------------------------------------------------------- 8. the history replayed
def plot_replay(rows: Sequence[tuple[date, str, str, float, str, str]]) -> Figure:
    """``rows``: (day, side, instrument, amount, decision alone, decision in basket)."""
    figure = new_figure(15.8, 7.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[2.0, 1.0], wspace=0.25, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    order = list(DECISION_COLOURS)
    for day, side, _, amount, alone, basket in rows:
        y = order.index(alone)
        marker = "^" if side == "buy" else "v"
        axis.scatter(
            [x_of(day)],
            [y + (0.12 if side == "buy" else -0.12)],
            s=max(amount / 2500, 18),
            marker=marker,
            color=DECISION_COLOURS[alone],
            edgecolor=PALETTE["ink"] if basket != "allowed" else "none",
            linewidth=1.0,
            alpha=0.9,
        )
    axis.set_yticks(range(len(order)), labels=order)
    axis.set_ylim(-0.6, len(order) - 0.4)
    axis.xaxis_date()
    style_axes(axis, title="Each historical order, checked on its own (▲ buy, ▼ sell; size by amount)", grid="x")
    counts = figure.add_subplot(grid[1])
    alone_counts = [sum(1 for row in rows if row[4] == name) for name in order]
    days = {}
    for row in rows:
        days[row[0]] = row[5]
    basket_counts = [sum(1 for value in days.values() if value == name) for name in order]
    positions = np.arange(len(order))
    counts.barh(
        positions + 0.19,
        alone_counts,
        height=0.36,
        color=[DECISION_COLOURS[name] for name in order],
        label="orders, one at a time",
    )
    counts.barh(
        positions - 0.19,
        basket_counts,
        height=0.36,
        color=[DECISION_COLOURS[name] for name in order],
        alpha=0.45,
        hatch="///",
        edgecolor=PALETTE["surface"],
        label="trading days, as baskets",
    )
    for position in positions:
        counts.text(alone_counts[position], position + 0.19, f" {alone_counts[position]}", va="center", fontsize=8)
        counts.text(basket_counts[position], position - 0.19, f" {basket_counts[position]}", va="center", fontsize=8)
    counts.set_yticks(positions, labels=order)
    counts.invert_yaxis()
    style_axes(counts, title="Orders alone, against days as baskets", grid="x")
    counts.legend(loc="lower right", fontsize=7.8)
    title_block(
        figure,
        "The book's own history, put through the pre-trade check it never had",
        "Checked one at a time, a rebalance looks like a cash breach and an overdraft; checked as the day's basket, "
        "most "
        "are fine. Outlined markers are days the basket itself would have been stopped or needed an override.",
    )
    caption(
        figure,
        "Each order against the portfolio of the evening before. Risk metrics are not re-forecast for past days.",
    )
    return figure


# ---------------------------------------------------------------------------- 9. UCITS screen
def plot_ucits(
    days: Sequence[date],
    layers: Mapping[str, Sequence[float]],
    five_ten_forty: Sequence[float],
    today: Sequence[tuple[str, float]],
) -> Figure:
    figure = new_figure(15.8, 7.8)
    grid = figure.add_gridspec(1, 2, width_ratios=[2.0, 1.0], wspace=0.25, **_margins(figure, bottom=1.4))
    axis = figure.add_subplot(grid[0])
    colours = [
        PALETTE["navy"],
        PALETTE["teal"],
        PALETTE["violet"],
        PALETTE["sky"],
        PALETTE["slate"],
        PALETTE["gain"],
        "#8C6BB1",
        "#5FA8D3",
    ]
    axis.stackplot(days, *layers.values(), labels=list(layers), colors=colours[: len(layers)], alpha=0.85)
    axis.plot(days, five_ten_forty, color=PALETTE["ink"], linewidth=1.2)
    axis.axhline(0.40, color=PALETTE["loss"], linewidth=1.4, linestyle="--")
    axis.annotate(
        "40%: the UCITS ceiling",
        (days[0], 0.40),
        xytext=(4, 4),
        textcoords="offset points",
        fontsize=8.5,
        color=PALETTE["loss"],
    )
    _percent_axis(axis)
    style_axes(axis, title="Issuers above 5% of the fund, stacked")
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), fontsize=7.8, ncol=len(layers))
    bars = figure.add_subplot(grid[1])
    positions = np.arange(len(today))
    bars.barh(
        positions,
        [value for _, value in today],
        color=[
            PALETTE["loss"] if value > 0.10 else PALETTE["navy"] if value > 0.05 else PALETTE["grid"]
            for _, value in today
        ],
        height=0.6,
    )
    bars.axvline(0.05, color=PALETTE["muted"], linewidth=1.0, linestyle=":")
    bars.axvline(0.10, color=PALETTE["loss"], linewidth=1.2, linestyle="--")
    for position, (_, value) in enumerate(today):
        bars.text(value, position, f" {value:.1%}", va="center", fontsize=8)
    bars.set_yticks(positions, labels=[name for name, _ in today], fontsize=8.5)
    bars.invert_yaxis()
    _percent_axis(bars, "x")
    style_axes(bars, title="Today, issuer by issuer (5% and 10% lines)", grid="x")
    title_block(
        figure,
        "Would the account qualify as a UCITS fund? No - by design",
        "UCITS caps any issuer at 10% and the issuers above 5% at 40% together. A concentrated account of seven large "
        "positions fails both; the same mandate language states the directive as four rules.",
    )
    caption(figure, "UCITS Directive 2009/65/EC, article 52(2). A what-if on the account, not one of its own limits.")
    return figure


# ---------------------------------------------------------------------------- 10. a rule, parsed
def plot_rule_tree(text: str, tree: tuple[str, list]) -> Figure:
    """``tree``: (label, children) - the rule as the parser builds it."""
    figure = new_figure(15.8, 8.0)
    grid = figure.add_gridspec(2, 1, height_ratios=[0.22, 1.0], hspace=0.1, **_margins(figure, bottom=0.9))
    source = figure.add_subplot(grid[0])
    source.axis("off")
    source.text(
        0.0,
        0.5,
        text,
        family="monospace",
        fontsize=11.5,
        va="center",
        color=PALETTE["ink"],
        bbox={"boxstyle": "round,pad=0.6", "facecolor": PALETTE["band"], "edgecolor": PALETTE["grid"]},
    )
    axis = figure.add_subplot(grid[1])
    axis.axis("off")
    positions: dict[int, tuple[float, float]] = {}
    labels: dict[int, str] = {}
    edges: list[tuple[int, int]] = []
    counter = [0]

    def leaves(node: tuple[str, list]) -> int:
        return 1 if not node[1] else sum(leaves(child) for child in node[1])

    def layout(node: tuple[str, list], depth: int, left: float, right: float) -> int:
        identifier = counter[0]
        counter[0] += 1
        label, children = node
        labels[identifier] = label
        positions[identifier] = ((left + right) / 2, -depth)
        total = sum(leaves(child) for child in children)
        start = left
        for child in children:
            share = (right - left) * leaves(child) / total
            child_id = layout(child, depth + 1, start, start + share)
            edges.append((identifier, child_id))
            start += share
        return identifier

    layout(tree, 0, 0.0, 1.0)
    depth = max(-y for _, y in positions.values()) or 1
    for parent, child in edges:
        (x0, y0), (x1, y1) = positions[parent], positions[child]
        axis.plot([x0, x1], [y0, y1], color=PALETTE["grid"], linewidth=1.4, zorder=1)
    for identifier, (x, y) in positions.items():
        label = labels[identifier]
        leaf = not any(parent == identifier for parent, _ in edges)
        colour = PALETTE["band"] if leaf else PALETTE["navy"]
        text_colour = PALETTE["ink"] if leaf else "white"
        width = 0.0068 * max(len(line) for line in label.split("\n")) + 0.03
        axis.add_patch(
            FancyBboxPatch(
                (x - width / 2, y - 0.18),
                width,
                0.36,
                boxstyle="round,pad=0.02",
                facecolor=colour,
                edgecolor=PALETTE["navy"],
                linewidth=1.0,
                zorder=2,
            )
        )
        axis.text(x, y, label, ha="center", va="center", fontsize=8.2, color=text_colour, zorder=3)
    axis.set_xlim(-0.02, 1.02)
    axis.set_ylim(-depth - 0.5, 0.5)
    title_block(
        figure,
        "How a rule is read: from the mandate's words to the objects the engine checks",
        "The Lark grammar parses each rule into a tree of typed parts - the measure, its filter, the bound, the "
        "warning "
        "level. Printing the tree gives back the same text, which a property test checks on generated rules.",
    )
    caption(figure, "LALR(1) parsing: linear in the length of the mandate, with the line and column of any error.")
    return figure


# ---------------------------------------------------------------------------- 11. allocation bands
def plot_allocation_bands(
    days: Sequence[date], series: Mapping[str, Sequence[float]], bands: Mapping[str, tuple[float, float]]
) -> Figure:
    figure = new_figure(15.8, 8.4)
    grid = figure.add_gridspec(len(series), 1, hspace=0.45, **_margins(figure, bottom=0.95))
    colours = {"Equities": PALETTE["navy"], "Fixed income": PALETTE["teal"], "Cash": PALETTE["sky"]}
    for row, (name, values) in enumerate(series.items()):
        axis = figure.add_subplot(grid[row])
        low, high = bands[name]
        axis.axhspan(low, high, color=PALETTE["band"], zorder=0)
        values_array = np.asarray(values)
        axis.plot(days, values_array, color=colours.get(name, PALETTE["navy"]), linewidth=1.6)
        outside = (values_array < low - 1e-12) | (values_array > high + 1e-12)
        axis.fill_between(
            days,
            values_array,
            np.clip(values_array, low, high),
            where=outside,
            color=PALETTE["loss"],
            alpha=0.35,
            linewidth=0,
        )
        axis.axhline(low, color=PALETTE["muted"], linewidth=0.8, linestyle="--")
        axis.axhline(high, color=PALETTE["muted"], linewidth=0.8, linestyle="--")
        _percent_axis(axis)
        style_axes(axis, title=f"{name}: band {low:.0%} to {high:.0%}")
    title_block(
        figure,
        "Asset allocation against the mandate's bands",
        "The client's half-million deposit in March 2025 arrived as cash: cash rose past its 10% ceiling and equities "
        "fell below their 70% floor until it was invested - passive breaches, cured by trading.",
    )
    caption(figure, "Red: outside the band. Weights of net asset value, cash including receivables and payables.")
    return figure


# ---------------------------------------------------------------------------- 12. the report
def plot_compliance_report(
    name: str,
    day: date,
    tiles: Sequence[tuple[str, str]],
    rows: Sequence[UtilisationRow],
    breaches: Sequence[tuple[str, date, date | None, str, str]],
    rule_titles: Sequence[tuple[str, str]],
    decisions: Sequence[tuple[str, str, str]],
    start: date,
) -> Figure:
    figure = new_figure(11.7, 16.5)
    grid = figure.add_gridspec(
        4, 1, height_ratios=[0.5, 1.6, 1.0, 0.7], hspace=0.45, **_margins(figure, top=1.5, bottom=0.8, left=0.3)
    )
    header = figure.add_subplot(grid[0])
    header.axis("off")
    for index, (label, value) in enumerate(tiles):
        x = -0.35 + index * 0.33
        header.text(x, 0.75, label, fontsize=9, color=PALETTE["muted"], transform=header.transAxes)
        header.text(x, 0.3, value, fontsize=20, weight="bold", color=PALETTE["ink"], transform=header.transAxes)
    panel = figure.add_subplot(grid[1])
    positions = np.arange(len(rows))
    panel.barh(
        positions,
        [min(row[3] or 0.0, 1.35) for row in rows],
        color=[STATUS_COLOURS[row[4]] for row in rows],
        height=0.62,
    )
    panel.axvline(1.0, color=PALETTE["loss"], linewidth=1.2)
    panel.set_yticks(positions, labels=[row[1] for row in rows], fontsize=7.8)
    panel.invert_yaxis()
    panel.set_xlim(0, 1.4)
    _percent_axis(panel, "x")
    style_axes(panel, title="Limit utilisation today", grid="x")
    timeline = figure.add_subplot(grid[2])
    row_of = {rule_id: index for index, (rule_id, _) in enumerate(rule_titles)}
    for rule_id, opened, closed, kind, severity in breaches:
        timeline.barh(
            row_of[rule_id],
            max(((closed or day) - opened).days, 1),
            left=x_of(opened),
            height=0.56,
            color=KIND_COLOURS[kind],
            edgecolor=PALETTE["ink"] if severity == "hard" else "none",
        )
    timeline.set_yticks(range(len(rule_titles)), labels=[title for _, title in rule_titles], fontsize=7.4)
    timeline.invert_yaxis()
    timeline.set_xlim(x_of(start), x_of(day))
    timeline.xaxis_date()
    style_axes(timeline, title="Breaches since the mandate took effect (violet active, sky passive)", grid="x")
    orders = figure.add_subplot(grid[3])
    orders.axis("off")
    orders.set_title("Today's test orders", loc="left")
    for index, (label, decision, detail) in enumerate(decisions):
        y = 0.9 - index * 0.12
        orders.text(-0.35, y, label, fontsize=9, transform=orders.transAxes, color=PALETTE["ink"])
        orders.text(
            0.25, y, decision, fontsize=9, transform=orders.transAxes, color=DECISION_COLOURS[decision], weight="bold"
        )
        orders.text(0.48, y, detail, fontsize=8.5, transform=orders.transAxes, color=PALETTE["muted"])
    title_block(
        figure,
        f"{name} - compliance report",
        f"As of {day:%d %B %Y}. The investment restrictions of the mandate, checked.",
    )
    caption(
        figure,
        "Rules written in the Meridian mandate language; every result, breach and order decision is stored with the "
        "rule text that produced it.",
    )
    return figure
