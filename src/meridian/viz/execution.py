"""Charts for execution: what the day's trading cost and why, how the algorithms differ, and what the model knows.

The questions a head of trading answers every morning, one chart each:

* **What did yesterday's trading cost, and where did it go?** The implementation
  shortfall of the day's blocks, split into delay, spread, impact, timing,
  opportunity and fees.
* **How did each algorithm trade?** Schedules against the volume curve; one
  block's fills against the price it moved; our share of each minute's volume.
* **Which algorithm should we have used?** The same blocks re-run with every
  algorithm on the same day; the Almgren-Chriss frontier of cost against risk.
* **Is the cost model right?** Pre-trade estimates against outcomes; the impact
  coefficient recovered from the desk's history against the true one.
* **Did every account get the same deal?** Blocks allocated back to accounts.
* **What does the order's life look like?** Parent and child orders through
  their FIX states.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .accounting import _margins, _money
from .style import PALETTE, caption, new_figure, style_axes, title_block

ALGO_COLOURS = {
    "twap": PALETTE["slate"],
    "vwap": PALETTE["navy"],
    "pov": PALETTE["violet"],
    "is": PALETTE["teal"],
    "close": PALETTE["sky"],
}
ALGO_NAMES = {"twap": "TWAP", "vwap": "VWAP", "pov": "POV", "is": "IS (arrival)", "close": "Close"}
COMPONENT_COLOURS = {
    "delay": PALETTE["sky"],
    "spread": PALETTE["slate"],
    "temporary impact": PALETTE["violet"],
    "permanent impact": "#9C7BC0",
    "timing": PALETTE["navy"],
    "opportunity": "#D9A21B",
    "fees": PALETTE["muted"],
}
STATUS_COLOURS = {
    "new": PALETTE["sky"],
    "partially filled": PALETTE["teal"],
    "filled": PALETTE["gain"],
    "cancelled": PALETTE["grid"],
    "expired": "#D9A21B",
}
AMBER = PALETTE["accent"]


def _bp_axis(axis, which: str = "y") -> None:  # type: ignore[no-untyped-def]
    formatter = lambda value, _: f"{value:,.4g} bp"  # noqa: E731
    (axis.yaxis if which == "y" else axis.xaxis).set_major_formatter(formatter)


def _percent_axis(axis, which: str = "y", places: int = 0) -> None:  # type: ignore[no-untyped-def]
    formatter = lambda value, _: f"{value:.{places}%}"  # noqa: E731
    (axis.yaxis if which == "y" else axis.xaxis).set_major_formatter(formatter)


def _clock(minute: float) -> str:
    total = 9 * 60 + 30 + int(minute)
    return f"{total // 60:02d}:{total % 60:02d}"


def _clock_axis(axis) -> None:  # type: ignore[no-untyped-def]
    ticks = [0, 60, 120, 180, 240, 300, 360, 389]
    axis.set_xticks(ticks, labels=[_clock(tick) for tick in ticks])


# ---------------------------------------------------------------------------- 1. the shortfall
def plot_shortfall(
    components: Mapping[str, float],
    paper_value: float,
    blocks: Sequence[tuple[str, str, float, float, float]],
    trade_date_label: str,
) -> Figure:
    """The day's implementation shortfall as a waterfall of its components, and each block's shortfall.

    ``components`` in base currency (positive a cost); ``blocks`` are (instrument, algorithm, controllable
    cost bp, market cost bp, share of ADV).
    """
    figure = new_figure(15.5, 8.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.25, **_margins(figure, bottom=1.6))
    axis = figure.add_subplot(grid[0])
    names = list(components)
    values = [components[name] / paper_value * 1e4 for name in names]
    running = 0.0
    levels = [0.0]
    for index, (name, value) in enumerate(zip(names, values, strict=True)):
        bottom = running if value >= 0 else running + value
        axis.bar(index, abs(value), bottom=bottom, color=COMPONENT_COLOURS[name], width=0.66)
        axis.text(
            index,
            running + value + (0.6 if value >= 0 else -0.6),
            f"{value:+.1f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=8.4,
        )
        running += value
        levels.append(running)
    axis.bar(len(names), running, color=AMBER if running > 0 else PALETTE["gain"], width=0.66)
    axis.text(
        len(names),
        running + (0.6 if running >= 0 else -0.6),
        f"{running:+.1f}",
        ha="center",
        va="bottom" if running >= 0 else "top",
        fontsize=9,
        weight="bold",
    )
    controllable = sum(components[name] for name in ("spread", "temporary impact", "permanent impact", "fees"))
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.set_xticks(
        range(len(names) + 1), labels=[*[name.replace(" ", "\n") for name in names], "shortfall"], fontsize=8
    )
    margin = 0.18 * (max(levels) - min(levels))
    axis.set_ylim(min(levels) - margin, max(levels) + margin)
    _bp_axis(axis)
    style_axes(axis, title="Where the day's shortfall went (basis points of the orders' value)", grid="y")
    axis.text(
        0.0,
        -0.16,
        f"Costs the desk controls (spread, impact, fees): {controllable / paper_value * 1e4:+.1f} bp, "
        f"{_money(controllable)}\nThe market's own move (delay, timing, opportunity): "
        f"{(running - controllable / paper_value * 1e4):+.1f} bp",
        transform=axis.transAxes,
        va="top",
        fontsize=8.4,
        color=PALETTE["ink"],
        bbox={"facecolor": PALETTE["band"], "edgecolor": "none", "pad": 6},
        clip_on=False,
    )
    side = figure.add_subplot(grid[1])
    ordered = sorted(blocks, key=lambda row: row[2])
    positions = np.arange(len(ordered))
    side.barh(positions, [row[2] for row in ordered], color=[ALGO_COLOURS[row[1]] for row in ordered], height=0.62)
    side.scatter([row[2] + row[3] for row in ordered], positions, s=14, color=PALETTE["ink"], zorder=3)
    side.set_yticks(positions, labels=[f"{row[0]}  ({row[4]:.1%} ADV)" for row in ordered], fontsize=7.4)
    side.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    _bp_axis(side, "x")
    style_axes(side, title="Each block: controllable cost (bar) and total shortfall (dot)", grid="x")
    side.legend(
        handles=[Patch(color=ALGO_COLOURS[name], label=ALGO_NAMES[name]) for name in ("vwap", "is", "pov")]
        + [Line2D([], [], marker="o", color="white", markerfacecolor=PALETTE["ink"], label="total shortfall")],
        loc="lower right",
    )
    title_block(
        figure,
        f"Implementation shortfall of the rebalance, {trade_date_label}",
        f"{len(blocks)} blocks worth {_money(paper_value)} at the decision prices. Against the paper portfolio - every "
        "share at yesterday's close - what the desk paid, and what the market did on its own.",
    )
    caption(
        figure,
        "Perold's shortfall, decomposed exactly: the simulator knows the price path without our trades, so impact and "
        "timing are measured, not estimated. Positive is a cost.",
    )
    return figure


# ---------------------------------------------------------------------------- 2. schedules
def plot_trajectories(
    profile: np.ndarray,
    plans: Mapping[str, np.ndarray],
    realised: Mapping[str, np.ndarray],
    instrument: str,
) -> Figure:
    """Each algorithm's planned and realised completion through the day, against the volume curve."""
    figure = new_figure(15.5, 7.8)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.35, 1.0], wspace=0.22, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    minutes = np.arange(len(profile))
    for name, plan in plans.items():
        axis.plot(minutes, plan, color=ALGO_COLOURS[name], linestyle="--", linewidth=1.2)
        axis.plot(minutes, realised[name], color=ALGO_COLOURS[name], label=ALGO_NAMES[name])
    _percent_axis(axis)
    _clock_axis(axis)
    style_axes(
        axis, title=f"Share of the {instrument} block done (dashed: the plan; solid: what was filled)", grid="both"
    )
    axis.legend(loc="upper left")
    side = figure.add_subplot(grid[1])
    side.bar(minutes, profile, color=PALETTE["grid"], width=1.0)
    side.plot(minutes, np.convolve(profile, np.ones(15) / 15, mode="same"), color=PALETTE["navy"])
    _percent_axis(side, places=2)
    _clock_axis(side)
    style_axes(side, title="The market's expected volume by minute: the U-shape VWAP follows", grid="y")
    title_block(
        figure,
        "Five ways to work the same order",
        "TWAP trades evenly; VWAP with the volume curve; POV with the volume that actually comes; IS front-loads to "
        "cut its exposure to the price; Close waits for the auction-heavy final minutes and cannot always finish.",
    )
    caption(
        figure,
        "Every algorithm is capped at 25% of any minute's volume. The IS trajectory is Almgren-Chriss, urgency kT = 2.",
    )
    return figure


