"""``meridian book`` - the book of record from the command line.

Every command reads the demonstration book, which is rebuilt deterministically
from the demonstration market, so an operator sees the numbers the
documentation shows. ``run --persist`` writes the journal, the lots, the
realised gains, the valuations and the reconciliation breaks into the
configured database, after which ``trial-balance --from-db`` reads the trial
balance back out of SQL.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from ..accounting.chart_of_accounts import Accounts
from ..accounting.journal import JournalEntry
from ..accounting.lots import Term
from ..accounting.tax import compare_lot_methods, form_8949
from ..config import get_settings
from ..core.enums import TransactionType
from ..persistence import Database, UnitOfWork
from ..services.accounting_run import run_demo_accounting
from ..services.demo_accounting import PORTFOLIO_ID, DemoAccounting, build_demo_accounting
from ..services.demo_market import DEMO_END
from ..viz.style import save_figure
from ._common import console, fail, render_rows, success, table

app = typer.Typer(
    help="The book of record: positions, lots, cash, gains, NAV, the value bridge and reconciliation.",
    no_args_is_help=True,
)


def _demo() -> DemoAccounting:
    logging.getLogger().setLevel(logging.WARNING)
    return build_demo_accounting()


def _day(text: str | None, default: date = DEMO_END) -> date:
    if text is None:
        return default
    try:
        return date.fromisoformat(text)
    except ValueError:
        fail(f"{text!r} is not an ISO date (YYYY-MM-DD)")


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


@app.command("run")
def run(
    persist: Annotated[bool, typer.Option("--persist/--dry-run", help="Write the book to the database")] = False,
) -> None:
    """Replay, check, value, reconcile - and persist if asked. Nothing is written if a control fails."""
    demo = _demo()
    if not persist:
        result = run_demo_accounting(demo)
    else:
        database = Database(get_settings()).create_all()
        try:
            with database.session() as session:
                unit_of_work = UnitOfWork(session)
                result = run_demo_accounting(demo, unit_of_work)
                unit_of_work.commit()
        finally:
            database.dispose()
    console.print(render_rows(table("End-of-day accounting run", ["Step", "Result"]), result.summary_rows()))
    if not result.passed:
        fail("the book failed its controls")


@app.command("positions")
def positions(
    as_of: Annotated[str | None, typer.Option("--as-of", help="ISO date")] = None,
) -> None:
    """Holdings at market on a date: quantity, price, value in local and base currency, and unrealised result."""
    demo = _demo()
    valuation = demo.valuator.value(_day(as_of))
    rows = [
        (
            item.instrument_id,
            item.currency,
            f"{item.quantity:,.0f}",
            f"{item.price:,.4f}",
            _money(item.market_value),
            _money(item.market_value_base),
            _money(item.unrealised_price_base),
            _money(item.unrealised_fx_base),
        )
        for item in sorted(valuation.positions, key=lambda position: -position.market_value_base)
    ]
    console.print(
        render_rows(
            table(
                f"Positions on {valuation.day} - NAV {_money(valuation.nav)} USD",
                [
                    "Instrument",
                    "Ccy",
                    "Quantity",
                    "Price",
                    "Value (local)",
                    "Value (USD)",
                    "Unreal. price",
                    "Unreal. FX",
                ],
                numeric=[2, 3, 4, 5, 6, 7],
                caption="Unrealised result split per lot: price at today's rate, currency on the historical cost.",
            ),
            rows,
        )
    )


@app.command("lots")
def lots(
    instrument: Annotated[str, typer.Argument(help="Instrument id, e.g. DE-BAYN")],
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    """Open tax lots in one holding, with tacked holding periods and wash sale adjustments."""
    demo = _demo()
    day = _day(as_of)
    found = demo.book.lots_on(day, instrument)
    if not found:
        fail(f"no open lots in {instrument} on {day}")
    rows = [
        (
            lot.lot_id,
            lot.open_date.isoformat(),
            lot.holding_start.isoformat(),
            "long" if lot.is_long_term(day) else "short",
            f"{lot.quantity:,.0f}",
            f"{lot.cost_per_unit:,.4f}",
            f"{lot.open_fx_rate:.6f}",
            _money(lot.base_cost),
            _money(lot.tax_basis),
        )
        for lot in found
    ]
    console.print(
        render_rows(
            table(
                f"{instrument} lots on {day}",
                ["Lot", "Opened", "Held from", "Term", "Qty", "Cost/unit", "Open FX", "Cost (USD)", "Tax basis"],
                numeric=[4, 5, 6, 7, 8],
                caption="Tax basis includes any loss disallowed by a wash sale; book cost never does.",
            ),
            rows,
        )
    )


@app.command("cash")
def cash(
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    days: Annotated[int, typer.Option("--days", help="Days of ladder to show")] = 10,
) -> None:
    """Settled and projected cash per currency, and the settlement ladder."""
    demo = _demo()
    day = _day(as_of)
    book = demo.book
    currencies = sorted({movement.currency for movement in book.cash_movements})
    console.print(
        render_rows(
            table(f"Cash on {day}", ["Currency", "Settled", "Projected"], numeric=[1, 2]),
            [(c, _money(book.settled_cash(c, day)), _money(book.projected_cash(c, day))) for c in currencies],
        )
    )
    rows = [
        (currency, settle_day.isoformat(), _money(settling), _money(balance))
        for currency, ladder in book.cash_ladder(day, days).items()
        for settle_day, settling, balance in ladder
        if settling
    ]
    if rows:
        console.print(render_rows(table("Settling next", ["Currency", "Date", "Settling", "Balance after"]), rows))
    else:
        console.print("[muted]nothing settles in the window[/muted]")


@app.command("gains")
def gains(
    year: Annotated[int | None, typer.Option("--year", help="US tax year, or a UK year's starting year")] = None,
    regime: Annotated[str, typer.Option("--regime", help="us or uk")] = "us",
    form: Annotated[bool, typer.Option("--form-8949", help="List Form 8949 rows (US only)")] = False,
) -> None:
    """Realised gains by tax year, under US lot rules or UK share matching."""
    demo = _demo()
    if regime.lower() == "uk":
        uk_rows = [
            (
                item.tax_year,
                str(item.disposals),
                _money(item.gains),
                _money(item.losses),
                _money(item.net),
                _money(item.annual_exempt_amount),
                _money(item.taxable),
                _money(item.estimated_tax()),
            )
            for item in demo.uk_matching.by_tax_year()
            if year is None or item.tax_year.startswith(str(year))
        ]
        console.print(
            render_rows(
                table(
                    "UK capital gains (GBP): same day, 30 days, then the section 104 pool",
                    ["Tax year", "Disposals", "Gains", "Losses", "Net", "Exempt", "Taxable", "CGT"],
                    numeric=[1, 2, 3, 4, 5, 6, 7],
                ),
                uk_rows,
            )
        )
        return
    if regime.lower() != "us":
        fail("--regime must be us or uk")
    rows = [
        (
            str(item.year),
            _money(item.net_short),
            _money(item.net_long),
            _money(item.net),
            _money(item.disallowed),
            _money(sum(item.carryforward(), Decimal(0))),
            _money(item.estimated_tax()),
        )
        for item in demo.us_tax_years
        if year is None or item.year == year
    ]
    console.print(
        render_rows(
            table(
                "US capital gains (USD), netted as Schedule D nets them",
                ["Year", "Net short", "Net long", "Net", "Wash sale", "Carried forward", "Federal tax"],
                numeric=[1, 2, 3, 4, 5, 6],
            ),
            rows,
        )
    )
    if form:
        chosen = year or DEMO_END.year
        console.print(
            render_rows(
                table(
                    f"Form 8949, {chosen}",
                    ["Description", "Acquired", "Sold", "Proceeds", "Basis", "Code", "Adjustment", "Gain"],
                    numeric=[3, 4, 6, 7],
                ),
                [row.as_tuple() for row in form_8949(demo.book.realised, chosen)],
            )
        )


@app.command("lot-choice")
def lot_choice(
    instrument: Annotated[str, typer.Argument()],
    quantity: Annotated[float, typer.Argument(help="Shares to sell")],
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    """What selling some of a holding would realise, and the tax, under each lot relief method."""
    demo = _demo()
    day = _day(as_of)
    found = list(demo.book.lots_on(day, instrument))
    if not found:
        fail(f"no open lots in {instrument} on {day}")
    price = demo.prices.price(instrument, day)
    if price is None:
        fail(f"no price for {instrument} on {day}")
    rate = demo.fx.rate(demo.instruments[instrument].currency.code, "USD", day)
    held = sum((lot.quantity for lot in found), Decimal(0))
    size = min(Decimal(str(quantity)), held)
    rows = [
        (choice.method, _money(choice.short_term), _money(choice.long_term), _money(choice.tax), str(len(choice.lots)))
        for choice in compare_lot_methods(found, size, price, rate, day)
    ]
    console.print(
        render_rows(
            table(
                f"Selling {size:,} {instrument} at {price} on {day}",
                ["Method", "Short-term", "Long-term", "Federal tax", "Lots"],
                numeric=[1, 2, 3, 4],
            ),
            rows,
        )
    )


@app.command("nav")
def nav(
    start: Annotated[str | None, typer.Option("--from")] = None,
    end: Annotated[str | None, typer.Option("--to")] = None,
    every: Annotated[int, typer.Option("--every", help="Show every n-th day")] = 21,
) -> None:
    """Net asset value and its composition through time."""
    demo = _demo()
    first, last = _day(start, demo.valuation_days[0]), _day(end)
    rows = [
        (
            item.day.isoformat(),
            _money(item.nav),
            _money(item.securities),
            _money(item.accrued_interest),
            _money(item.cash_like),
            _money(item.unrealised),
        )
        for index, item in enumerate(v for v in demo.valuations if first <= v.day <= last)
        if index % max(every, 1) == 0
    ]
    console.print(
        render_rows(
            table(
                "Net asset value (USD)",
                ["Date", "NAV", "Securities", "Accrued", "Cash-like", "Unrealised"],
                numeric=[1, 2, 3, 4, 5],
            ),
            rows,
        )
    )


@app.command("bridge")
def bridge(
    start: Annotated[str, typer.Option("--from", help="Opening valuation date")] = "2024-12-31",
    end: Annotated[str, typer.Option("--to", help="Closing valuation date")] = "2025-12-31",
    chart: Annotated[Path | None, typer.Option("--chart", help="Also write the waterfall chart here")] = None,
) -> None:
    """Why NAV moved between two dates: flows, price, currency, income, costs - and the residual, which is zero."""
    from ..viz.accounting import plot_valuation_waterfall

    demo = _demo()
    try:
        result = demo.bridge(_day(start), _day(end))
    except ValueError as error:
        fail(str(error))
    rows = [(label, _money(amount)) for label, amount in result.components()]
    rows.append(("Residual", f"{result.residual:.2e}"))
    console.print(
        render_rows(table(f"Value bridge {result.start} to {result.end}", ["Component", "USD"], numeric=[1]), rows)
    )
    effects = sorted(result.by_instrument.values(), key=lambda item: item.total)
    console.print(
        render_rows(
            table("By holding", ["Instrument", "Price", "Currency", "Accrued"], numeric=[1, 2, 3]),
            [(item.instrument_id, _money(item.price), _money(item.fx), _money(item.income)) for item in effects],
        )
    )
    if chart is not None:
        success(f"wrote {save_figure(plot_valuation_waterfall(result), chart)}")


@app.command("trial-balance")
def trial_balance(
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    from_db: Annotated[bool, typer.Option("--from-db", help="Compute it in SQL (after run --persist)")] = False,
) -> None:
    """The trial balance: every account's debit or credit balance, and the check that they agree."""
    day = _day(as_of)
    if from_db:
        database = Database(get_settings())
        try:
            with database.session() as session:
                unit_of_work = UnitOfWork(session)
                if not unit_of_work.ledger.count(PORTFOLIO_ID):
                    fail("no journal in the database; run `meridian book run --persist` first")
                trial = unit_of_work.ledger.trial_balance(PORTFOLIO_ID, day)
        finally:
            database.dispose()
    else:
        trial = _demo().book.ledger.trial_balance(day)
    rows = trial.rows()
    rows.append(("", "Total", _money(trial.total_debits), _money(trial.total_credits)))
    source = "the database" if from_db else "the ledger"
    console.print(
        render_rows(
            table(
                f"Trial balance at {day}, from {source} (USD)",
                ["Code", "Account", "Debit", "Credit"],
                numeric=[2, 3],
                caption=f"Difference {trial.difference:.2e}.",
            ),
            rows,
        )
    )


