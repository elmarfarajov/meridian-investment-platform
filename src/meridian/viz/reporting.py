"""The pages of the client report that no single module owns: the cover, the summary, holdings, trading, notes.

Every page is A3 portrait (11.7 x 16.5 inches), the size of the one-page
reports the performance, risk, compliance and rebalancing modules already
draw, so the pack reads as one document. The pages take plain inputs; the data
is gathered in :mod:`meridian.reporting.client_pack`.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from datetime import date

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from .accounting import _margins, _money
from .style import PALETTE, new_figure, style_axes

PAGE = (11.7, 16.5)
NAVY = PALETTE["navy"]


def _footer(figure: Figure, page: int, total: int, account: str) -> None:
    figure.text(
        0.05,
        0.018,
        f"{account} · Meridian Investment Platform · for the client's use only",
        fontsize=7.5,
        color=PALETTE["muted"],
    )
    figure.text(0.95, 0.018, f"{page} / {total}", fontsize=7.5, color=PALETTE["muted"], ha="right")


def _heading(figure: Figure, title: str, subtitle: str) -> None:
    figure.patches.append(Rectangle((0, 0.955), 1, 0.045, transform=figure.transFigure, color=NAVY, zorder=0))
    figure.text(0.05, 0.972, title, fontsize=17, weight="bold", color="white", va="center")
    figure.text(0.95, 0.972, subtitle, fontsize=9, color="#D7DEE8", va="center", ha="right")


def _tiles(figure: Figure, tiles: Sequence[tuple[str, str, str]], top: float, columns: int = 3) -> None:
    """Label, value, note - in a grid of boxes."""
    width = 0.9 / columns
    for index, (label, value, note) in enumerate(tiles):
        row, column = divmod(index, columns)
        x = 0.05 + column * width
        y = top - row * 0.085
        figure.patches.append(
            Rectangle(
                (x + 0.004, y - 0.07),
                width - 0.012,
                0.075,
                transform=figure.transFigure,
                color=PALETTE["band"],
                zorder=0,
            )
        )
        figure.text(x + 0.015, y - 0.012, label, fontsize=8.5, color=PALETTE["muted"])
        figure.text(x + 0.015, y - 0.042, value, fontsize=17, weight="bold", color=PALETTE["ink"])
        figure.text(x + 0.015, y - 0.062, note, fontsize=7.8, color=PALETTE["muted"])


# ---------------------------------------------------------------------------- the cover
def plot_cover(
    client: str,
    account: str,
    portfolio: str,
    period: tuple[date, date],
    prepared: date,
    contents: Sequence[str],
    total_pages: int,
) -> Figure:
    figure = new_figure(*PAGE)
    figure.patches.append(Rectangle((0, 0.62), 1, 0.38, transform=figure.transFigure, color=NAVY, zorder=0))
    figure.patches.append(
        Rectangle((0.05, 0.615), 0.12, 0.006, transform=figure.transFigure, color=PALETTE["accent"], zorder=1)
    )
    figure.text(0.05, 0.93, "MERIDIAN", fontsize=13, weight="bold", color="white")
    figure.text(0.05, 0.905, "Investment Platform", fontsize=10, color="#D7DEE8")
    figure.text(0.05, 0.78, "Quarterly client report", fontsize=30, weight="bold", color="white")
    figure.text(0.05, 0.745, f"{portfolio}", fontsize=16, color="white")
    figure.text(0.05, 0.715, f"{period[0]:%d %B %Y} to {period[1]:%d %B %Y}", fontsize=11, color="#D7DEE8")
    figure.text(0.05, 0.565, "Prepared for", fontsize=9, color=PALETTE["muted"])
    figure.text(0.05, 0.54, client, fontsize=15, weight="bold", color=PALETTE["ink"])
    figure.text(0.05, 0.518, account, fontsize=10, color=PALETTE["ink"])
    figure.text(0.05, 0.49, f"Prepared {prepared:%d %B %Y}", fontsize=9, color=PALETTE["muted"])
    figure.text(0.05, 0.43, "Contents", fontsize=11, weight="bold", color=PALETTE["ink"])
    for index, item in enumerate(contents):
        figure.text(0.05, 0.40 - index * 0.026, f"{index + 2:>2}", fontsize=10, color=PALETTE["accent"], weight="bold")
        figure.text(0.09, 0.40 - index * 0.026, item, fontsize=10, color=PALETTE["ink"])
    _footer(figure, 1, total_pages, account)
    return figure


# ---------------------------------------------------------------------------- the summary
def plot_summary(
    tiles: Sequence[tuple[str, str, str]],
    growth: tuple[Sequence[date], Sequence[float], Sequence[float]],
    allocation: Sequence[tuple[str, float]],
    commentary: Sequence[str],
    account: str,
    as_of: date,
    page: int,
    total_pages: int,
) -> Figure:
    figure = new_figure(*PAGE)
    _heading(figure, "Summary", f"as of {as_of:%d %B %Y}")
    _tiles(figure, tiles, top=0.93)
    grid = figure.add_gridspec(
        3,
        2,
        height_ratios=[1.2, 1.0, 0.1],
        width_ratios=[1.6, 1.0],
        hspace=0.35,
        wspace=0.28,
        **_margins(figure, top=4.4, bottom=1.2, left=0.08, right=0.95),
    )
    axis = figure.add_subplot(grid[0, 0])
    days, portfolio, benchmark = growth
    axis.plot(days, portfolio, color=NAVY, label="portfolio")
    axis.plot(days, benchmark, color=PALETTE["slate"], linestyle="--", label="policy benchmark")
    style_axes(axis, title="Growth of 100 since inception", grid="both")
    axis.legend(loc="upper left")
    pie = figure.add_subplot(grid[0, 1])
    labels = [item[0] for item in allocation]
    values = [item[1] for item in allocation]
    colours = [NAVY, PALETTE["teal"], PALETTE["violet"], PALETTE["sky"], PALETTE["slate"], PALETTE["gain"]]
    pie.pie(
        values,
        colors=colours[: len(values)],
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": "white"},
    )
    pie.legend(
        [f"{label} {value:.1%}" for label, value in zip(labels, values, strict=True)],
        loc="center left",
        bbox_to_anchor=(0.9, 0.5),
        fontsize=8,
    )
    pie.set_title("Asset allocation", loc="left")
    notes = figure.add_subplot(grid[1, :])
    notes.axis("off")
    notes.set_title("The quarter in brief", loc="left")
    for index, paragraph in enumerate(commentary):
        notes.text(
            0.0,
            0.92 - index * 0.2,
            textwrap.fill(paragraph, 135),
            fontsize=9.6,
            color=PALETTE["ink"],
            va="top",
            transform=notes.transAxes,
            linespacing=1.4,
        )
    _footer(figure, page, total_pages, account)
    return figure


# ---------------------------------------------------------------------------- holdings and tax
def plot_holdings(
    rows: Sequence[tuple[str, str, float, float, float, float, float, float]],
    cash: float,
    nav: float,
    account: str,
    as_of: date,
    page: int,
    total_pages: int,
) -> Figure:
    """Every holding with its value, weight, unrealised gain by holding period, and its weight after the rebalance.

    ``rows`` are (instrument, asset class, quantity, value, weight, long-term gain, short-term gain, weight after).
    """
    figure = new_figure(*PAGE)
    _heading(figure, "Holdings and tax position", f"as of {as_of:%d %B %Y}")
    table = figure.add_axes((0.05, 0.47, 0.9, 0.46))
    table.axis("off")
    headers = (
        "Instrument",
        "Class",
        "Quantity",
        "Value",
        "Weight",
        "Unrealised LT",
        "Unrealised ST",
        "After rebalance",
    )
    xs = (0.0, 0.16, 0.30, 0.42, 0.54, 0.64, 0.77, 0.9)
    for x, header in zip(xs, headers, strict=True):
        table.text(x, 1.0, header, fontsize=8.4, weight="bold", color=PALETTE["muted"], transform=table.transAxes)
    step = 0.9 / (len(rows) + 2)
    for index, row in enumerate(rows):
        y = 0.96 - (index + 1) * step
        if index % 2 == 0:
            table.add_patch(
                Rectangle(
                    (-0.01, y - step * 0.3), 1.02, step, color=PALETTE["band"], transform=table.transAxes, zorder=0
                )
            )
        values = (
            row[0],
            row[1],
            f"{row[2]:,.0f}",
            _money(row[3]),
            f"{row[4]:.1%}",
            _money(row[5], signed=True),
            _money(row[6], signed=True),
            f"{max(row[7], 0.0):.1%}",
        )
        for column, (x, value) in enumerate(zip(xs, values, strict=True)):
            colour = PALETTE["ink"]
            if column in (5, 6):
                colour = PALETTE["gain"] if value.startswith("+") else PALETTE["loss"]
            table.text(x, y, value, fontsize=8.4, color=colour, transform=table.transAxes)
    y = 0.96 - (len(rows) + 1) * step
    table.text(0.0, y, "Cash", fontsize=8.4, transform=table.transAxes)
    table.text(0.42, y, _money(cash), fontsize=8.4, transform=table.transAxes)
    table.text(0.54, y, f"{cash / nav:.1%}", fontsize=8.4, transform=table.transAxes)
    chart = figure.add_axes((0.08, 0.08, 0.84, 0.32))
    names = [row[0] for row in rows]
    long_term = np.array([row[5] for row in rows])
    short_term = np.array([row[6] for row in rows])
    positions = np.arange(len(rows))
    chart.bar(positions - 0.2, long_term, width=0.4, color=PALETTE["sky"], label="long-term (23.8%)")
    chart.bar(positions + 0.2, short_term, width=0.4, color=PALETTE["violet"], label="short-term (40.8%)")
    chart.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    chart.set_xticks(positions, labels=names, rotation=40, ha="right", fontsize=8)
    chart.yaxis.set_major_formatter(lambda value, _: _money(value))
    style_axes(chart, title="Unrealised gains and losses by holding period: what selling each would realise", grid="y")
    chart.legend(loc="upper right")
    _footer(figure, page, total_pages, account)
    return figure


# ---------------------------------------------------------------------------- trading and costs
def plot_trading(
    tiles: Sequence[tuple[str, str, str]],
    rows: Sequence[tuple[str, str, str, str, str, str]],
    components: Sequence[tuple[str, float]],
    account: str,
    trade_date: date,
    page: int,
    total_pages: int,
) -> Figure:
    """The account's share of the rebalance's trading: the orders, their prices and what they cost.

    ``rows`` are (instrument, side, requested, allocated, average price, cost in bp); ``components`` (name, bp).
    """
    figure = new_figure(*PAGE)
    _heading(figure, "Trading and costs", f"traded {trade_date:%d %B %Y}")
    _tiles(figure, tiles, top=0.93)
    table = figure.add_axes((0.05, 0.36, 0.9, 0.4))
    table.axis("off")
    headers = ("Instrument", "Side", "Requested", "Allocated", "Average price", "Cost against decision")
    xs = (0.0, 0.2, 0.32, 0.47, 0.62, 0.8)
    for x, header in zip(xs, headers, strict=True):
        table.text(x, 1.0, header, fontsize=8.4, weight="bold", color=PALETTE["muted"], transform=table.transAxes)
    step = 0.95 / (len(rows) + 1)
    for index, row in enumerate(rows):
        y = 0.97 - (index + 1) * step
        if index % 2 == 0:
            table.add_patch(
                Rectangle(
                    (-0.01, y - step * 0.3), 1.02, step, color=PALETTE["band"], transform=table.transAxes, zorder=0
                )
            )
        for column, (x, value) in enumerate(zip(xs, row, strict=True)):
            colour = PALETTE["ink"]
            if column == 1:
                colour = PALETTE["teal"] if value == "buy" else PALETTE["loss"]
            table.text(x, y, value, fontsize=8.2, color=colour, transform=table.transAxes)
    chart = figure.add_axes((0.1, 0.07, 0.82, 0.24))
    names = [item[0] for item in components]
    values = [item[1] for item in components]
    chart.bar(
        range(len(values)),
        values,
        color=[PALETTE["gain"] if value < 0 else PALETTE["violet"] for value in values],
        width=0.6,
    )
    for index, height in enumerate(values):
        chart.text(index, height, f"{height:+.1f}", ha="center", va="bottom" if height >= 0 else "top", fontsize=8.4)
    chart.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    chart.set_xticks(range(len(values)), labels=names, fontsize=8.4)
    chart.yaxis.set_major_formatter(lambda value, _: f"{value:,.0f} bp")
    style_axes(
        chart, title="Where the cost came from, basis points of the orders' value (implementation shortfall)", grid="y"
    )
    _footer(figure, page, total_pages, account)
    return figure


# ---------------------------------------------------------------------------- notes
def plot_notes(sections: Sequence[tuple[str, str]], account: str, page: int, total_pages: int) -> Figure:
    figure = new_figure(*PAGE)
    _heading(figure, "Methodology and important information", "")
    y = 0.92
    for title, text in sections:
        figure.text(0.05, y, title, fontsize=11, weight="bold", color=PALETTE["ink"])
        wrapped = "\n".join(textwrap.fill(paragraph, 150) for paragraph in text.split("\n"))
        figure.text(0.05, y - 0.012, wrapped, fontsize=8.8, color=PALETTE["ink"], va="top", linespacing=1.45)
        y -= 0.034 + (wrapped.count("\n") + 1) * 0.0118
    _footer(figure, page, total_pages, account)
    return figure