# ---------------------------------------------------------------------------- 3. the Almgren-Chriss frontier
def plot_ac_frontier(
    frontier: Sequence[tuple[float, float, float]],
    trajectories: Sequence[tuple[str, np.ndarray]],
    markers: Sequence[tuple[str, float, float]],
    instrument: str,
    value: float,
) -> Figure:
    """Expected cost against its standard deviation along the Almgren-Chriss frontier, and the trajectories behind "
    "it."""
    figure = new_figure(15.5, 7.8)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.2, 1.0], wspace=0.22, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    costs = np.array([point[1] for point in frontier]) / value * 1e4
    risks = np.array([point[2] for point in frontier]) / value * 1e4
    axis.plot(risks, costs, color=PALETTE["navy"], linewidth=2.2)
    for label, risk, cost in markers:
        colour = AMBER if "chosen" in label else PALETTE["ink"]
        axis.scatter(risk / value * 1e4, cost / value * 1e4, s=80, color=colour, zorder=4, edgecolor="white")
        offset = (-40, 16) if "chosen" in label else (8, 6)
        axis.annotate(
            label,
            (risk / value * 1e4, cost / value * 1e4),
            xytext=offset,
            textcoords="offset points",
            fontsize=8.2,
            color=colour,
            weight="bold" if colour == AMBER else "normal",
        )
    _bp_axis(axis, "x")
    _bp_axis(axis, "y")
    style_axes(
        axis,
        title="Expected cost against its standard deviation",
        xlabel="risk of the cost",
        ylabel="expected cost",
        grid="both",
    )
    side = figure.add_subplot(grid[1])
    for (label, holdings), colour in zip(
        trajectories, (PALETTE["slate"], PALETTE["navy"], PALETTE["teal"], PALETTE["violet"]), strict=False
    ):
        side.plot(np.arange(len(holdings)), holdings / holdings[0], color=colour, label=label)
    _percent_axis(side)
    style_axes(side, title="Shares still to trade", xlabel="minutes after arrival", grid="both")
    side.legend(loc="upper right")
    title_block(
        figure,
        f"Optimal execution: the Almgren-Chriss frontier for the {instrument} block",
        "Trading faster pays more impact and runs less risk of the price moving away. Each point is the optimum for "
        "one "
        "risk aversion; the risk-neutral trader trades evenly (TWAP), the urgent one front-loads.",
    )
    caption(
        figure,
        "Linear temporary impact matched to the simulator's square-root law at the order's own rate; permanent impact "
        "and half-spread included.",
    )
    return figure


