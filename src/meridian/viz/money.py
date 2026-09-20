"""Charts for the things that look like details until they cost money.

Allocation and day-count conventions are the two places where a plausible-looking
shortcut leaks cash: a naive division loses pennies on every fee split, and the
wrong day count misstates every accrual. Both are easier to argue about with a
picture than with a paragraph.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
from matplotlib.figure import Figure

from ..core.daycount import DayCountConvention, compare_conventions
from ..core.money import Money
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block


def plot_allocation(
    amount: Money,
    weights: tuple[float, ...] = (1 / 3, 1 / 3, 1 / 3),
    labels: tuple[str, ...] | None = None,
) -> Figure:
    """Splitting an amount by weights, and what the naive version loses.

    The naive split rounds each share independently and the total no longer adds
    up. The allocation used here hands the remainder out one minor unit at a time
    to the shares with the largest fractional part, so the parts always sum to the
    whole - which is the only acceptable behaviour for a fee, a distribution or a
    tax lot.
    """
    allocated = amount.allocate(weights)
    precision = amount.currency.precision
    naive = [(amount.amount * Decimal(str(weight))).quantize(precision) for weight in weights]
    names = labels or tuple(f"Account {index + 1}" for index in range(len(weights)))

    figure = new_figure(11.0, 4.8)
    grid = figure.add_gridspec(
        1, 2, width_ratios=[1.25, 1.0], wspace=0.24, top=0.79, bottom=0.16, left=0.08, right=0.975
    )
    axis = figure.add_subplot(grid[0, 0])
    positions = np.arange(len(weights))
    width = 0.38
    axis.bar(
        positions - width / 2,
        [float(item.amount) for item in allocated],
        width=width,
        color=PALETTE["navy"],
        label="Conserving allocation",
    )
    axis.bar(
        positions + width / 2,
        [float(value) for value in naive],
        width=width,
        color=PALETTE["loss"],
        label="Naive rounding",
    )
    axis.set_xticks(positions, labels=list(names))
    style_axes(axis, title="Shares of the same amount", ylabel=f"Amount ({amount.currency.code})")
    axis.legend(loc="lower right")

    totals = figure.add_subplot(grid[0, 1])
    allocated_total = sum((item.amount for item in allocated), Decimal(0))
    naive_total = sum(naive, Decimal(0))
    differences = [float(allocated_total - amount.amount), float(naive_total - amount.amount)]
    totals.bar(
        ["Conserving", "Naive"],
        differences,
        color=[PALETTE["gain"], PALETTE["loss"]],
        width=0.5,
    )
    totals.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    style_axes(totals, title="Error against the original amount", ylabel=amount.currency.code)
    limit = max(0.02, max(abs(value) for value in differences) * 1.6)
    totals.set_ylim(-limit, limit)
    annotate(
        totals,
        f"naive split is out by {abs(differences[1]):.2f} {amount.currency.code}",
        xy=(0.04, 0.88),
        xycoords="axes fraction",
        highlight=True,
        fontsize=8.5,
    )

    title_block(
        figure,
        f"Allocating {amount}",
        "Fowler's algorithm: floor every share, then hand the remaining minor units to the largest "
        "fractional parts. The parts always sum back to the whole.",
    )
    caption(
        figure,
        f"Weights {', '.join(f'{weight:.4g}' for weight in weights)}. "
        f"Rounding to {amount.currency.minor_units} decimal places, banker's rounding.",
    )
    return figure


def plot_daycount_comparison(
    start: date,
    end: date,
    *,
    notional: int = 10_000_000,
    annual_rate: str = "0.05",
) -> Figure:
    """Year fractions and accrued interest under every convention, over the same period."""
    results = compare_conventions(start, end, notional=notional, annual_rate=annual_rate)
    conventions = list(results)
    fractions = [float(results[convention][0]) for convention in conventions]
    accrued = [float(results[convention][1]) for convention in conventions]
    labels = [convention.value for convention in conventions]

    figure = new_figure(12.0, 5.2)
    grid = figure.add_gridspec(1, 2, wspace=0.26, top=0.80, bottom=0.22, left=0.07, right=0.975)
    axis = figure.add_subplot(grid[0, 0])
    colours = [PALETTE["navy"] if convention.value.startswith("ACT") else PALETTE["teal"] for convention in conventions]
    axis.bar(labels, fractions, color=colours, width=0.62)
    axis.tick_params(axis="x", rotation=40)
    for label in axis.get_xticklabels():
        label.set_horizontalalignment("right")
    style_axes(axis, title="Year fraction for the same period", ylabel="Years")
    axis.set_ylim(min(fractions) * 0.96, max(fractions) * 1.02)

    spread_axis = figure.add_subplot(grid[0, 1])
    baseline = min(accrued)
    spread = [value - baseline for value in accrued]
    spread_axis.bar(labels, spread, color=colours, width=0.62)
    spread_axis.tick_params(axis="x", rotation=40)
    for label in spread_axis.get_xticklabels():
        label.set_horizontalalignment("right")
    style_axes(
        spread_axis,
        title=f"Interest on {notional:,} at {float(annual_rate) * 100:.0f}%, above the lowest convention",
        ylabel="Currency units",
    )
    annotate(
        spread_axis,
        f"{max(spread):,.0f} between the highest and lowest convention",
        xy=(0.97, 0.94),
        xycoords="axes fraction",
        ha="right",
        highlight=True,
    )

    title_block(
        figure,
        f"Day-count conventions, {start.isoformat()} to {end.isoformat()}",
        "The convention is part of the contract, not a preference. On one period, on one notional, "
        "the choice is worth real money.",
    )
    caption(
        figure,
        "ACT/ACT ICMA is evaluated with the period itself as the reference coupon period; "
        "BUS/252 counts business days on the NYSE calendar.",
    )
    return figure


def plot_rounding_drift(base: Money, periods: int = 240, weights: tuple[float, ...] = (0.5, 0.3, 0.2)) -> Figure:
    """Repeated allocation: the conserving version never drifts, the naive one does."""
    precision = base.currency.precision
    conserving_drift: list[float] = []
    naive_drift: list[float] = []
    conserving_total = Decimal(0)
    naive_total = Decimal(0)
    for period in range(periods):
        amount = base + Money(Decimal(period % 7) / 100, base.currency)
        conserving_total += sum((item.amount for item in amount.allocate(weights)), Decimal(0)) - amount.amount
        naive_total += (
            sum(((amount.amount * Decimal(str(weight))).quantize(precision) for weight in weights), Decimal(0))
            - amount.amount
        )
        conserving_drift.append(float(conserving_total))
        naive_drift.append(float(naive_total))

    figure = new_figure(10.5, 4.6)
    axis = figure.add_subplot()
    figure.subplots_adjust(top=0.78, bottom=0.15, left=0.09, right=0.97)
    axis.plot(naive_drift, color=PALETTE["loss"], label="Naive rounding")
    axis.plot(conserving_drift, color=PALETTE["gain"], label="Conserving allocation", linewidth=2.2)
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    style_axes(axis, xlabel="Allocation", ylabel=f"Cumulative error ({base.currency.code})")
    axis.legend(loc="lower left")
    annotate(
        axis,
        f"after {periods} allocations the naive method is out by {naive_drift[-1]:,.2f} {base.currency.code}",
        xy=(0.04, 0.9),
        xycoords="axes fraction",
        highlight=True,
    )
    title_block(
        figure,
        "Rounding error accumulates",
        "The same split repeated: one method stays exactly on zero, the other walks away from it.",
    )
    caption(
        figure,
        f"Weights {weights}, amounts varying by a few cents each period, {base.currency.minor_units} decimal places.",
    )
    return figure


def convention_table(start: date, end: date) -> list[tuple[str, str, str]]:
    """Rows for the CLI: convention, year fraction, denominator."""
    return [
        (convention.value, f"{float(fraction):.8f}", convention.denominator_label)
        for convention, (fraction, _) in compare_conventions(start, end).items()
    ]


__all__ = [
    "DayCountConvention",
    "convention_table",
    "plot_allocation",
    "plot_daycount_comparison",
    "plot_rounding_drift",
]
