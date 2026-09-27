"""Charts for tax-aware rebalancing: what to trade, which lots, what it costs, and what it is worth over years.

A portfolio manager's questions before pressing the button, one chart each:

* **How much risk does each dollar of tax buy?** The efficient frontier of
  tracking error against tax, with today's proposal, the tax-blind trade and
  the current portfolio on it.
* **What does the proposal trade, and which lots does it sell?** Weights before
  and after; every lot of every stock sold, with the rule-based alternatives.
* **Where are the losses, and which can be harvested?** Every lot by age and
  gain, the one-year line and the wash-sale window.
* **What does it cost to get there?** Commission, spread and impact per trade;
  the continuous solution rounded to board lots and minimum tickets.
* **Does the mandate still hold?** The Day 6 engine on the proposed portfolio.
* **Is it worth it over years?** Tax alpha across simulated paths, after-tax
  wealth, the harvest calendar and the tracking-error budget.

Colours: teal buys, crimson sells; green a gain, crimson a loss; the amber
accent marks the proposal alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .accounting import _margins, _money
from .style import PALETTE, caption, new_figure, style_axes, title_block

STRATEGY_COLOURS = {
    "buy and hold": PALETTE["slate"],
    "tax-blind": PALETTE["loss"],
    "tax-aware": PALETTE["sky"],
    "tax-aware, no harvesting": PALETTE["sky"],
    "tax-aware, harvesting": PALETTE["teal"],
}
RELIEF_LABELS = {
    "specific": "Chosen lots",
    "fifo": "First in, first out",
    "lifo": "Last in, first out",
    "hifo": "Highest cost first",
}
BUY, SELL = PALETTE["teal"], PALETTE["loss"]
AMBER = PALETTE["accent"]
GOLD = "#D9A21B"


def _pct(value: float, places: int = 1) -> str:
    return f"{value:.{places}%}"


def _percent_axis(axis, which: str = "y", places: int = 0) -> None:  # type: ignore[no-untyped-def]
    formatter = lambda value, _: f"{value:.{places}%}"  # noqa: E731
    (axis.yaxis if which == "y" else axis.xaxis).set_major_formatter(formatter)


def _money_axis(axis, which: str = "x") -> None:  # type: ignore[no-untyped-def]
    formatter = lambda value, _: _money(value, signed=value != 0)  # noqa: E731
    (axis.xaxis if which == "x" else axis.yaxis).set_major_formatter(formatter)


def _colour(name: str) -> str:
    return STRATEGY_COLOURS.get(name, PALETTE["navy"])


@dataclass(frozen=True)
class FrontierMarker:
    label: str
    tax: float  # base currency
    tracking_error: float
    kind: str  # current | proposal | other


# ---------------------------------------------------------------------------- 1. the frontier
def plot_efficient_frontier(
    points: Sequence[tuple[float, float, float, float]],
    markers: Sequence[FrontierMarker],
    day: date,
    nav: float,
    dominated: Sequence[tuple[float, float]] = (),
) -> Figure:
    """Tracking error against tax realised, the frontier through full solves, with rebalances placed on it.

    ``points`` are (tax, tracking error, cost, turnover) from the cheapest end to the closest; ``dominated``
    the (tax, tracking error) of solutions the sweeps found that another point beats.
    """
    figure = new_figure(15.5, 8.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.65, 1.0], wspace=0.22, **_margins(figure, bottom=1.05))
    axis = figure.add_subplot(grid[0])
    taxes = np.array([point[0] for point in points])
    errors = np.array([point[1] for point in points])
    top = max(errors.max(), max(marker.tracking_error for marker in markers)) * 1.12
    axis.fill_between(taxes, errors, top, color=PALETTE["band"], zorder=0)
    axis.text(
        taxes.min(),
        top * 0.97,
        "  above the frontier: reachable, but dominated",
        va="top",
        fontsize=8,
        color=PALETTE["muted"],
    )
    axis.fill_between(taxes, 0, errors, color="#F8F9FB", zorder=0, hatch="///", edgecolor=PALETTE["grid"], linewidth=0)
    axis.text(
        taxes.min(), top * 0.03, "  out of reach: the mandate allows nothing here", fontsize=8, color=PALETTE["muted"]
    )
    axis.plot(
        taxes, errors, color=PALETTE["navy"], linewidth=2.2, marker="o", markersize=4.5, zorder=3, label="frontier"
    )
    if dominated:
        axis.scatter(
            [item[0] for item in dominated],
            [item[1] for item in dominated],
            s=22,
            facecolor="white",
            edgecolor=PALETTE["slate"],
            zorder=2,
            label="a local optimum another point beats",
        )
        axis.legend(loc="lower right")
    axis.axvline(0.0, color=PALETTE["grid"], linewidth=1.0, zorder=1)
    for marker in markers:
        if marker.kind == "proposal":
            axis.scatter(
                marker.tax, marker.tracking_error, s=210, marker="*", color=AMBER, zorder=5, edgecolor=PALETTE["ink"]
            )
            colour, weight = AMBER, "bold"
        elif marker.kind == "current":
            axis.scatter(marker.tax, marker.tracking_error, s=90, marker="s", color=PALETTE["ink"], zorder=5)
            colour, weight = PALETTE["ink"], "bold"
        else:
            axis.scatter(
                marker.tax, marker.tracking_error, s=70, color=_colour(marker.label), zorder=5, edgecolor="white"
            )
            colour, weight = _colour(marker.label), "normal"
        axis.annotate(
            f"{marker.label}\n{_money(marker.tax, signed=True)} tax, TE {_pct(marker.tracking_error, 2)}",
            (marker.tax, marker.tracking_error),
            xytext=(10, 8),
            textcoords="offset points",
            fontsize=8.2,
            color=colour,
            weight=weight,
        )
    axis.set_ylim(0, top)
    _percent_axis(axis, "y", 1)
    _money_axis(axis, "x")
    style_axes(
        axis,
        title="Tracking error bought with tax: every point a full, compliant rebalance",
        xlabel="tax realised by the rebalance (negative: tax saved by harvested losses)",
        ylabel="tracking error after the trades (annual)",
        grid="both",
    )
    side = figure.add_subplot(grid[1])
    costs = np.array([point[2] for point in points])
    turnover = np.array([point[3] for point in points])
    side.bar(np.arange(len(points)), turnover, color=PALETTE["sky"], width=0.7, label="turnover (two-way)")
    _percent_axis(side, "y")
    twin = side.twinx()
    twin.plot(np.arange(len(points)), costs, color=PALETTE["violet"], marker="o", markersize=4, label="trading cost")
    twin.yaxis.set_major_formatter(lambda value, _: _money(value))
    twin.grid(visible=False)
    for spine in ("top",):
        twin.spines[spine].set_visible(False)
    side.set_xticks(np.arange(len(points)), labels=[_money(tax, signed=True) for tax in taxes], rotation=60, fontsize=7)
    style_axes(side, title="What each point trades, and pays to trade", xlabel="tax realised", grid="y")
    handles = [
        Patch(color=PALETTE["sky"], label="turnover (left)"),
        Line2D([], [], color=PALETTE["violet"], marker="o", label="trading cost (right)"),
    ]
    side.legend(handles=handles, loc="upper center", fontsize=8)
    title_block(
        figure,
        f"The efficient frontier of tracking error against tax, {day:%d %B %Y}",
        "The lower envelope of every rebalance two sweeps found - tax capped, and risk priced - with the mandate, cash "
        f"band, wash-sale rule and active-share floor all holding. Account value {_money(nav)}.",
    )
    caption(
        figure,
        "Epsilon-constraint and price-of-risk sweeps solved by Clarabel; the active-share floor makes the problem "
        "non-convex, "
        "so dominated local optima are shown. Tax at 40.8% short-term and 23.8% long-term (federal plus NIIT), per "
        "lot.",
    )
    return figure


# ---------------------------------------------------------------------------- 2. the trades
def plot_rebalance_trades(
    rows: Sequence[tuple[str, float, float, float, float]],
    cash: tuple[float, float],
    day: date,
    summary: Sequence[tuple[str, str]],
) -> Figure:
    """Weights before and after for every asset traded, the trade itself, and the tax each sale realises.

    ``rows`` are (asset, weight before, weight after, target weight or nan, tax realised in base currency).
    """
    figure = new_figure(15.5, 9.0)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.5, 1.0], wspace=0.28, **_margins(figure, bottom=1.0, left=0.1))
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(rows))
    before = np.array([row[1] for row in rows])
    after = np.array([row[2] for row in rows])
    axis.barh(positions + 0.19, before, height=0.36, color=PALETTE["grid"], label="before")
    colours = [BUY if a > b else SELL for b, a in zip(before, after, strict=True)]
    axis.barh(positions - 0.19, after, height=0.36, color=colours, label="after")
    for position, row in zip(positions, rows, strict=True):
        if np.isfinite(row[3]) and row[3] > 0:
            axis.plot([row[3]] * 2, [position - 0.42, position + 0.42], color=PALETTE["ink"], linewidth=1.3)
        change = row[2] - row[1]
        axis.text(
            max(row[1], row[2]) + 0.003,
            position,
            f"{'+' if change > 0 else ''}{change:.1%}",
            va="center",
            fontsize=7.8,
            color=BUY if change > 0 else SELL,
        )
    axis.set_yticks(positions, labels=[row[0] for row in rows], fontsize=8)
    axis.invert_yaxis()
    _percent_axis(axis, "x")
    style_axes(axis, title="Weights before and after (the tick is the target's weight)", grid="x")
    axis.legend(
        handles=[
            Patch(color=PALETTE["grid"], label="before"),
            Patch(color=BUY, label="after, bought"),
            Patch(color=SELL, label="after, sold"),
            Line2D([], [], color=PALETTE["ink"], label="target"),
        ],
        loc="lower right",
    )
    side = figure.add_subplot(grid[1])
    sold = [(row[0], row[4]) for row in rows if row[2] < row[1] - 1e-9]
    sold.sort(key=lambda item: item[1])
    side.barh(
        np.arange(len(sold)),
        [tax for _, tax in sold],
        color=[PALETTE["gain"] if tax < 0 else PALETTE["loss"] for _, tax in sold],
        height=0.6,
    )
    side.set_yticks(np.arange(len(sold)), labels=[name for name, _ in sold], fontsize=8)
    side.invert_yaxis()
    side.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    _money_axis(side, "x")
    style_axes(side, title="Tax realised by each sale (green: saved)", grid="x")
    for index, (label, value) in enumerate(summary):
        side.text(1.02, 1.0 - index * 0.075, f"{label}", transform=side.transAxes, fontsize=8, color=PALETTE["muted"])
        side.text(
            1.02,
            0.965 - index * 0.075,
            value,
            transform=side.transAxes,
            fontsize=10,
            color=PALETTE["ink"],
            weight="bold",
        )
    title_block(
        figure,
        f"The proposed rebalance, {day:%d %B %Y}",
        f"Cash {_pct(cash[0])} before, {_pct(cash[1])} after. Sales fund purchases; losses sold are not bought back "
        "(the wash-sale rule), so substitutes carry their risk.",
    )
    caption(figure, "Weights are shares of net asset value, accrued interest included. Tax at each lot's own rate.")
    return figure


# ---------------------------------------------------------------------------- 3. lot selection
def plot_lot_selection(
    lots: Sequence[tuple[str, str, float, bool, float, float]],
    relief: Mapping[str, float],
    relief_gains: Mapping[str, tuple[float, float]],
) -> Figure:
    """Every lot of every stock sold, its tax per unit and how much of it was sold; then the same trades by fixed rules.

    ``lots`` are (asset, lot id, tax per unit of value sold, long-term, weight held, weight sold).
    ``relief`` maps a method to the tax it realises; ``relief_gains`` to (short-term, long-term) net gains.
    """
    figure = new_figure(15.5, 8.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.45, 1.0], wspace=0.3, **_margins(figure, bottom=1.0, left=0.1))
    axis = figure.add_subplot(grid[0])
    labels = []
    position = 0.0
    positions = []
    previous = None
    for asset, lot_id, rate, long_term, held, sold in lots:
        if asset != previous and previous is not None:
            position += 0.6
        previous = asset
        colour = PALETTE["gain"] if rate < 0 else (PALETTE["sky"] if long_term else PALETTE["violet"])
        axis.barh(position, rate, height=0.6, color=colour, alpha=0.35)
        share = sold / held if held > 0 else 0.0
        axis.barh(position, rate * share, height=0.6, color=colour)
        axis.text(
            max(rate, 0.0) + 0.004,
            position,
            f"{share:.0%} sold",
            va="center",
            ha="left",
            fontsize=7.4,
            color=PALETTE["ink"] if share > 0 else PALETTE["muted"],
        )
        positions.append(position)
        labels.append(f"{asset}  {lot_id}")
        position += 1.0
    axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.set_yticks(positions, labels=labels, fontsize=7.6)
    axis.invert_yaxis()
    _percent_axis(axis, "x")
    style_axes(axis, title="Tax per dollar sold, lot by lot (solid: the part sold)", grid="x")
    axis.legend(
        handles=[
            Patch(color=PALETTE["gain"], label="a loss: selling saves tax"),
            Patch(color=PALETTE["violet"], label="short-term gain (40.8%)"),
            Patch(color=PALETTE["sky"], label="long-term gain (23.8%)"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.05),
        ncol=3,
    )
    side = figure.add_subplot(grid[1])
    methods = list(relief)
    values = [relief[method] for method in methods]
    best = min(values)
    bars = side.bar(
        np.arange(len(methods)),
        values,
        color=[AMBER if value == best else PALETTE["slate"] for value in values],
        width=0.62,
    )
    for bar, method in zip(bars, methods, strict=True):
        short, long = relief_gains[method]
        side.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() / 2,
            f"{_money(bar.get_height(), signed=True)}\n\nnet gains\n"
            f"ST {_money(short, signed=True)}\nLT {_money(long, signed=True)}",
            ha="center",
            va="center",
            fontsize=7.8,
            color="white",
            weight="bold",
        )
    side.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    side.set_xticks(np.arange(len(methods)), labels=[RELIEF_LABELS[method] for method in methods], fontsize=8)
    _money_axis(side, "y")
    style_axes(side, title="The same trades, lots relieved four ways: tax realised", grid="y")
    title_block(
        figure,
        "Which lots to sell: specific identification against the broker's defaults",
        "The optimiser chooses lots; a fixed rule would sell the same number of shares from other lots. Per unit sold, "
        "a large long-term gain can cost more than a small short-term one.",
    )
    caption(
        figure,
        "ST/LT: net short- and long-term gains realised. Specific identification is the lowest possible for these "
        "trades "
        "- it is what the optimiser chose among all lots.",
    )
    return figure


# ---------------------------------------------------------------------------- 4. the harvesting map
def plot_lot_map(
    lots: Sequence[tuple[str, int, float, float, bool, float, bool]],
    day: date,
    long_term_days: int = 365,
    wash_days: int = 30,
) -> Figure:
    """Every open lot by days held and gain, sized by value; lots sold marked, the one-year and wash-sale lines drawn.

    ``lots`` are (asset, days held, gain as a share of basis, value, long-term, share sold, wash-blocked).
    """
    figure = new_figure(15.5, 8.4)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    days = np.array([lot[1] for lot in lots], dtype=float)
    gains = np.array([lot[2] for lot in lots])
    values = np.array([lot[3] for lot in lots])
    sizes = 30 + 900 * values / values.max()
    colours = [PALETTE["gain"] if gain >= 0 else PALETTE["loss"] for gain in gains]
    axis.scatter(days, gains, s=sizes, c=colours, alpha=0.35, edgecolor="none")
    sold = np.array([lot[5] > 1e-6 for lot in lots])
    axis.scatter(days[sold], gains[sold], s=sizes[sold], facecolor="none", edgecolor=AMBER, linewidth=2.0)
    for lot, x, y in zip(lots, days, gains, strict=True):
        if abs(y) > 0.12 or lot[5] > 1e-6:
            axis.annotate(lot[0], (x, y), xytext=(6, 4), textcoords="offset points", fontsize=7.5, color=PALETTE["ink"])
    axis.axvline(long_term_days, color=PALETTE["ink"], linewidth=1.2, linestyle="--")
    axis.text(long_term_days + 8, gains.max() * 0.95, "long-term from here\n(23.8% instead of 40.8%)", fontsize=8)
    axis.axvspan(0, wash_days, color=GOLD, alpha=0.18)
    axis.text(
        wash_days + 4,
        gains.min() * 0.95,
        "bought within 30 days:\na loss here is disallowed",
        fontsize=8,
        color="#8A6A10",
    )
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    _percent_axis(axis, "y")
    style_axes(
        axis,
        title="Every open tax lot: how long held, how far from its cost",
        xlabel="days held",
        ylabel="unrealised gain as a share of the lot's cost",
        grid="both",
    )
    axis.legend(
        handles=[
            Patch(color=PALETTE["gain"], alpha=0.5, label="lot at a gain"),
            Patch(color=PALETTE["loss"], alpha=0.5, label="lot at a loss"),
            Line2D(
                [],
                [],
                marker="o",
                color="white",
                markeredgecolor=AMBER,
                markersize=11,
                markeredgewidth=2,
                label="sold by the proposal",
            ),
        ],
        loc="upper right",
    )
    title_block(
        figure,
        f"The harvesting map, {day:%d %B %Y}",
        "Losses below the line are what harvesting sells; young gains left of the one-year line are what a tax-aware "
        "manager waits on. Circle area is the lot's value.",
    )
    caption(figure, "Cost basis includes wash-sale adjustments carried from the Day 3 book.")
    return figure


# ---------------------------------------------------------------------------- 5. the solve rounds
def plot_solve_rounds(
    rounds: Sequence[tuple[int, float, float, float, int, bool]],
    notes: Sequence[str],
    floor: float | None,
) -> Figure:
    """How the proposal settled: tracking error, active share and tax round by round, and what each round fixed.

    ``rounds`` are (number, tracking error, active share, tax, assets barred, active share restricted).
    """
    figure = new_figure(15.5, 8.4)
    grid = figure.add_gridspec(3, 2, width_ratios=[1.2, 1.0], hspace=0.55, wspace=0.18, **_margins(figure, bottom=0.9))
    numbers = [item[0] for item in rounds]
    labels = [f"round {item[0]}\n{item[4]} barred" + (", floor on" if item[5] else "") for item in rounds]
    panels = (
        ("Tracking error", [item[1] for item in rounds], PALETTE["navy"], "pct2"),
        ("Active share", [item[2] for item in rounds], PALETTE["violet"], "pct1"),
        ("Tax realised", [item[3] for item in rounds], PALETTE["gain"], "money"),
    )
    for row, (title, values, colour, kind) in enumerate(panels):
        axis = figure.add_subplot(grid[row, 0])
        if kind == "money":
            axis.bar(
                numbers,
                values,
                color=[PALETTE["gain"] if value < 0 else PALETTE["loss"] for value in values],
                width=0.5,
            )
            axis.yaxis.set_major_formatter(lambda value, _: _money(value, signed=value != 0))
            axis.axhline(0, color=PALETTE["ink"], linewidth=0.7)
        else:
            axis.plot(numbers, values, marker="o", color=colour)
            _percent_axis(axis, "y", 1 if kind == "pct1" else 2)
            for number, value in zip(numbers, values, strict=True):
                axis.annotate(
                    _pct(value, 2 if kind == "pct2" else 1),
                    (number, value),
                    xytext=(0, 7),
                    textcoords="offset points",
                    ha="center",
                    fontsize=7.8,
                )
        if kind == "pct1" and floor is not None:
            axis.axhline(floor, color=PALETTE["violet"], linestyle="--", linewidth=1)
            axis.text(numbers[0], floor, " floor", va="bottom", fontsize=8, color=PALETTE["violet"])
        axis.set_xticks(numbers, labels=labels if row == 2 else [""] * len(numbers), fontsize=7.6)
        axis.margins(y=0.3)
        style_axes(axis, title=title, grid="y")
    side = figure.add_subplot(grid[:, 1])
    side.axis("off")
    side.set_title("What the rounds fixed", loc="left")
    for index, note in enumerate(notes):
        side.text(0.0, 0.94 - index * 0.1, f"{index + 1}. {note}", fontsize=8.2, transform=side.transAxes, wrap=True)
    title_block(
        figure,
        "Two rules that are not convex, met in rounds",
        "Wash sales: a stock whose loss lots are sold may not be bought, so it is barred and the problem solved again. "
        "Active share: its floor is linearised at the signs of the active weights, refined until they settle.",
    )
    caption(
        figure,
        "Each round is a full conic solve; the last is the proposal. Two starts are tried for the floor, and the "
        "lower kept.",
    )
    return figure


# ---------------------------------------------------------------------------- 6. trading costs
def plot_trading_costs(
    rows: Sequence[tuple[str, float, float, float]],
    curves: Sequence[tuple[str, float, float]],
    nav: float,
) -> Figure:
    """Cost of each trade split into commission and half-spread against market impact, and the impact law itself.

    ``rows`` are (asset, traded value, linear cost, impact cost); ``curves`` (asset, linear rate, impact coefficient).
    """
    figure = new_figure(15.5, 8.0)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.3, 1.0], wspace=0.25, **_margins(figure, bottom=1.0, left=0.1))
    axis = figure.add_subplot(grid[0])
    ordered = sorted(rows, key=lambda row: -(row[2] + row[3]))
    positions = np.arange(len(ordered))
    linear = np.array([row[2] for row in ordered])
    impact = np.array([row[3] for row in ordered])
    axis.barh(positions, linear, color=PALETTE["slate"], height=0.62, label="commission and half-spread")
    axis.barh(positions, impact, left=linear, color=PALETTE["violet"], height=0.62, label="market impact")
    for position, row in zip(positions, ordered, strict=True):
        axis.text(
            row[2] + row[3],
            position,
            f"  {(row[2] + row[3]) / row[1] * 1e4:.1f} bp of {_money(row[1])}",
            va="center",
            fontsize=7.6,
        )
    axis.set_yticks(positions, labels=[row[0] for row in ordered], fontsize=8)
    axis.invert_yaxis()
    axis.xaxis.set_major_formatter(lambda value, _: _money(value))
    style_axes(axis, title="What each trade costs", grid="x")
    axis.legend(loc="lower right")
    side = figure.add_subplot(grid[1])
    sizes = np.linspace(0, 0.08, 120)
    for name, rate, coefficient in curves:
        side.plot(sizes * nav, (rate * sizes + coefficient * sizes**1.5) / np.maximum(sizes, 1e-12) * 1e4, label=name)
    side.xaxis.set_major_formatter(lambda value, _: _money(value))
    style_axes(
        side,
        title="Cost per dollar traded grows with the square root of size",
        xlabel="trade size",
        ylabel="cost, basis points",
        grid="both",
    )
    side.legend(loc="upper left", fontsize=7.6)
    title_block(
        figure,
        "Trading costs: linear and square-root impact",
        "Commission 5 bp plus half the quoted spread on every dollar, and impact of 0.1 x daily volatility x the "
        "square "
        "root of the trade's share of daily volume - the x^1.5 law the optimiser prices in.",
    )
    caption(
        figure, "Daily volume and volatility from the Day 2 market data; impact coefficient from the square-root law."
    )
    return figure


# ---------------------------------------------------------------------------- 7. rounding
def plot_rounding(
    rows: Sequence[tuple[str, float, float, float, str]],
    min_ticket: float,
    drift: float,
) -> Figure:
    """The optimiser's trades against the rounded orders: board lots, the minimum ticket, and what was dropped.

    ``rows`` are (asset, continuous signed value, rounded signed value, lot size, flag) with flag one of
    "", "dropped", "raised".
    """
    figure = new_figure(15.5, 8.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.5, 1.0], wspace=0.08, **_margins(figure, bottom=1.0, left=0.1))
    axis = figure.add_subplot(grid[0])
    ordered = sorted(rows, key=lambda row: row[1])
    positions = np.arange(len(ordered))
    for position, (_, continuous, rounded, lot_size, flag) in zip(positions, ordered, strict=True):
        colour = BUY if continuous > 0 else SELL
        axis.plot([continuous, rounded], [position, position], color=PALETTE["grid"], linewidth=3, zorder=1)
        axis.scatter(continuous, position, s=40, facecolor="white", edgecolor=colour, zorder=3, linewidth=1.5)
        axis.scatter(rounded, position, s=40, color=colour if flag != "dropped" else PALETTE["muted"], zorder=4)
        note = f"lots of {lot_size:,.0f}" if lot_size > 1 else ""
        if flag:
            note = (note + "  " if note else "") + flag
        if note:
            axis.text(
                max(continuous, rounded) + 4_000,
                position,
                note,
                va="center",
                fontsize=7.6,
                color=AMBER if flag else PALETTE["muted"],
            )
    axis.axvspan(-min_ticket, min_ticket, color=PALETTE["band"], zorder=0)
    axis.text(
        0, len(ordered) - 0.3, f"below the {_money(min_ticket)} ticket", ha="center", fontsize=8, color=PALETTE["muted"]
    )
    axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.set_yticks(positions, labels=[row[0] for row in ordered], fontsize=8)
    _money_axis(axis, "x")
    style_axes(axis, title="Open circle: the optimiser's trade; filled: the order sent", grid="x")
    side = figure.add_subplot(grid[1], sharey=axis)
    adjustment = [row[2] - row[1] for row in ordered]
    side.barh(positions, adjustment, color=[AMBER if row[3] > 1 else PALETTE["slate"] for row in ordered], height=0.6)
    side.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    side.tick_params(labelleft=False)
    side.xaxis.set_major_formatter(lambda value, _: f"{value:+,.0f}")
    style_axes(side, title="Rounding: order less the optimiser's trade, dollars (amber: board lots)", grid="x")
    title_block(
        figure,
        "From weights to orders: whole lots, minimum tickets, cash kept in its band",
        "Rounding is its own small mixed-integer programme (HiGHS): the closest whole-lot orders, each zero or above "
        "the "
        f"minimum ticket, cash within the band. Total drift from the optimiser's trades: ${drift:,.0f}.",
    )
    caption(
        figure,
        "Tokyo trades in board lots of 100 shares; the other markets here in single shares. Sales never exceed the "
        "position.",
    )
    return figure


# ---------------------------------------------------------------------------- 8. three managers
def plot_strategy_comparison(
    rows: Sequence[tuple[str, float, float, float, float, float, float]], nav: float
) -> Figure:
    """Today's account rebalanced by three managers, side by side.

    ``rows`` are (manager, tracking error after, tax, cost, turnover, active share after, losses realised).
    """
    figure = new_figure(15.5, 7.2)
    grid = figure.add_gridspec(1, 5, wspace=0.42, **_margins(figure, bottom=1.25, left=0.05))
    metrics = (
        ("Tracking error after", 1, "pct"),
        ("Tax realised", 2, "money"),
        ("Losses harvested", 6, "money"),
        ("Trading cost", 3, "money"),
        ("Turnover (two-way)", 4, "pct"),
    )
    names = [row[0] for row in rows]
    for column, (title, index, kind) in enumerate(metrics):
        axis = figure.add_subplot(grid[column])
        values = [float(row[index]) for row in rows]
        bars = axis.bar(np.arange(len(rows)), values, color=[_colour(name) for name in names], width=0.66)
        for bar, value in zip(bars, values, strict=True):
            text = (
                _pct(value, 2 if kind == "pct" and value < 0.1 else 0)
                if kind == "pct"
                else _money(value, signed=index == 2)
            )
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                text,
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=8,
            )
        axis.axhline(0, color=PALETTE["ink"], linewidth=0.7)
        axis.set_xticks(np.arange(len(rows)), labels=[name.replace(", ", ",\n") for name in names], fontsize=7.4)
        if kind == "pct":
            _percent_axis(axis, "y", 1)
        else:
            axis.yaxis.set_major_formatter(lambda value, _: _money(value))
        style_axes(axis, title=title, grid="y")
    title_block(
        figure,
        "Three managers, one account, one day",
        "The same risk aversion; the tax-blind manager ignores tax and relieves lots first in, first out; the others "
        "choose lots, and the last also harvests losses.",
    )
    caption(
        figure,
        f"Account value {_money(nav)}. Losses harvested: realised losses the rebalance books, wash-sale deferrals "
        "excluded.",
    )
    return figure


# ---------------------------------------------------------------------------- 9. the mandate after the trades
def plot_post_trade(rows: Sequence[tuple[str, float, float, str, str]], decision: str) -> Figure:
    """Each rule's utilisation before and after the proposal, as the Day 6 engine measures it independently.

    ``rows`` are (rule title, utilisation before, utilisation after, status after, effect).
    """
    figure = new_figure(15.5, 9.0)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, left=0.27, right=0.88))
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(rows))
    status_colour = {
        "pass": PALETTE["gain"],
        "warning": GOLD,
        "breach": PALETTE["loss"],
        "not evaluable": PALETTE["grid"],
    }
    axis.barh(positions + 0.19, [min(row[1], 1.35) for row in rows], height=0.36, color=PALETTE["grid"], label="before")
    axis.barh(
        positions - 0.19,
        [min(row[2], 1.35) for row in rows],
        height=0.36,
        color=[status_colour[row[3]] for row in rows],
    )
    for position, row in zip(positions, rows, strict=True):
        if row[4] != "unchanged":
            axis.text(
                1.02,
                position,
                row[4],
                transform=axis.get_yaxis_transform(),
                va="center",
                fontsize=8,
                color=AMBER,
                weight="bold",
            )
    axis.axvline(1.0, color=PALETTE["loss"], linewidth=1.3)
    axis.set_yticks(positions, labels=[row[0] for row in rows], fontsize=8.2)
    axis.invert_yaxis()
    axis.set_xlim(0, 1.4)
    _percent_axis(axis, "x")
    style_axes(axis, title="Utilisation of each limit: grey today, coloured after the proposal", grid="x")
    axis.legend(
        handles=[
            Patch(color=PALETTE["grid"], label="today"),
            Patch(color=PALETTE["gain"], label="after: pass"),
            Patch(color=GOLD, label="after: warning"),
            Patch(color=PALETTE["loss"], label="after: breach"),
        ],
        loc="lower right",
    )
    title_block(
        figure,
        f"The mandate after the trades: {decision}",
        "The proposal is sent to the Day 6 compliance engine as one basket. The optimiser met every limit it could "
        "compile, inside a buffer; the engine measures the result its own way, and has the last word.",
    )
    caption(
        figure,
        "Utilisation is value over limit (limit over value for floors). Rules that do not compile - a count of "
        "holdings - are checked here only.",
    )
    return figure


# ---------------------------------------------------------------------------- 10. tax alpha
def plot_tax_alpha(
    alphas: Mapping[str, np.ndarray],
    held: Mapping[str, np.ndarray],
    table: Sequence[Mapping[str, float | str]],
    paths: int,
    months: int,
) -> Figure:
    """Annual tax alpha against the tax-blind manager across simulated paths, on liquidation and as held."""
    figure = new_figure(15.5, 8.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.35, 1.0], wspace=0.22, **_margins(figure, bottom=1.1))
    axis = figure.add_subplot(grid[0])
    names = [name for name in alphas if name != "tax-blind"]
    for index, name in enumerate(names):
        for offset, data, alpha_level in ((-0.17, alphas[name], 0.9), (0.17, held[name], 0.45)):
            parts = axis.violinplot(data, positions=[index + offset], widths=0.3, showextrema=False)
            for body in parts["bodies"]:  # type: ignore[attr-defined]
                body.set_facecolor(_colour(name))
                body.set_alpha(alpha_level)
            axis.scatter(index + offset, np.mean(data), color=PALETTE["ink"], s=18, zorder=3)
            axis.text(index + offset, np.mean(data), f"  {np.mean(data):+.2%}", fontsize=8, va="center")
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.set_xticks(np.arange(len(names)), labels=names, fontsize=8.5)
    _percent_axis(axis, "y", 1)
    style_axes(axis, title="Annual after-tax return over the tax-blind manager, one violin per measure", grid="y")
    axis.legend(
        handles=[
            Patch(color=PALETTE["slate"], alpha=0.9, label="on liquidation (every gain taxed at the end)"),
            Patch(color=PALETTE["slate"], alpha=0.45, label="as held (deferred tax not charged)"),
        ],
        loc="upper left",
    )
    side = figure.add_subplot(grid[1])
    side.axis("off")
    side.set_title("Averages over the paths", loc="left")
    headers = ("", "pre-tax", "after tax", "tax alpha", "TE", "turnover")
    xs = (0.0, 0.34, 0.5, 0.66, 0.82, 0.95)
    for x, header in zip(xs, headers, strict=True):
        side.text(
            x,
            0.92,
            header,
            fontsize=8,
            color=PALETTE["muted"],
            transform=side.transAxes,
            ha="left" if x == 0 else "center",
        )
    for row_index, row in enumerate(table):
        y = 0.84 - row_index * 0.08
        values = (
            str(row["strategy"]),
            _pct(float(row["pre_tax"]), 2),
            _pct(float(row["after_tax"]), 2),
            f"{float(row['tax_alpha']):+.2%}",
            _pct(float(row["tracking_error"]), 2),
            _pct(float(row["turnover"]), 0),
        )
        for x, value in zip(xs, values, strict=True):
            side.text(
                x,
                y,
                value,
                fontsize=8.4,
                transform=side.transAxes,
                ha="left" if x == 0 else "center",
                color=_colour(str(row["strategy"])) if x == 0 else PALETTE["ink"],
            )
    title_block(
        figure,
        "Tax alpha: the same account managed four ways through the same simulated markets",
        f"{paths} paths of {months} months from the Day 5 factor model, a 100-stock index reconstituted quarterly. The "
        "client realises short-term gains elsewhere, which harvested losses offset; tax is paid from the account each "
        "year.",
    )
    caption(
        figure,
        "Tax alpha: annualised after-tax return minus the tax-blind manager's on the same path. Turnover two-way, per "
        "year. "
        "US federal rates with the net investment income tax; wash-sale rule enforced.",
    )
    return figure


# ---------------------------------------------------------------------------- 11. after-tax wealth
def plot_after_tax_wealth(
    months: Sequence[int],
    wealth: Mapping[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    taxes: Mapping[str, np.ndarray],
) -> Figure:
    """After-tax wealth relative to the tax-blind manager on the same path (median, inter-quartile band), and tax paid.

    ``wealth`` maps a manager to (25th percentile, median, 75th percentile) of its wealth over the tax-blind
    manager's, less one, month by month.
    """
    figure = new_figure(15.5, 8.0)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.35, 1.0], wspace=0.22, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    x = np.asarray(months)
    for name, (low, middle, high) in wealth.items():
        axis.plot(x, middle, color=_colour(name), label=name)
        if name != "tax-blind":
            axis.fill_between(x, low, high, color=_colour(name), alpha=0.12)
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    _percent_axis(axis, "y", 1)
    style_axes(
        axis,
        title="After-tax wealth over the tax-blind manager's, path by path (median, inter-quartile band)",
        xlabel="months",
        grid="both",
    )
    axis.legend(loc="upper left")
    side = figure.add_subplot(grid[1])
    for name, series in taxes.items():
        side.plot(np.arange(1, len(series) + 1), series, color=_colour(name), label=name, drawstyle="steps-post")
    _percent_axis(side, "y", 1)
    style_axes(side, title="Tax paid, cumulative, share of the starting value", xlabel="months", grid="both")
    title_block(
        figure,
        "Deferral compounds: after-tax wealth, and the tax each manager paid",
        "Tax paid leaves the account at each year end; a manager who realises less keeps more invested. The gap widens "
        "each December.",
    )
    caption(
        figure,
        "Before liquidation. Negative tax paid: harvested losses offsetting the client's gains elsewhere, credited to "
        "the account.",
    )
    return figure


# ---------------------------------------------------------------------------- 12. the harvest calendar
def plot_harvest_calendar(
    months: Sequence[int],
    harvested: np.ndarray,
    gains: np.ndarray,
    carryforward: np.ndarray,
    volatility: np.ndarray,
) -> Figure:
    """Losses harvested and gains realised each month by the harvesting manager, and the loss carried forward."""
    figure = new_figure(15.5, 7.6)
    grid = figure.add_gridspec(2, 1, height_ratios=[1.6, 1.0], hspace=0.3, **_margins(figure, bottom=0.9))
    axis = figure.add_subplot(grid[0])
    x = np.asarray(months)
    axis.bar(x, -harvested, color=PALETTE["gain"], width=0.8, label="losses harvested")
    axis.bar(x, gains, color=PALETTE["loss"], width=0.8, label="gains realised")
    twin = axis.twinx()
    twin.plot(x, carryforward, color=PALETTE["violet"], linewidth=2, label="loss carried forward")
    twin.grid(visible=False)
    _percent_axis(axis, "y", 1)
    _percent_axis(twin, "y", 1)
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    style_axes(axis, title="Realised each month, share of the starting value (mean over paths)", grid="y")
    handles = [
        Patch(color=PALETTE["gain"], label="losses harvested"),
        Patch(color=PALETTE["loss"], label="gains realised"),
        Line2D([], [], color=PALETTE["violet"], label="loss carried forward (right)"),
    ]
    axis.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=3)
    lower = figure.add_subplot(grid[1], sharex=axis)
    lower.bar(x, volatility, color=PALETTE["slate"], width=0.8)
    _percent_axis(lower, "y", 1)
    style_axes(
        lower,
        title="Cross-sectional dispersion of the month's returns: the raw material of harvesting",
        xlabel="months",
        grid="y",
    )
    title_block(
        figure,
        "The harvest calendar",
        "Losses are harvested when dispersion is high and early, while lots are young; as the account ages its lots "
        "drift into gains and there is less to harvest. Unused losses carry forward.",
    )
    caption(figure, "The harvesting manager, averaged over the simulated paths.")
    return figure


# ---------------------------------------------------------------------------- 13. the tracking-error budget
def plot_tracking_budget(
    months: Sequence[int], errors: Mapping[str, np.ndarray], realised: Mapping[str, float], budget: float
) -> Figure:
    """Ex-ante tracking error month by month for each manager, against the tax-aware managers' budget."""
    figure = new_figure(15.5, 7.2)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    for name, series in errors.items():
        axis.plot(months, series, color=_colour(name), label=f"{name} (realised {_pct(realised[name], 2)})")
    axis.axhline(budget, color=AMBER, linestyle="--", linewidth=1.5)
    axis.text(
        months[-1],
        budget,
        "tracking-error budget of the tax-aware managers ",
        va="bottom",
        ha="right",
        fontsize=8,
        color=AMBER,
    )
    _percent_axis(axis, "y", 1)
    style_axes(
        axis, title="Ex-ante tracking error after each month's trades (mean over paths)", xlabel="months", grid="both"
    )
    axis.legend(loc="lower right")
    title_block(
        figure,
        "Risk spent to save tax",
        "The tax-blind manager tracks the index as closely as it can; the tax-aware managers spend a budgeted tracking "
        "error on deferring gains and harvesting losses; buy and hold drifts with every reconstitution.",
    )
    caption(
        figure, "Realised: annualised standard deviation of monthly returns against the index, pooled over the paths."
    )
    return figure