# ---------------------------------------------------------------------------- 4. one block, intraday
def plot_intraday(
    unimpacted: np.ndarray,
    impacted: np.ndarray,
    fills: Sequence[tuple[int, float, float]],
    levels: Mapping[str, float],
    instrument: str,
    algorithm: str,
    side: str,
) -> Figure:
    """One block's day: the price with and without our trades, every fill, and the benchmarks."""
    figure = new_figure(15.5, 8.2)
    grid = figure.add_gridspec(2, 1, height_ratios=[2.2, 1.0], hspace=0.28, **_margins(figure, bottom=0.9))
    axis = figure.add_subplot(grid[0])
    minutes = np.arange(len(unimpacted))
    axis.plot(minutes, unimpacted, color=PALETTE["grid"], linewidth=1.6, label="the price had we not traded")
    axis.plot(minutes, impacted, color=PALETTE["navy"], linewidth=1.4, label="the price with our trades")
    if fills:
        sizes = np.array([fill[1] for fill in fills])
        axis.scatter(
            [fill[0] for fill in fills],
            [fill[2] for fill in fills],
            s=8 + 90 * sizes / sizes.max(),
            color=PALETTE["teal"] if side == "buy" else PALETTE["loss"],
            alpha=0.7,
            zorder=3,
            label="our fills",
        )
    styles = {
        "decision": ("dotted", PALETTE["muted"]),
        "arrival": ("dashed", PALETTE["ink"]),
        "average": ("solid", AMBER),
        "VWAP": ("dashdot", PALETTE["violet"]),
    }
    for name, level in levels.items():
        linestyle, colour = styles.get(name, ("dotted", PALETTE["slate"]))
        axis.axhline(level, linestyle=linestyle, color=colour, linewidth=1.2)
        axis.text(len(minutes) - 1, level, f" {name} {level:,.2f}", va="center", fontsize=8, color=colour)
    _clock_axis(axis)
    style_axes(axis, title=f"{instrument}: {side} worked by {ALGO_NAMES[algorithm]}", grid="both")
    axis.legend(loc="upper left")
    lower = figure.add_subplot(grid[1], sharex=axis)
    gap = (impacted - unimpacted) / unimpacted * 1e4
    lower.fill_between(minutes, 0, gap, color=PALETTE["violet"], alpha=0.35)
    lower.plot(minutes, gap, color=PALETTE["violet"])
    _bp_axis(lower)
    _clock_axis(lower)
    style_axes(lower, title="Our permanent impact on the price, basis points", grid="y")
    title_block(
        figure,
        "One block through the day",
        "The grey line is the market the desk never sees: the price had the order not existed. The gap between the "
        "two lines is what the order did to the price; the fills pay half the spread and a temporary impact on top.",
    )
    caption(figure, "Fill area proportional to size. VWAP over the order's own trading window, our trades included.")
    return figure


