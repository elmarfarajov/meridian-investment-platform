"""Charts for tax lots and realised gains.

A lot is the unit of tax, so these charts are drawn at the level of the lot:

* **The lot map** - every lot the account has held, from purchase to sale,
  with its holding period, any tacking, and the wash sale adjustments.
* **The wash sale** - one loss harvested too eagerly, and where the loss went.
* **Lot selection** - one sale under four relief methods, and what each costs
  in tax.
* **Two tax codes** - the same disposals under US lot rules and UK share
  matching, which do not agree.
* **Realised gains by year** - netted the way Schedule D nets them.
* **The long-term horizon** - open lots by age, and the gains about to change
  character.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from ..accounting.lots import RealisedLot, Term
from ..accounting.tax import LotChoice, TaxYearSummary
from ..accounting.uk_matching import MatchRule, UkMatchingResult, UkTaxYear
from ..accounting.wash_sales import WashSaleMatch
from ..core.currency import USD
from ..domain.positions import LONG_TERM_HOLDING_DAYS, TaxLot
from ..marketdata.series import TimeSeries
from .accounting import _margins, _money, _thousands
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block, x_of

TERM_COLOURS = {Term.SHORT: PALETTE["teal"], Term.LONG: PALETTE["navy"]}
TERM_HANDLES = [
    Patch(color=TERM_COLOURS[Term.SHORT], label="short-term"),
    Patch(color=TERM_COLOURS[Term.LONG], label="long-term"),
]


# ---------------------------------------------------------------------------- the lot map
def plot_tax_lot_map(realised: Sequence[RealisedLot], open_lots: Sequence[TaxLot], as_of: date) -> Figure:
    """Every lot from acquisition to disposal, with holding periods, tacking and wash sales."""
    rows: list[tuple[str, date, date, date, Term, bool, bool, float | None]] = []
    for item in realised:
        rows.append(
            (
                item.instrument_id,
                item.holding_start,
                item.open_date,
                item.close_date,
                item.term,
                bool(item.wash_sale_basis),
                bool(item.disallowed_loss),
                float(item.gain_base),
            )
        )
    for lot in open_lots:
        term = Term.LONG if lot.is_long_term(as_of) else Term.SHORT
        rows.append(
            (
                lot.instrument_id,
                lot.holding_start,
                lot.open_date,
                as_of,
                term,
                bool(lot.wash_sale_adjustment),
                False,
                None,
            )
        )
    rows.sort(key=lambda row: (row[0], row[2], row[3]))
    figure = new_figure(15.5, max(7.5, 0.17 * len(rows) + 2.6))
    height = figure.get_figheight()
    axis = figure.add_axes((0.14, 0.9 / height, 0.84, 1 - 2.2 / height))
    previous = None
    for index, (instrument_id, start, opened, closed, term, adjusted, disallowed, gain) in enumerate(rows):
        y = len(rows) - index
        if instrument_id != previous:
            axis.axhline(y + 0.5, color=PALETTE["grid"], linewidth=0.8)
            axis.text(x_of(date(2020, 12, 20)), y, instrument_id, ha="right", va="center", fontsize=8.2, weight="bold")
            previous = instrument_id
        colour = TERM_COLOURS[term]
        if start < opened:
            axis.plot([start, opened], [y, y], color=colour, linewidth=4.5, alpha=0.28, solid_capstyle="butt")
        axis.plot(
            [opened, closed],
            [y, y],
            color=colour,
            linewidth=4.5,
            solid_capstyle="butt",
            alpha=0.55 if gain is None else 1,
        )
        if gain is not None:
            axis.scatter([closed], [y], s=26, color=PALETTE["gain"] if gain >= 0 else PALETTE["loss"], zorder=4)
        if adjusted:
            axis.scatter([opened], [y], marker="D", s=30, color=PALETTE["accent"], zorder=5)
        if disallowed:
            axis.scatter([closed], [y], marker="x", s=46, color=PALETTE["accent"], zorder=6)
    axis.set_yticks([])
    axis.set_xlim(x_of(date(2020, 12, 25)), x_of(as_of + timedelta(days=20)))
    axis.axvline(x_of(as_of), color=PALETTE["muted"], linewidth=0.8, linestyle=":")
    style_axes(axis, grid="x")
    axis.spines["left"].set_visible(False)
    axis.legend(
        handles=[
            Line2D([], [], color=TERM_COLOURS[Term.LONG], linewidth=5, label="long-term at sale (or today)"),
            Line2D([], [], color=TERM_COLOURS[Term.SHORT], linewidth=5, label="short-term"),
            Line2D([], [], color=PALETTE["slate"], linewidth=5, alpha=0.3, label="holding period tacked on"),
            Line2D([], [], color=PALETTE["gain"], marker="o", linestyle="", label="sold at a gain"),
            Line2D([], [], color=PALETTE["loss"], marker="o", linestyle="", label="sold at a loss"),
            Line2D([], [], color=PALETTE["accent"], marker="D", linestyle="", label="basis raised by a wash sale"),
            Line2D([], [], color=PALETTE["accent"], marker="x", linestyle="", label="loss disallowed"),
        ],
        loc="upper left",
        ncol=4,
        fontsize=7.8,
    )
    title_block(
        figure,
        "Every tax lot the account has held",
        f"{len(rows)} lots, from acquisition to disposal. Apple shares transferred in carry their 2021 holding "
        "period; wash sale replacements carry the period of the shares sold.",
    )
    caption(figure, "Lots still open run to the valuation date in a lighter shade. FIFO relief throughout.")
    return figure


# ---------------------------------------------------------------------------- the wash sale
def plot_wash_sale(
    matches: Sequence[WashSaleMatch],
    realised: Sequence[RealisedLot],
    replacement_lots: Sequence[TaxLot],
    prices: TimeSeries,
) -> Figure:
    """One harvested loss, the replacement bought inside the window, and where the loss went."""
    first = matches[0]
    sale_day, instrument_id = first.sale_date, first.instrument_id
    sold = [item for item in realised if item.disposal_id == first.disposal_id]
    loss = -float(sum((item.tax_gain_before_wash for item in sold), Decimal(0)))
    disallowed = float(sum((item.disallowed_loss for item in sold), Decimal(0)))
    replacement_days = sorted({match.replacement_date for match in matches if match.disposal_id == first.disposal_id})
    figure = new_figure(15.5, 7.2)
    grid = figure.add_gridspec(1, 3, width_ratios=[1.6, 0.9, 1.0], wspace=0.34, **_margins(figure, bottom=1.0))

    axis = figure.add_subplot(grid[0])
    window = prices.between(sale_day - timedelta(days=75), sale_day + timedelta(days=75))
    axis.plot(window.days, window.floats(), color=PALETTE["navy"], linewidth=1.5, label=f"{instrument_id} close")
    axis.axvspan(
        x_of(sale_day - timedelta(days=30)),
        x_of(sale_day + timedelta(days=30)),
        color=PALETTE["band"],
        zorder=0,
        label="61-day wash sale window",
    )
    found = window.as_of(sale_day)
    level = float(found.value) if found else float(window.last.value)
    axis.scatter([sale_day], [level], s=70, color=PALETTE["loss"], zorder=5)
    annotate(axis, "sold at a loss", (x_of(sale_day), level), xytext=(8, -18), textcoords="offset points")
    for day in replacement_days:
        bought = window.as_of(day)
        if bought:
            axis.scatter([day], [float(bought.value)], s=70, color=PALETTE["accent"], zorder=5)
            annotate(
                axis,
                f"bought back {(day - sale_day).days} days later",
                (x_of(day), float(bought.value)),
                highlight=True,
                xytext=(8, 10),
                textcoords="offset points",
            )
    style_axes(axis, title=f"{instrument_id}: the harvest and the repurchase")
    axis.legend(loc="upper right")

    bars = figure.add_subplot(grid[1])
    allowed = loss - disallowed
    bars.bar(0, loss, color=PALETTE["loss"], width=0.6)
    bars.bar(1, -disallowed, bottom=loss, color=PALETTE["accent"], width=0.6)
    bars.bar(2, allowed, color=PALETTE["slate"], width=0.6)
    for x, height, amount in ((0, loss, loss), (1, loss, -disallowed), (2, allowed, allowed)):
        bars.annotate(
            _money(amount),
            (x, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            weight="bold",
        )
    bars.set_ylim(0, loss * 1.18 if loss else 1)
    bars.set_xticks([0, 1, 2], labels=["loss\nrealised", "disallowed", "loss\nreported"])
    _thousands(bars)
    style_axes(bars, title="The loss, in dollars")

    basis = figure.add_subplot(grid[2])
    lots = [lot for lot in replacement_lots if lot.wash_sale_adjustment]
    book = float(sum((lot.base_cost for lot in lots), Decimal(0)))
    tax = float(sum((lot.tax_basis for lot in lots), Decimal(0)))
    basis.bar(0, book, color=PALETTE["navy"], width=0.55, label="cost paid")
    basis.bar(1, book, color=PALETTE["navy"], width=0.55)
    basis.bar(1, tax - book, bottom=book, color=PALETTE["accent"], width=0.55, label="disallowed loss added")
    for x, height in ((0, book), (1, tax)):
        basis.annotate(
            _money(height),
            (x, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            weight="bold",
        )
    basis.set_xticks([0, 1], labels=["book cost", "tax basis"])
    basis.set_ylim(0, tax * 1.2 if tax else 1)
    _thousands(basis)
    tacked = [(lot.open_date - lot.holding_start).days for lot in lots]
    span = f"{min(tacked)}-{max(tacked)}" if tacked and min(tacked) != max(tacked) else f"{max(tacked, default=0)}"
    style_axes(basis, title=f"The replacement lots (holding period +{span} days)")
    basis.legend(loc="upper left")
    title_block(
        figure,
        "A wash sale: the loss is deferred, not lost",
        f"{instrument_id} sold at a loss on {sale_day:%d %b %Y} and bought back inside 30 days. The disallowed "
        "loss moves into the replacement lots' tax basis - never their book cost - and their holding period tacks.",
    )
    caption(
        figure,
        "IRC 1091. Measured in the tax currency: a euro loss that is a dollar gain is not a wash sale. The other "
        "harvest in the book switched into a fund that is not substantially identical, and its loss stands.",
    )
    return figure


# ---------------------------------------------------------------------------- lot selection
ILLUSTRATION_DATE = date(2026, 1, 15)


def illustrative_lots(instrument_id: str = "US-MSFT") -> list[TaxLot]:
    """Six lots of one holding bought over four years: long- and short-term, above and below today's price.

    The demonstration account's own holdings are nearly all below cost after a
    falling market, where every relief method gives much the same answer. This
    stack is the ordinary case, where the choice matters.
    """
    specification = (
        ("MSFT-1", date(2022, 3, 1), 100, "280.00"),
        ("MSFT-2", date(2023, 6, 15), 80, "330.00"),
        ("MSFT-3", date(2024, 11, 20), 70, "425.00"),
        ("MSFT-4", date(2025, 2, 10), 60, "520.00"),
        ("MSFT-5", date(2025, 7, 1), 50, "505.00"),
        ("MSFT-6", date(2025, 10, 1), 40, "440.00"),
    )
    return [
        TaxLot(
            lot_id=lot_id,
            instrument_id=instrument_id,
            open_date=opened,
            quantity=Decimal(quantity),
            cost_per_unit=Decimal(cost),
            currency=USD,
            transaction_id=lot_id,
        )
        for lot_id, opened, quantity, cost in specification
    ]


def plot_lot_selection(
    lots: Sequence[TaxLot],
    choices: Sequence[LotChoice],
    *,
    instrument_id: str,
    quantity: Decimal,
    price: Decimal,
    as_of: date,
) -> Figure:
    """One sale under four relief methods: which lots, how much gain of each term, and the tax."""
    figure = new_figure(15.5, 7.0)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 1.1], wspace=0.25, **_margins(figure, bottom=1.0))
    scatter = figure.add_subplot(grid[0])
    for lot in lots:
        term = Term.LONG if lot.is_long_term(as_of) else Term.SHORT
        basis = float(lot.base_cost_per_unit + lot.wash_sale_adjustment)
        scatter.scatter(
            [lot.holding_days(as_of)],
            [basis],
            s=float(lot.quantity) * 0.9 + 20,
            color=TERM_COLOURS[term],
            alpha=0.75,
            edgecolor="white",
        )
        scatter.annotate(
            lot.lot_id, (lot.holding_days(as_of), basis), xytext=(7, 6), textcoords="offset points", fontsize=7
        )
    scatter.axhline(float(price), color=PALETTE["accent"], linewidth=1.1)
    annotate(
        scatter,
        f"price today {float(price):,.2f}",
        (0.99, float(price)),
        highlight=True,
        xytext=(0, 5),
        textcoords="offset points",
        xycoords=("axes fraction", "data"),
        ha="right",
    )
    scatter.axvline(LONG_TERM_HOLDING_DAYS, color=PALETTE["muted"], linewidth=0.8, linestyle=":")
    style_axes(
        scatter,
        title=f"Open {instrument_id} lots: tax basis per share against days held",
        xlabel="days held",
        ylabel="tax basis per share (USD)",
    )
    scatter.legend(handles=TERM_HANDLES, loc="upper left")

    bars = figure.add_subplot(grid[1])
    positions = np.arange(len(choices))
    short = np.array([float(choice.short_term) for choice in choices])
    long = np.array([float(choice.long_term) for choice in choices])
    taxes = np.array([float(choice.tax) for choice in choices])
    bars.bar(positions - 0.2, short, width=0.38, color=TERM_COLOURS[Term.SHORT], label="short-term gain")
    bars.bar(positions + 0.2, long, width=0.38, color=TERM_COLOURS[Term.LONG], label="long-term gain")
    bars.scatter(positions, taxes, color=PALETTE["accent"], s=80, zorder=5, label="federal tax (negative: a saving)")
    for x, value in zip(positions, taxes, strict=True):
        bars.annotate(
            f"tax {_money(value, signed=True)}",
            (x, value),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=8.3,
            color=PALETTE["accent"],
            weight="bold",
        )
    extremes = np.concatenate([short, long, taxes, [0.0]])
    spread = float(extremes.max() - extremes.min()) or 1.0
    bars.set_ylim(float(extremes.min()) - 0.12 * spread, float(extremes.max()) + 0.2 * spread)
    bars.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    bars.set_xticks(positions, labels=[choice.method for choice in choices])
    _thousands(bars)
    fifo = next((choice for choice in choices if choice.method == "FIFO"), choices[0])
    best = min(choices, key=lambda choice: choice.tax)
    style_axes(bars, title=f"Selling {float(quantity):,.0f} shares at {float(price):,.2f}: gain and tax by method")
    bars.legend(loc="lower left")
    annotate(
        bars,
        f"minimum tax is {_money(float(fifo.tax - best.tax))} better than FIFO",
        (0.02, 0.95),
        xycoords="axes fraction",
        highlight=True,
    )
    title_block(
        figure,
        "Which lots you sell is worth money",
        "The same sale relieves different lots under each method. Minimum tax sells losses first, then the gains "
        "cheapest to tax - greedy is optimal because each share's tax does not depend on the others.",
    )
    caption(
        figure,
        "Illustrative lots: the demonstration account's own holdings sit below cost after a falling market, where the "
        "methods barely differ. Top federal rates: 37% short-term, 20% long-term, each plus the 3.8% NIIT.",
    )
    return figure


# ---------------------------------------------------------------------------- two tax codes
def plot_us_vs_uk(
    us_years: Sequence[TaxYearSummary],
    uk_years: Sequence[UkTaxYear],
    realised: Sequence[RealisedLot],
    uk: UkMatchingResult,
    gbp_per_usd: dict[date, float],
    *,
    pool_instrument: str,
    lot_costs: Sequence[tuple[date, float]],
) -> Figure:
    """The same disposals under US lot rules and UK share matching."""
    figure = new_figure(16.0, 9.2)
    grid = figure.add_gridspec(
        2, 2, height_ratios=[1.0, 1.05], hspace=0.42, wspace=0.22, **_margins(figure, bottom=0.95)
    )
    per_disposal = figure.add_subplot(grid[0, :])
    us_by_disposal: dict[str, float] = defaultdict(float)
    for record in realised:
        us_by_disposal[record.disposal_id] += float(record.reportable_gain)
    disposals = [item for item in uk.disposals if item.disposal_id in us_by_disposal]
    positions = np.arange(len(disposals))
    us_values = [us_by_disposal[item.disposal_id] for item in disposals]
    uk_values = [float(item.gain) / gbp_per_usd.get(item.day, 0.79) for item in disposals]
    per_disposal.bar(positions - 0.2, us_values, width=0.38, color=PALETTE["navy"], label="US: specific lots, in USD")
    per_disposal.bar(
        positions + 0.2,
        uk_values,
        width=0.38,
        color=PALETTE["violet"],
        label="UK: share matching, in GBP (shown in USD)",
    )
    for index, item in enumerate(disposals):
        rules = item.quantity_by_rule()
        if MatchRule.BED_AND_BREAKFAST in rules or MatchRule.SAME_DAY in rules:
            per_disposal.scatter(
                [index + 0.2], [uk_values[index]], marker="*", s=110, color=PALETTE["accent"], zorder=5
            )
            per_disposal.annotate(
                "US: loss disallowed\nUK: matched to the repurchase",
                (index + 0.2, uk_values[index]),
                xytext=(10, 6),
                textcoords="offset points",
                fontsize=7.6,
                color=PALETTE["accent"],
            )
    per_disposal.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    per_disposal.set_xticks(
        positions, labels=[f"{item.instrument_id}\n{item.day:%b %y}" for item in disposals], fontsize=6.8
    )
    _thousands(per_disposal)
    style_axes(per_disposal, title="Every disposal, measured both ways (a star: matched under the UK 30-day rule)")
    per_disposal.legend(loc="lower left")

    years = figure.add_subplot(grid[1, 0])
    labels = [str(item.year) for item in us_years] + [item.tax_year for item in uk_years]
    values = [float(item.net) for item in us_years] + [float(item.net) for item in uk_years]
    colours = [PALETTE["navy"]] * len(us_years) + [PALETTE["violet"]] * len(uk_years)
    years.bar(range(len(labels)), values, color=colours, width=0.6)
    for index, value in enumerate(values):
        years.annotate(
            _money(value, signed=True),
            (index, value),
            xytext=(0, 4 if value >= 0 else -12),
            textcoords="offset points",
            ha="center",
            fontsize=8.2,
        )
    years.axvline(len(us_years) - 0.5, color=PALETTE["muted"], linewidth=0.8)
    years.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    years.set_xticks(range(len(labels)), labels=labels)
    _thousands(years)
    style_axes(years, title="Net gains by tax year: calendar years in USD, then UK years (6 April) in GBP")

    pool = figure.add_subplot(grid[1, 1])
    states = uk.pools.get(pool_instrument, [])
    if states:
        pool.step(
            [state.day for state in states],
            [float(state.average_cost) for state in states],
            where="post",
            color=PALETTE["violet"],
            linewidth=1.8,
            label="section 104 pool, average cost (GBP)",
        )
    if lot_costs:
        pool.scatter(
            [day for day, _ in lot_costs],
            [cost for _, cost in lot_costs],
            color=PALETTE["navy"],
            s=26,
            label="US lots, cost per share (converted to GBP)",
        )
    style_axes(pool, title=f"{pool_instrument}: one pool against many lots")
    pool.legend(loc="best")
    title_block(
        figure,
        "One book, two tax codes",
        "A US person resident in the UK reports every disposal twice. The US taxes lots in dollars; the UK matches "
        "same-day, then 30-day, then pooled shares in sterling. The answers differ in size and sometimes in sign.",
    )
    caption(
        figure,
        "UK gains are converted to dollars at the disposal date for the comparison only; each code's own yearly "
        "figures are in its own currency below.",
    )
    return figure


# ---------------------------------------------------------------------------- realised gains
def plot_realised_gains(years: Sequence[TaxYearSummary], realised: Sequence[RealisedLot]) -> Figure:
    """Gains and losses netted as Schedule D nets them, and the realised result split into price and currency."""
    figure = new_figure(15.5, 7.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.1, 1.0], wspace=0.25, **_margins(figure, bottom=1.35))
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(years))
    width = 0.19
    series = [
        ("short-term gains", [float(item.short_term_gains) for item in years], PALETTE["teal"], -1.5),
        ("short-term losses", [float(item.short_term_losses) for item in years], "#7FC1B9", -0.5),
        ("long-term gains", [float(item.long_term_gains) for item in years], PALETTE["navy"], 0.5),
        ("long-term losses", [float(item.long_term_losses) for item in years], "#7AA2CF", 1.5),
    ]
    for label, values, colour, offset in series:
        axis.bar(positions + offset * width, values, width=width * 0.95, color=colour, label=label)
    disallowed = [float(item.disallowed) for item in years]
    axis.bar(
        positions - 0.5 * width,
        [-value for value in disallowed],
        width=width * 0.95,
        bottom=[float(item.short_term_losses) for item in years],
        color="none",
        edgecolor=PALETTE["accent"],
        hatch="///",
        linewidth=0.8,
        label="loss deferred by the wash sale rule",
    )
    nets = [float(item.net) for item in years]
    axis.plot(positions, nets, color=PALETTE["ink"], marker="D", linewidth=0, markersize=7, label="net for the year")
    for x, value, item in zip(positions, nets, years, strict=True):
        carry = sum(float(part) for part in item.carryforward())
        text = f"net {_money(value, signed=True)}" + (f"\ncarried forward {_money(carry)}" if carry else "")
        axis.annotate(text, (x, value), xytext=(10, -4), textcoords="offset points", fontsize=7.8)
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.set_xticks(positions, labels=[str(item.year) for item in years])
    _thousands(axis)
    style_axes(axis, title="Realised gains and losses by tax year (USD)")
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=3, fontsize=7.6)

    split = figure.add_subplot(grid[1])
    price: dict[str, float] = defaultdict(float)
    fx: dict[str, float] = defaultdict(float)
    for record in realised:
        price[record.instrument_id] += float(record.price_gain_base)
        fx[record.instrument_id] += float(record.fx_gain_base)
    keys = sorted(price, key=lambda key: price[key] + fx[key])
    rows = np.arange(len(keys))
    split.barh(rows - 0.18, [price[key] for key in keys], height=0.34, color=PALETTE["navy"], label="price")
    split.barh(rows + 0.18, [fx[key] for key in keys], height=0.34, color=PALETTE["violet"], label="currency")
    split.set_yticks(rows, labels=keys)
    split.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    _thousands(split, which="x")
    style_axes(split, title="Realised result by holding: price and currency (USD, book basis)", grid="x")
    split.legend(loc="lower right")
    title_block(
        figure,
        "Realised gains, the way the return reports them",
        "Short-term against short-term, long-term against long-term, then across. A net loss is deductible up to "
        "$3,000 a year and the rest carries forward, keeping its character.",
    )
    caption(
        figure,
        "A falling market and two tax-loss harvests: most of the account's realised result is loss, much of it "
        "short-term - and part of it deferred by the wash sale rule into the replacement lots.",
    )
    return figure


# ---------------------------------------------------------------------------- the long-term horizon
def plot_unrealised_horizon(
    lots: Sequence[TaxLot],
    prices: dict[str, float],
    rates: dict[str, float],
    scales: dict[str, float],
    as_of: date,
) -> Figure:
    """Open lots by days held against their unrealised gain, and the short-term lots' road to long-term."""
    figure = new_figure(15.5, 7.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.45, 1.0], wspace=0.3, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    pending: list[tuple[str, int, float]] = []
    for lot in lots:
        price = prices.get(lot.instrument_id)
        if price is None:
            continue
        value = float(lot.quantity) * price * scales.get(lot.instrument_id, 1.0) * rates.get(lot.currency.code, 1.0)
        gain = value - float(lot.tax_basis)
        days = lot.holding_days(as_of)
        term = Term.LONG if days > LONG_TERM_HOLDING_DAYS else Term.SHORT
        axis.scatter([days], [gain], s=max(value / 2500, 12), color=TERM_COLOURS[term], alpha=0.7, edgecolor="white")
        if abs(gain) > 40_000:
            axis.annotate(lot.instrument_id, (days, gain), xytext=(6, 4), textcoords="offset points", fontsize=7)
        if term is Term.SHORT:
            pending.append((f"{lot.instrument_id}  {lot.lot_id}", (lot.long_term_from() - as_of).days, gain))
    axis.axvspan(LONG_TERM_HOLDING_DAYS - 90, LONG_TERM_HOLDING_DAYS, color=PALETTE["band"], zorder=0)
    axis.axvline(LONG_TERM_HOLDING_DAYS, color=PALETTE["accent"], linewidth=1.1)
    low = axis.get_ylim()[0]
    annotate(
        axis,
        "one year and a day: long-term",
        (LONG_TERM_HOLDING_DAYS, low),
        highlight=True,
        xytext=(6, 12),
        textcoords="offset points",
    )
    axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    _thousands(axis)
    style_axes(
        axis,
        title=f"Open lots on {as_of:%d %b %Y}: unrealised gain on tax basis against days held",
        xlabel="days held (after tacking)",
        ylabel="USD",
    )
    axis.legend(handles=TERM_HANDLES, loc="upper right")

    road = figure.add_subplot(grid[1])
    pending.sort(key=lambda item: item[1])
    labels = [label for label, _, _ in pending]
    remaining = [days for _, days, _ in pending]
    gains = [gain for _, _, gain in pending]
    road.barh(range(len(pending)), remaining, color=[PALETTE["gain"] if g >= 0 else PALETTE["loss"] for g in gains])
    for row, (days, gain) in enumerate(zip(remaining, gains, strict=True)):
        road.text(days + 4, row, f"{days} days; {_money(gain, signed=True)} at stake", va="center", fontsize=7.8)
    road.set_yticks(range(len(pending)), labels=labels, fontsize=7.6)
    road.set_xlim(0, max(remaining, default=365) * 1.55)
    road.invert_yaxis()
    style_axes(road, title="Short-term lots: days until long-term", xlabel="days", grid="x")
    title_block(
        figure,
        "The long-term horizon",
        "A short-term gain sold today is taxed at up to 40.8%; held past one year, at 23.8%. A short-term loss is "
        "the opposite case: worth realising before it turns.",
    )
    caption(figure, "Bubble size is market value. Green bars are gains that wait for the lower rate; red, losses.")
    return figure
