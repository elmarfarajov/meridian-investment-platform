"""The Day 3 charts: the book of record, tax lots and reconciliation.

Every chart is drawn from the demonstration book built by
:func:`~meridian.services.demo_accounting.build_demo_accounting`, which is
deterministic, so the gallery, the documentation and the pull request always
show the same numbers. The data each chart needs is prepared here rather than
in the chart functions, which take plain inputs and can draw any book.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from matplotlib.figure import Figure

from .accounting.tax import compare_lot_methods
from .domain.instruments import instrument_price_scale
from .services.demo_accounting import DemoAccounting, build_demo_accounting
from .services.demo_market import DEMO_END
from .viz.accounting import (
    plot_cash_ladder,
    plot_fx_separation,
    plot_income_calendar,
    plot_nav_history,
    plot_restatement,
    plot_settlement_cycles,
    plot_trial_balance,
    plot_valuation_waterfall,
)
from .viz.reconciliation import plot_reconciliation_dashboard, plot_reconciliation_statement, statement_lines
from .viz.tax import (
    ILLUSTRATION_DATE,
    illustrative_lots,
    plot_lot_selection,
    plot_realised_gains,
    plot_tax_lot_map,
    plot_unrealised_horizon,
    plot_us_vs_uk,
    plot_wash_sale,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

WATERFALL_YEAR = 2025
FUNDING_WINDOW = (date(2024, 3, 28), date(2024, 4, 26), date(2024, 4, 2))


def _demo() -> DemoAccounting:
    return build_demo_accounting()


def waterfall_chart() -> Figure:
    demo = _demo()
    start, end = date(WATERFALL_YEAR - 1, 12, 31), date(WATERFALL_YEAR, 12, 31)
    return plot_valuation_waterfall(demo.bridge(start, end), title=f"Where the value went in {WATERFALL_YEAR}")


def nav_chart() -> Figure:
    demo = _demo()
    return plot_nav_history(demo.valuations, demo.daily_bridges, demo.book, demo.instruments)


def fx_chart() -> Figure:
    demo = _demo()
    return plot_fx_separation(demo.valuations[-1], demo.fx_paths())


def cash_chart() -> Figure:
    start, end, ladder_day = FUNDING_WINDOW
    return plot_cash_ladder(_demo().book, start, end, ladder_day)


def settlement_chart() -> Figure:
    demo = _demo()
    return plot_settlement_cycles(demo.book, demo.instruments)


def income_chart() -> Figure:
    demo = _demo()
    return plot_income_calendar(demo.book, demo.instruments)


def trial_balance_chart() -> Figure:
    return plot_trial_balance(_demo().book, DEMO_END)


def restatement_chart() -> Figure:
    restatement = _demo().restatement
    version = restatement.correction
    transaction = version.transaction
    return plot_restatement(
        restatement.days,
        restatement.reported,
        restatement.restated,
        restatement.changes,
        trade_date=transaction.trade_date,
        corrected_on=version.recorded_at.date(),
        description=(
            f"{transaction.transaction_id}: {transaction.quantity:,} {transaction.instrument_id} booked at "
            f"{restatement.original.price} instead of {transaction.price}"
        ),
    )


def lot_map_chart() -> Figure:
    book = _demo().book
    open_lots = [lot for lots in book.open_lots.values() for lot in lots]
    return plot_tax_lot_map(book.realised, open_lots, DEMO_END)


def wash_sale_chart() -> Figure:
    demo = _demo()
    book = demo.book
    biggest = max(book.wash_sales, key=lambda match: match.disallowed)
    matches = [match for match in book.wash_sales if match.disposal_id == biggest.disposal_id]
    after = max(match.replacement_date for match in matches) + timedelta(days=1)
    series = demo.prices.series(biggest.instrument_id)
    assert series is not None
    return plot_wash_sale(matches, book.realised, book.lots_on(after, biggest.instrument_id), series)


def lot_selection_chart() -> Figure:
    lots = illustrative_lots()
    quantity, price = Decimal(200), Decimal(480)
    choices = compare_lot_methods(lots, quantity, price, Decimal(1), ILLUSTRATION_DATE)
    return plot_lot_selection(
        lots, choices, instrument_id="US-MSFT", quantity=quantity, price=price, as_of=ILLUSTRATION_DATE
    )


def us_vs_uk_chart() -> Figure:
    demo = _demo()
    book, uk = demo.book, demo.uk_matching
    pool_instrument = Counter(item.instrument_id for item in uk.disposals).most_common(1)[0][0]
    currency = demo.instruments[pool_instrument].currency.code
    gbp_per_usd = {item.day: float(demo.fx.rate("USD", "GBP", item.day)) for item in uk.disposals}
    open_lots = [lot for lots in book.open_lots.values() for lot in lots]
    costs = {
        (lot.open_date, float(lot.cost_per_unit * demo.fx.rate(currency, "GBP", lot.open_date)))
        for lot in open_lots
        if lot.instrument_id == pool_instrument
    }
    costs |= {
        (item.open_date, float(item.cost / item.quantity * demo.fx.rate(currency, "GBP", item.open_date)))
        for item in book.realised
        if item.instrument_id == pool_instrument
    }
    return plot_us_vs_uk(
        demo.us_tax_years,
        uk.by_tax_year(),
        book.realised,
        uk,
        gbp_per_usd,
        pool_instrument=pool_instrument,
        lot_costs=sorted(costs),
    )


def realised_chart() -> Figure:
    demo = _demo()
    return plot_realised_gains(demo.us_tax_years, demo.book.realised)


def horizon_chart() -> Figure:
    demo = _demo()
    book = demo.book
    open_lots = [lot for lots in book.open_lots.values() for lot in lots]
    prices = {key: float(demo.prices.price(key, DEMO_END) or 0) for key in book.open_lots}
    rates = {currency: float(demo.fx.rate(currency, "USD", DEMO_END)) for currency in ("USD", "EUR", "GBP", "CHF")}
    scales = {key: float(instrument_price_scale(demo.instruments[key])) for key in book.open_lots}
    return plot_unrealised_horizon(open_lots, prices, rates, scales, DEMO_END)


def reconciliation_chart() -> Figure:
    register, score = _demo().reconciliation
    return plot_reconciliation_dashboard(register, score)


def statement_chart() -> Figure:
    demo = _demo()
    register, _ = demo.reconciliation
    report = max(register.reports, key=lambda item: (len({part.cause for part in item.breaks}), len(item.breaks)))
    currencies = demo.book.snapshot_on(report.as_of).currencies
    lines = statement_lines(report, sorted(demo.book.settled_positions(report.as_of)), list(currencies))
    return plot_reconciliation_statement(report, lines)


def accounting_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "valuation-waterfall.png",
            "Where the value went",
            "A year of NAV bridged exactly: flows, price, currency, income and costs, with each holding's share.",
            waterfall_chart,
            "accounting",
        ),
        GalleryItem(
            "nav-history.png",
            "Two and a half years of the book",
            "NAV by holding, shaded by currency, with the cumulative investment result decomposed beneath it.",
            nav_chart,
            "accounting",
        ),
        GalleryItem(
            "fx-separation.png",
            "Price and currency, separated",
            "Each holding's unrealised result split at its own purchase rates, and the currencies behind it.",
            fx_chart,
            "accounting",
        ),
        GalleryItem(
            "cash-ladder.png",
            "Cash by settlement date",
            "Settled against projected cash in four currencies while the account was funded, and what settles next.",
            cash_chart,
            "accounting",
        ),
        GalleryItem(
            "settlement-cycles.png",
            "The day the settlement cycle changed",
            "Every trade's settlement lag by market, before and after US equities moved to T+1.",
            settlement_chart,
            "accounting",
        ),
        GalleryItem(
            "income-calendar.png",
            "Income: earned, paid, taxed",
            "Dividends and coupons from ex-date to pay date, with withholding split into reclaimable and lost.",
            income_chart,
            "accounting",
        ),
        GalleryItem(
            "trial-balance.png",
            "The book balances",
            "The trial balance as a chart, and net assets = capital + net income at every month-end.",
            trial_balance_chart,
            "accounting",
        ),
        GalleryItem(
            "restatement.png",
            "A correction is a replay",
            "NAV as reported each evening against NAV as now known, around a trade booked at the wrong price.",
            restatement_chart,
            "accounting",
        ),
        GalleryItem(
            "tax-lot-map.png",
            "Every tax lot the account has held",
            "Lots from acquisition to disposal, with holding periods, tacking and wash sale adjustments.",
            lot_map_chart,
            "tax",
        ),
        GalleryItem(
            "wash-sale.png",
            "A wash sale",
            "A harvested loss bought back inside 30 days: the loss moves into the replacement lots' tax basis.",
            wash_sale_chart,
            "tax",
        ),
        GalleryItem(
            "lot-selection.png",
            "Which lots you sell is worth money",
            "One sale under FIFO, LIFO, highest cost and minimum tax: the gain of each term and the tax on it.",
            lot_selection_chart,
            "tax",
        ),
        GalleryItem(
            "us-vs-uk.png",
            "One book, two tax codes",
            "The same disposals under US lot rules and UK same-day, 30-day and section 104 matching.",
            us_vs_uk_chart,
            "tax",
        ),
        GalleryItem(
            "realised-gains.png",
            "Realised gains by tax year",
            "Netted the way Schedule D nets them, with losses carried forward and the wash sale deferral shown.",
            realised_chart,
            "tax",
        ),
        GalleryItem(
            "unrealised-horizon.png",
            "The long-term horizon",
            "Open lots by days held against unrealised gain, and each short-term lot's road to long-term.",
            horizon_chart,
            "tax",
        ),
        GalleryItem(
            "reconciliation-dashboard.png",
            "Reconciliation against the custodian",
            "Breaks by day and cause, recall against planted breaks, and how long each stayed open.",
            reconciliation_chart,
            "reconciliation",
        ),
        GalleryItem(
            "reconciliation-statement.png",
            "One morning, line by line",
            "The book against the custodian's statement, with every difference and the reason given for it.",
            statement_chart,
            "reconciliation",
        ),
    )