# ---------------------------------------------------------------------------- 5. algorithms compared
def plot_algorithm_comparison(rows: Sequence[tuple[str, float, float, float, float, float]]) -> Figure:
    """The day's blocks re-run with each algorithm: cost against risk, fill rate, and VWAP slippage.

    ``rows`` are (algorithm, mean controllable cost bp, standard deviation of shortfall bp, total shortfall bp,
    fill rate, VWAP slippage bp).
    """
    figure = new_figure(15.5, 7.4)
    grid = figure.add_gridspec(1, 3, width_ratios=[1.3, 1.0, 1.0], wspace=0.3, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    for name, cost, risk, _, _, _ in rows:
        axis.scatter(risk, cost, s=140, color=ALGO_COLOURS[name], zorder=3)
        axis.annotate(ALGO_NAMES[name], (risk, cost), xytext=(8, 4), textcoords="offset points", fontsize=8.6)
    _bp_axis(axis, "x")
    _bp_axis(axis, "y")
    style_axes(
        axis,
        title="Controllable cost against the spread of outcomes",
        xlabel="standard deviation of shortfall",
        ylabel="mean cost",
        grid="both",
    )
    fills = figure.add_subplot(grid[1])
    names = [row[0] for row in rows]
    fills.bar(range(len(rows)), [row[4] for row in rows], color=[ALGO_COLOURS[name] for name in names], width=0.6)
    for index, row in enumerate(rows):
        fills.text(index, row[4], f"{row[4]:.0%}", ha="center", va="bottom", fontsize=8)
    fills.set_xticks(range(len(rows)), labels=[ALGO_NAMES[name] for name in names], fontsize=8)
    _percent_axis(fills)
    style_axes(fills, title="Share of the value traded by the close", grid="y")
    slip = figure.add_subplot(grid[2])
    slip.bar(range(len(rows)), [row[5] for row in rows], color=[ALGO_COLOURS[name] for name in names], width=0.6)
    slip.set_xticks(range(len(rows)), labels=[ALGO_NAMES[name] for name in names], fontsize=8)
    _bp_axis(slip)
    style_axes(slip, title="Slippage against VWAP", grid="y")
    title_block(
        figure,
        "The same blocks, five algorithms, one day",
        "Each block re-run with every algorithm on the identical simulated market - the comparison no real desk can "
        "make. Waiting for the close is cheap only for the shares it manages to trade.",
    )
    caption(
        figure,
        "Controllable cost: spread, temporary and permanent impact, fees. Unfilled shares are charged opportunity "
        "cost at the close in the shortfall, not here.",
    )
    return figure


# ---------------------------------------------------------------------------- 6. calibration
def plot_impact_calibration(
    measured: Sequence[tuple[float, float]],
    observed: Sequence[tuple[float, float]],
    fits: Mapping[str, tuple[float, float, float]],
    truth: float,
) -> Figure:
    """Impact cost against σ√(participation) for the desk's history: measured by the simulator, and as a desk sees it.

    ``fits`` maps "measured" and "observed" to (coefficient, standard error, r squared).
    """
    figure = new_figure(15.5, 7.8)
    grid = figure.add_gridspec(1, 2, wspace=0.22, **_margins(figure, bottom=1.0))
    for column, (name, data, title) in enumerate(
        (
            ("measured", measured, "Temporary impact, measured by the simulator"),
            ("observed", observed, "Execution cost less the half-spread, as a desk observes it"),
        )
    ):
        axis = figure.add_subplot(grid[column])
        x = np.array([row[0] for row in data])
        y = np.array([row[1] for row in data])
        axis.scatter(x, y, s=10, color=PALETTE["slate"], alpha=0.45)
        grid_x = np.linspace(0, x.max(), 50)
        coefficient, error, r_squared = fits[name]
        axis.plot(
            grid_x,
            coefficient * grid_x,
            color=PALETTE["navy"],
            linewidth=2,
            label=f"fitted: {coefficient:.3f} ± {1.96 * error:.3f} (R² {r_squared:.2f})",
        )
        axis.plot(grid_x, truth * grid_x, color=AMBER, linewidth=1.6, linestyle="--", label=f"true: {truth:.3f}")
        _bp_axis(axis, "x")
        _bp_axis(axis, "y")
        style_axes(axis, title=title, xlabel="daily volatility x √(participation)", ylabel="cost", grid="both")
        axis.legend(loc="upper left")
        if name == "observed":
            axis.set_ylim(np.percentile(y, 2), np.percentile(y, 98))
    title_block(
        figure,
        "Calibrating the impact model, with the answer known",
        "Four hundred orders from the desk's history. Measured directly, the square-root coefficient is recovered to "
        "within a percent; from the prices a desk actually sees, the market's own moves drown it - hundreds of orders "
        "give only a rough estimate, which is why brokers pool millions.",
    )
    caption(
        figure,
        "Fits through the origin. The measured panel uses the steady-rate algorithms (VWAP, POV), whose average "
        "√participation is the order's.",
    )
    return figure


# ---------------------------------------------------------------------------- 7. pre-trade against post-trade
def plot_pre_post(rows: Sequence[tuple[float, float, float, str]]) -> Figure:
    """Pre-trade estimate against realised controllable cost for every order in the desk's history.

    ``rows`` are (share of ADV, pre-trade bp, realised controllable bp, algorithm).
    """
    figure = new_figure(15.5, 7.8)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 1.2], wspace=0.22, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    pre = np.array([row[1] for row in rows])
    post = np.array([row[2] for row in rows])
    axis.scatter(pre, post, s=10, c=[ALGO_COLOURS[row[3]] for row in rows], alpha=0.6)
    top = max(pre.max(), post.max())
    axis.plot([0, top], [0, top], color=PALETTE["ink"], linewidth=1, linestyle="--")
    _bp_axis(axis, "x")
    _bp_axis(axis, "y")
    style_axes(
        axis, title="Each order: estimate against outcome", xlabel="pre-trade estimate", ylabel="realised", grid="both"
    )
    axis.legend(
        handles=[Patch(color=ALGO_COLOURS[name], label=ALGO_NAMES[name]) for name in ("twap", "vwap", "pov", "is")],
        loc="upper left",
    )
    side = figure.add_subplot(grid[1])
    size = np.array([row[0] for row in rows])
    edges = np.quantile(size, np.linspace(0, 1, 7))
    centres, pre_mean, post_mean, spread = [], [], [], []
    for low, high in itertools.pairwise(edges):
        mask = (size >= low) & (size <= high)
        centres.append(f"{low:.1%}–{high:.1%}")
        pre_mean.append(pre[mask].mean())
        post_mean.append(post[mask].mean())
        spread.append(post[mask].std())
    positions = np.arange(len(centres))
    side.bar(positions - 0.18, pre_mean, width=0.36, color=PALETTE["grid"], label="pre-trade estimate")
    side.bar(
        positions + 0.18,
        post_mean,
        width=0.36,
        yerr=spread,
        color=PALETTE["navy"],
        label="realised (± one s.d.)",
        error_kw={"ecolor": PALETTE["muted"], "capsize": 3},
    )
    side.set_xticks(positions, labels=centres, fontsize=7.6)
    _bp_axis(side)
    style_axes(side, title="By order size (share of average daily volume)", grid="y")
    side.legend(loc="upper left")
    title_block(
        figure,
        "Did the cost model predict the cost?",
        "The pre-trade estimate - half the spread plus square-root impact - against what each order actually paid in "
        "spread, impact and fees. On average it is right; order by order the schedule and the day's volume move it.",
    )
    caption(
        figure,
        "Realised controllable cost excludes the market's own move (delay, timing, opportunity), which no model of "
        "cost can forecast.",
    )
    return figure


