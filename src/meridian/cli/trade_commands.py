"""``meridian trade`` - the trading desk: the day's blocks, how they were worked, what they cost, who got what.

``blotter`` lists the day's block orders as worked; ``order`` follows one block
through its child orders and audit trail; ``costs`` decomposes the
implementation shortfall; ``algos`` re-runs the day with every algorithm;
``calibrate`` fits the impact model to the desk's history; ``allocations``
shows an account's share of the blocks; ``run --persist`` checks the controls
and stores the day; ``stored`` reads it back. ``meridian report client`` writes
the client report.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from ..config import get_settings
from ..core.exceptions import ValidationError
from ..persistence import Database, UnitOfWork
from ._common import console, fail, render_rows, success, table

if TYPE_CHECKING:  # the simulator (and the optimiser behind it) load only when a command runs
    from ..services.demo_execution import DemoExecution

app = typer.Typer(
    help="The trading desk: block orders, algorithms, allocation and transaction cost analysis.",
    no_args_is_help=True,
)
report_app = typer.Typer(help="Client reporting: the quarterly report as a PDF.", no_args_is_help=True)

COMPONENTS = ("delay", "spread", "temporary impact", "permanent impact", "timing", "opportunity", "fees")


def _demo() -> DemoExecution:
    from ..services.demo_execution import build_demo_execution

    logging.getLogger().setLevel(logging.WARNING)
    warnings.filterwarnings("ignore", module="cvxpy")
    return build_demo_execution()


@app.command("blotter")
def blotter() -> None:
    """Every block order of the day: algorithm, fill, prices and shortfall."""
    demo = _demo()
    rows = []
    for result, cost in zip(demo.executions, demo.costs, strict=True):
        parent = result.parent
        rows.append(
            (
                parent.order_id,
                parent.instrument_id,
                parent.side.value,
                f"{parent.quantity:,.0f}",
                f"{cost.size_adv:.2%}",
                result.params.name.upper(),
                f"{parent.fill_rate:.0%}",
                "-" if cost.average is None else f"{cost.average:,.4f}",
                f"{cost.shortfall_bps:+.1f}",
            )
        )
    console.print(
        render_rows(
            table(
                f"Blotter, {demo.trade_date}",
                ["Block", "Instrument", "Side", "Shares", "% ADV", "Algo", "Filled", "Average", "Shortfall bp"],
                numeric=[3, 4, 6, 7, 8],
                caption=f"{len(demo.account_orders)} account orders in {len(demo.blocks)} blocks; "
                f"to the fixed-income desk by RFQ: {', '.join(demo.rfq_orders) or 'none'}.",
            ),
            rows,
        )
    )


@app.command("order")
def order(instrument: Annotated[str, typer.Argument(help="The instrument of a block, e.g. DE-BAYN")]) -> None:
    """One block: its child orders and its audit trail."""
    demo = _demo()
    matches = [result for result in demo.executions if result.parent.instrument_id == instrument]
    if not matches:
        fail(f"no block for {instrument}; see `meridian trade blotter`")
    result = matches[0]
    rows = [
        (
            child.order_id,
            f"{child.quantity:,.0f}",
            f"{child.cumulative:,.0f}",
            child.status.value,
            "-" if child.average_price is None else f"{child.average_price:,.4f}",
        )
        for child in result.children
    ]
    console.print(
        render_rows(
            table(
                f"{result.parent.order_id}: child orders",
                ["Child", "Quantity", "Filled", "Status", "Average"],
                numeric=[1, 2, 4],
            ),
            rows,
        )
    )
    events = [
        (event.minute, event.status.value, event.note)
        for event in result.parent.events
        if "at" not in event.note or event.status.value != "partially filled"
    ]
    console.print(render_rows(table("Audit trail (fills summarised)", ["Minute", "Status", "Note"]), events))


@app.command("costs")
def costs() -> None:
    """The day's implementation shortfall, component by component."""
    demo = _demo()
    totals = demo.totals()
    paper = totals["paper value"]
    rows = [(name, f"{totals[name]:,.0f}", f"{totals[name] / paper * 1e4:+.2f}") for name in COMPONENTS]
    rows.append(("shortfall", f"{totals['shortfall']:,.0f}", f"{totals['shortfall'] / paper * 1e4:+.2f}"))
    console.print(
        render_rows(
            table(
                "Implementation shortfall",
                ["Component", "Base currency", "bp"],
                numeric=[1, 2],
                caption=f"Against the decision prices, on {paper:,.0f} of orders. Positive is a cost.",
            ),
            rows,
        )
    )