@app.command("journal")
def journal(
    source: Annotated[str | None, typer.Option("--source", help="A transaction or corporate action id")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 6,
) -> None:
    """Journal entries, line by line: one transaction's, or the most recent."""
    ledger = _demo().book.ledger
    entries: list[JournalEntry] = (
        [entry for entry in ledger if entry.source_id == source] if source else list(ledger.entries)[-limit:]
    )
    if not entries:
        fail(f"no entries for {source}")
    for entry in entries:
        console.print(
            render_rows(
                table(
                    f"{entry.entry_id}  {entry.effective_date}  {entry.kind.value}: {entry.description}",
                    ["Account", "Ccy", "Debit", "Credit", "Base (USD)"],
                    numeric=[2, 3, 4],
                ),
                entry.lines(),
            )
        )


@app.command("reconcile")
def reconcile(
    as_of: Annotated[str | None, typer.Option("--as-of", help="Statement date")] = None,
    chart: Annotated[Path | None, typer.Option("--chart", help="Also write the dashboard chart here")] = None,
) -> None:
    """Compare the book with the custodian's statement and explain every break."""
    from ..viz.reconciliation import plot_reconciliation_dashboard

    demo = _demo()
    register, score = demo.reconciliation
    if as_of is not None:
        day = _day(as_of)
        report = next((item for item in register.reports if item.as_of == day), None)
        if report is None:
            first, last = register.reports[0].as_of, register.reports[-1].as_of
            fail(f"no statement on {day}; statements run from {first} to {last}")
    else:
        report = max(register.reports, key=lambda item: len(item.breaks))
    rows = [
        (
            item.kind.value,
            item.key,
            _money(item.book),
            _money(item.custodian),
            " + ".join(c.value for c in item.causes),
            item.explanation,
        )
        for item in report.breaks
    ]
    console.print(
        render_rows(
            table(
                f"Breaks on {report.as_of}: {len(report.breaks)}, {report.match_rate:.0%} of lines matched",
                ["Kind", "Key", "Book", "Custodian", "Cause", "Explanation"],
                numeric=[2, 3],
            ),
            rows,
        )
    )
    console.print(
        render_rows(
            table(
                f"Measured against planted breaks: recall {score.recall:.0%}, precision {score.precision:.0%}",
                ["Cause", "Planted", "Found"],
                numeric=[1, 2],
            ),
            [(item.cause.value, str(item.planted), str(item.detected)) for item in score.causes.values()],
        )
    )
    if chart is not None:
        success(f"wrote {save_figure(plot_reconciliation_dashboard(register, score), chart)}")


@app.command("wash-sales")
def wash_sales() -> None:
    """Every loss disallowed by the wash sale rule, and the replacement shares that absorbed it."""
    book = _demo().book
    rows = [
        (
            match.instrument_id,
            match.sale_date.isoformat(),
            match.sold_lot_id,
            match.replacement_id,
            match.replacement_date.isoformat(),
            f"{match.quantity:,.0f}",
            _money(match.disallowed),
            f"+{match.tacked_days}",
        )
        for match in book.wash_sales
    ]
    console.print(
        render_rows(
            table(
                "Wash sales (IRC 1091)",
                ["Instrument", "Sold", "Lot", "Replacement", "Bought", "Shares", "Disallowed", "Days tacked"],
                numeric=[5, 6, 7],
            ),
            rows,
        )
    )
    counts = {term: sum(1 for item in book.realised if item.term is term) for term in Term}
    transfers = sum(1 for item in book.transactions if item.transaction_type is TransactionType.TRANSFER_IN)
    console.print(
        f"[muted]{len(book.realised)} realised lots ({counts[Term.SHORT]} short-term, {counts[Term.LONG]} long-term); "
        f"{transfers} transfer in kind; investments at cost {_money(book.ledger.balance(Accounts.INVESTMENTS))}[/muted]"
    )