# ---------------------------------------------------------------------------- 8. allocation
def plot_allocation(
    rows: Sequence[tuple[str, Mapping[str, float], Mapping[str, float], float]],
    accounts: Sequence[str],
) -> Figure:
    """Each block's fills shared among the accounts: requested against allocated, one price for all.

    ``rows`` are (instrument, requested by account, allocated by account, average price).
    """
    figure = new_figure(15.5, 8.8)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.6, 1.0], wspace=0.25, **_margins(figure, bottom=1.0, left=0.1))
    axis = figure.add_subplot(grid[0])
    colours = (PALETTE["navy"], PALETTE["teal"], PALETTE["violet"])
    positions = np.arange(len(rows))
    left = np.zeros(len(rows))
    for account, colour in zip(accounts, colours, strict=False):
        requested = np.array([row[1].get(account, 0.0) for row in rows])
        allocated = np.array([row[2].get(account, 0.0) for row in rows])
        total = np.array([sum(row[1].values()) for row in rows])
        axis.barh(positions, allocated / total, left=left, color=colour, height=0.62, label=account)
        axis.barh(
            positions,
            (requested - allocated) / total,
            left=left + allocated / total,
            color=colour,
            alpha=0.2,
            height=0.62,
        )
        left += requested / total
    axis.set_yticks(positions, labels=[row[0] for row in rows], fontsize=7.6)
    axis.invert_yaxis()
    _percent_axis(axis, "x")
    style_axes(axis, title="Each block's requested shares by account (pale: not filled)", grid="x")
    axis.legend(loc="lower right")
    side = figure.add_subplot(grid[1])
    rates: dict[str, list[float]] = {account: [] for account in accounts}
    for row in rows:
        for account in accounts:
            if row[1].get(account, 0.0) > 0:
                rates[account].append(row[2].get(account, 0.0) / row[1][account])
    for index, (account, colour) in enumerate(zip(accounts, colours, strict=False)):
        values = np.array(rates[account])
        side.scatter(np.full(len(values), index) + np.linspace(-0.15, 0.15, len(values)), values, s=16, color=colour)
    side.set_xticks(range(len(accounts)), labels=accounts, fontsize=8)
    _percent_axis(side)
    side.set_ylim(0, 1.08)
    style_axes(side, title="Fill rate of every account order: the same for all", grid="y")
    title_block(
        figure,
        "Block orders allocated back to the accounts",
        "The three accounts on the same model trade as one block per stock, so they never compete with each other. "
        "Fills are shared at one average price, pro rata in whole shares, the odd shares by largest remainder.",
    )
    caption(
        figure,
        "Allocation decided before the block is worked (FCA COBS 11.3, SEC guidance on aggregated orders); no account "
        "receives more than it asked for.",
    )
    return figure