# ---------------------------------------------------------------------------- 14. the proposal page
def plot_rebalance_report(
    name: str,
    day: date,
    tiles: Sequence[tuple[str, str]],
    tickets: Sequence[tuple[str, str, str, str, str]],
    frontier: Sequence[tuple[float, float]],
    proposal: tuple[float, float],
    checks: Sequence[tuple[str, str]],
) -> Figure:
    """The page the investment committee signs: the proposal's numbers, its orders, its frontier and its checks."""
    figure = new_figure(11.7, 16.5)
    grid = figure.add_gridspec(
        4, 1, height_ratios=[0.45, 1.8, 0.9, 0.6], hspace=0.42, **_margins(figure, top=1.5, bottom=0.8, left=0.08)
    )
    header = figure.add_subplot(grid[0])
    header.axis("off")
    for index, (label, value) in enumerate(tiles):
        row, column = divmod(index, 3)
        x, y = column * 0.34, 0.85 - row * 0.55
        header.text(x, y, label, fontsize=9, color=PALETTE["muted"], transform=header.transAxes)
        header.text(x, y - 0.3, value, fontsize=17, weight="bold", color=PALETTE["ink"], transform=header.transAxes)
    orders = figure.add_subplot(grid[1])
    orders.axis("off")
    orders.set_title("Orders", loc="left")
    columns = (0.0, 0.2, 0.3, 0.5, 0.72)
    for x, text in zip(columns, ("Instrument", "Side", "Quantity", "Value", "Lots relieved"), strict=True):
        orders.text(x, 0.98, text, fontsize=8.2, color=PALETTE["muted"], transform=orders.transAxes)
    for index, ticket in enumerate(tickets):
        y = 0.94 - index * (0.92 / max(len(tickets), 1))
        for x, text in zip(columns, ticket, strict=True):
            colour = BUY if ticket[1] == "buy" else SELL if x == 0.2 else PALETTE["ink"]
            orders.text(
                x, y, text, fontsize=8, transform=orders.transAxes, color=colour if x == 0.2 else PALETTE["ink"]
            )
    panel = figure.add_subplot(grid[2])
    panel.plot(
        [point[0] for point in frontier],
        [point[1] for point in frontier],
        color=PALETTE["navy"],
        marker="o",
        markersize=3.5,
    )
    panel.scatter(*proposal, s=200, marker="*", color=AMBER, edgecolor=PALETTE["ink"], zorder=4)
    _money_axis(panel, "x")
    _percent_axis(panel, "y", 1)
    style_axes(
        panel,
        title="Where the proposal sits on the frontier",
        xlabel="tax realised",
        ylabel="tracking error",
        grid="both",
    )
    footer = figure.add_subplot(grid[3])
    footer.axis("off")
    footer.set_title("Checks", loc="left")
    for index, (label, value) in enumerate(checks):
        y = 0.85 - index * 0.16
        footer.text(0.0, y, label, fontsize=8.6, transform=footer.transAxes, color=PALETTE["muted"])
        footer.text(0.42, y, value, fontsize=8.6, transform=footer.transAxes, color=PALETTE["ink"])
    title_block(
        figure,
        f"{name}: rebalance proposal",
        f"{day:%d %B %Y}. Prepared by the tax-aware optimiser; checked by the compliance engine.",
    )
    caption(
        figure,
        "Tracking error from the Day 5 factor model; tax at each lot's own federal rate; orders rounded to whole lots "
        "and minimum tickets.",
    )
    return figure