@app.command("algos")
def algos() -> None:
    """The same blocks re-run with every algorithm on the same simulated day."""
    demo = _demo()
    rows = []
    for name, items in demo.comparison.items():
        paper = sum(cost.paper_value for cost in items)
        controllable = sum(cost.spread + cost.temporary + cost.permanent + cost.fees for cost in items)
        filled = sum(cost.filled * cost.decision for cost in items)
        rows.append(
            (
                name.upper(),
                f"{controllable / paper * 1e4:+.1f}",
                f"{sum(c.shortfall for c in items) / paper * 1e4:+.1f}",
                f"{filled / paper:.0%}",
            )
        )
    console.print(
        render_rows(
            table(
                "Algorithms compared",
                ["Algorithm", "Controllable bp", "Shortfall bp", "Value filled"],
                numeric=[1, 2, 3],
            ),
            rows,
        )
    )


@app.command("calibrate")
def calibrate_command() -> None:
    """Fit the square-root impact coefficient to the desk's history, against the true one."""
    from ..services.demo_execution import IMPACT

    demo = _demo()
    rows = []
    for _name, fit in demo.calibration.items():
        low, high = fit.interval()
        rows.append(
            (
                fit.source,
                f"{fit.coefficient:.3f}",
                f"{low:.3f} to {high:.3f}",
                f"{fit.r_squared:.3f}",
                f"{fit.observations}",
            )
        )
    console.print(
        render_rows(
            table(
                "Impact calibration",
                ["From", "Coefficient", "95% interval", "R squared", "Orders"],
                numeric=[1, 3, 4],
                caption=f"The coefficient that generated the data: {IMPACT.temporary:.3f}.",
            ),
            rows,
        )
    )


@app.command("allocations")
def allocations(portfolio: Annotated[str, typer.Option("--portfolio")] = "PF-GLOBAL-EQ") -> None:
    """An account's share of the day's blocks: requested, allocated, price and cost."""
    demo = _demo()
    items = demo.account_costs.get(portfolio)
    if items is None:
        fail(f"{portfolio} has no orders today; accounts: {', '.join(demo.account_costs)}")
    rows = [
        (
            item.allocation.instrument_id,
            item.allocation.side.value,
            f"{item.allocation.requested:,.0f}",
            f"{item.allocation.quantity:,.0f}",
            f"{item.allocation.price:,.4f}" if item.allocation.quantity else "-",
            f"{item.shortfall_bps:+.1f}",
        )
        for item in items
    ]
    console.print(
        render_rows(
            table(
                f"Allocations to {portfolio}",
                ["Instrument", "Side", "Requested", "Allocated", "Price", "Cost bp"],
                numeric=[2, 3, 4, 5],
            ),
            rows,
        )
    )


@app.command("run")
def run(
    persist: Annotated[
        bool, typer.Option("--persist/--dry-run", help="Write the day's orders, fills, allocations and costs")
    ] = False,
) -> None:
    """Check the controls and, with --persist, store the day."""
    from ..services.execution_run import run_demo_execution

    demo = _demo()
    try:
        if not persist:
            result = run_demo_execution(demo)
        else:
            database = Database(get_settings()).create_all()
            try:
                with database.session() as session:
                    unit_of_work = UnitOfWork(session)
                    result = run_demo_execution(demo, unit_of_work)
                    unit_of_work.commit()
            finally:
                database.dispose()
    except ValidationError as error:
        fail(str(error))
    console.print(render_rows(table("Trading-day run", ["Step", "Result"]), result.summary_rows()))
    if persist:
        success("orders, audit trail, fills, allocations and transaction costs stored")


@app.command("stored")
def stored() -> None:
    """Read the stored trading day back and recount it in SQL."""
    from datetime import date

    database = Database(get_settings())
    try:
        with database.session() as session:
            repository = UnitOfWork(session).execution
            day = date(2026, 9, 21)
            blocks = repository.blocks(day)
            if not blocks:
                fail("nothing stored yet - run `meridian trade run --persist` first")
            filled = repository.filled_by_block(day)
            by_algorithm = repository.cost_by_algorithm(day)
    finally:
        database.dispose()
    rows = [("blocks", f"{len(blocks)}"), ("shares filled (from the child fills)", f"{sum(filled.values()):,.0f}")]
    rows += [
        (f"shortfall, {name.upper()}", f"{total / value * 1e4:+.1f} bp on {value:,.0f}")
        for name, (total, value) in sorted(by_algorithm.items())
    ]
    console.print(render_rows(table("Read back from the database", ["Measure", "Value"]), rows))


@report_app.command("client")
def client_report(
    out: Annotated[Path, typer.Option("--out", help="Where to write the PDF")] = Path("client-report.pdf"),
) -> None:
    """Write the quarterly client report: summary, holdings, performance, risk, compliance, rebalance, trading."""
    from ..reporting.client_pack import ClientPack

    demo = _demo()
    try:
        with console.status("assembling nine pages from every module"):
            path = ClientPack(demo).write(out)
    except ValidationError as error:
        fail(str(error))
    success(f"client report written to {path} ({path.stat().st_size / 1024:,.0f} KB)")