# ---------------------------------------------------------------------------- 9. the order's life
def plot_order_lifecycle(
    parent: tuple[str, Sequence[tuple[int, str]]],
    children: Sequence[tuple[str, Sequence[tuple[int, str]], float, float]],
    fills: Sequence[tuple[int, float]],
    end: int,
) -> Figure:
    """A parent order and its child orders through their FIX states, with the fills.

    ``parent`` is (id, [(minute, status)]); ``children`` (id, events, quantity, filled).
    """
    figure = new_figure(15.5, 8.4)
    grid = figure.add_gridspec(2, 1, height_ratios=[3.0, 1.0], hspace=0.25, **_margins(figure, bottom=0.9, left=0.14))
    axis = figure.add_subplot(grid[0])
    rows = [(parent[0], parent[1], None, None), *children]
    for index, (_name, events, quantity, filled) in enumerate(rows):
        points = list(events)
        for (start, status), (stop, _) in zip(points, [*points[1:], (end, points[-1][1])], strict=True):
            if stop > start or status in ("filled", "cancelled", "expired"):
                axis.barh(
                    index,
                    max(stop - start, 1),
                    left=start,
                    height=0.6,
                    color=STATUS_COLOURS.get(status, PALETTE["grid"]),
                )
        if quantity is not None and filled is not None:
            axis.text(
                end + 2, index, f"{filled:,.0f} / {quantity:,.0f}", va="center", fontsize=7.2, color=PALETTE["muted"]
            )
    axis.set_yticks(range(len(rows)), labels=[row[0] for row in rows], fontsize=7.2)
    axis.invert_yaxis()
    axis.set_xlim(0, end + 30)
    _clock_axis(axis)
    style_axes(axis, title="Parent order (top) and its child orders: state through the day", grid="x")
    axis.legend(
        handles=[Patch(color=colour, label=status) for status, colour in STATUS_COLOURS.items()],
        loc="lower right",
        ncol=5,
    )
    lower = figure.add_subplot(grid[1], sharex=axis)
    lower.bar([fill[0] for fill in fills], [fill[1] for fill in fills], color=PALETTE["teal"], width=1.0)
    lower.yaxis.set_major_formatter(lambda value, _: f"{value:,.0f}")
    style_axes(lower, title="Shares filled each minute", grid="y")
    title_block(
        figure,
        "An order's life, in FIX states",
        "The desk releases the parent to an algorithm, which sends a child order per slice. A child partially filled "
        "at "
        "the end of its slice is cancelled and the rest rolls into the next; the parent is filled, or expires at the "
        "close.",
    )
    caption(
        figure,
        "States follow FIX OrdStatus (tag 39). Every transition is an event in the audit trail, checked for order and "
        "quantity invariants.",
    )
    return figure


# ---------------------------------------------------------------------------- 10. participation
def plot_participation(names: Sequence[str], matrix: np.ndarray, cap: float) -> Figure:
    """Our share of each minute's volume, block by block."""
    figure = new_figure(15.5, 8.4)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, left=0.12, right=0.93))
    axis = figure.add_subplot(grid[0])
    image = axis.imshow(matrix, aspect="auto", cmap="Blues", vmin=0, vmax=cap, interpolation="nearest")
    axis.set_yticks(range(len(names)), labels=names, fontsize=7.4)
    _clock_axis(axis)
    axis.grid(visible=False)
    colourbar = figure.colorbar(image, ax=axis, fraction=0.025, pad=0.01)
    colourbar.ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    style_axes(axis, title="Our share of the market's volume, minute by minute", grid=None)
    title_block(
        figure,
        "How hard each block leaned on the market",
        "VWAP blocks trade a steady sliver of every minute; the large Tokyo blocks run at their POV rate all day and "
        f"still do not finish. No minute exceeds the {cap:.0%} cap.",
    )
    caption(figure, "Participation: our shares over the market's plus ours, per one-minute bar.")
    return figure


# ---------------------------------------------------------------------------- 11. the blotter
def plot_blotter(rows: Sequence[tuple[str, str, str, str, str, str, str, str, str]], trade_date_label: str) -> Figure:
    """The desk's blotter for the day: every block, its algorithm, fill, prices and costs."""
    figure = new_figure(15.5, 1.8 + 0.34 * len(rows))
    axis = figure.add_axes((0.01, 0.02, 0.98, 0.84))
    axis.axis("off")
    headers = (
        "Block",
        "Instrument",
        "Side",
        "Shares",
        "% ADV",
        "Algorithm",
        "Filled",
        "Average vs arrival",
        "Shortfall",
    )
    xs = (0.0, 0.14, 0.27, 0.33, 0.43, 0.51, 0.62, 0.72, 0.88)
    for x, header in zip(xs, headers, strict=True):
        axis.text(x, 1.0, header, fontsize=8.4, color=PALETTE["muted"], weight="bold", transform=axis.transAxes)
    step = 0.96 / max(len(rows), 1)
    for index, row in enumerate(rows):
        y = 0.97 - (index + 1) * step
        if index % 2 == 0:
            axis.axhspan(y - step * 0.35, y + step * 0.65, color=PALETTE["band"], zorder=0)
        for x, value in zip(xs, row, strict=True):
            colour = PALETTE["ink"]
            if x == 0.27:
                colour = PALETTE["teal"] if value == "buy" else PALETTE["loss"]
            axis.text(x, y, value, fontsize=8, color=colour, transform=axis.transAxes)
    axis.set_ylim(0, 1)
    title_block(
        figure,
        f"The trading blotter, {trade_date_label}",
        "Every block the desk worked, as the head of trading sees it the next morning.",
    )
    return figure
