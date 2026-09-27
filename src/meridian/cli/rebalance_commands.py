"""``meridian rebalance`` - the tax-aware optimiser, from the command line.

``propose`` solves today's rebalance and prints the orders; ``lots`` shows
which lots each sale relieves and what the broker's default rules would have
cost instead; ``frontier`` prints the tracking-error / tax trade-off; ``compare``
rebalances the account three ways; ``backtest`` runs the tax-alpha simulation;
``run --persist`` checks the controls and stores the proposal; ``stored`` reads
it back.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import replace
from typing import TYPE_CHECKING, Annotated

import typer

from ..config import get_settings
from ..core.exceptions import ValidationError
from ..persistence import Database, UnitOfWork
from ._common import console, fail, render_rows, success, table

if TYPE_CHECKING:  # the optimiser (and cvxpy) loads only when a rebalance command runs
    from ..services.demo_optimisation import DemoOptimisation

app = typer.Typer(
    help="Tax-aware rebalancing: the proposal, its lots, the tracking-error / tax frontier and tax alpha.",
    no_args_is_help=True,
)

PORTFOLIO = "PF-GLOBAL-EQ"
BACKTEST_MONTHS = 36
BACKTEST_SEED = 7


def _demo() -> DemoOptimisation:
    from ..services.demo_optimisation import build_demo_optimisation

    logging.getLogger().setLevel(logging.WARNING)
    warnings.filterwarnings("ignore", module="cvxpy")
    return build_demo_optimisation()


def _money(value: float) -> str:
    return f"{value:,.0f}"


@app.command("propose")
def propose(
    risk_aversion: Annotated[
        float | None,
        typer.Option("--risk-aversion", help="Weight on tracking error squared; the house view by default"),
    ] = None,
    no_harvest: Annotated[bool, typer.Option("--no-harvest", help="Let losses sit")] = False,
) -> None:
    """Solve today's rebalance and print its orders, rounded to whole lots."""
    from ..optimisation.rounding import round_trades
    from ..services.demo_optimisation import HOUSE

    demo = _demo()
    settings = HOUSE
    if risk_aversion is not None:
        if risk_aversion < 0:
            fail("the risk aversion must not be negative")
        settings = replace(settings, risk_aversion=risk_aversion)
    if no_harvest:
        settings = replace(settings, harvest=False)
    try:
        result = demo.house.solve(settings) if settings != HOUSE else demo.proposal
    except ValidationError as error:
        fail(str(error))
    rounded = round_trades(demo.house, result, settings) if settings != HOUSE else demo.tickets
    summary = [
        ("tracking error", f"{result.tracking_error_before:.2%} to {rounded.tracking_error_after:.2%}"),
        ("active share", f"{result.active_share_before:.1%} to {rounded.active_share_after:.1%}"),
        ("tax realised", _money(rounded.tax)),
        ("gains realised", _money(result.realised_gains)),
        ("losses realised", _money(result.realised_losses)),
        ("trading cost", f"{rounded.cost * 1e4:.1f} bp"),
        ("turnover, two-way", f"{result.turnover:.0%}"),
        ("solver", f"{result.solver}, {result.rounds} rounds, {result.status}"),
    ]
    console.print(render_rows(table(f"Rebalance on {result.as_of}", ["Measure", "Value"], numeric=[1]), summary))
    rows = [
        (ticket.asset_id, ticket.side, f"{ticket.units:,.0f}", _money(ticket.value), len(ticket.lots) or "")
        for ticket in sorted(rounded.tickets, key=lambda item: (item.side != "sell", -item.value))
    ]
    console.print(
        render_rows(
            table(
                "Orders",
                ["Instrument", "Side", "Quantity", "Value", "Lots"],
                numeric=[2, 3, 4],
                caption=f"Rounded to whole lots, minimum ticket {rounded.min_ticket:,.0f}; dropped: "
                f"{', '.join(rounded.dropped) or 'none'}.",
            ),
            rows,
        )
    )
    for note in result.repairs:
        console.print(f"[muted]{note}[/muted]")


@app.command("lots")
def lots() -> None:
    """The lots the proposal sells, and the tax the broker's default rules would realise on the same trades."""
    demo = _demo()
    rows = [
        (
            sale.lot.asset_id,
            sale.lot.lot_id,
            sale.lot.opened.isoformat(),
            "long" if sale.long_term else "short",
            f"{sale.units:,.0f}",
            _money(sale.gain),
            _money(sale.tax) + (" (wash sale)" if sale.wash_sale else ""),
        )
        for sale in sorted(demo.proposal.sales, key=lambda item: (item.lot.asset_id, item.lot.lot_id))
    ]
    console.print(
        render_rows(
            table("Lots relieved", ["Instrument", "Lot", "Opened", "Term", "Units", "Gain", "Tax"], numeric=[4, 5, 6]),
            rows,
        )
    )
    relief = [(method, _money(sum(sale.tax for sale in sales))) for method, sales in demo.relief.items()]
    console.print(render_rows(table("The same trades, lots relieved four ways", ["Rule", "Tax"], numeric=[1]), relief))


@app.command("frontier")
def frontier() -> None:
    """The tracking-error / tax frontier: the least tracking error each tax bill buys."""
    demo = _demo()
    rows = [
        (
            index + 1,
            _money(point.tax),
            f"{point.tracking_error:.2%}",
            _money(point.cost),
            f"{point.turnover:.0%}",
            "" if point.risk_aversion is None else f"{point.risk_aversion:g}",
        )
        for index, point in enumerate(demo.frontier.points)
    ]
    console.print(
        render_rows(
            table(
                "The efficient frontier",
                ["Point", "Tax", "Tracking error", "Cost", "Turnover", "Risk aversion"],
                numeric=[1, 2, 3, 4, 5],
                caption=f"Tracking error today {demo.frontier.tracking_error_before:.2%}; "
                f"{len(demo.frontier.dominated)} dominated solutions not shown.",
            ),
            rows,
        )
    )


@app.command("compare")
def compare() -> None:
    """Today's account rebalanced by three managers."""
    demo = _demo()
    rows = [
        (
            name,
            f"{result.tracking_error_after:.2%}",
            _money(result.tax),
            _money(result.realised_losses),
            f"{result.cost * 1e4:.1f} bp",
            f"{result.turnover:.0%}",
        )
        for name, result in demo.alternatives.items()
    ]
    console.print(
        render_rows(
            table(
                "Three managers", ["Manager", "TE after", "Tax", "Losses", "Cost", "Turnover"], numeric=[1, 2, 3, 4, 5]
            ),
            rows,
        )
    )


@app.command("backtest")
def backtest(
    paths: Annotated[int, typer.Option("--paths", min=1, help="Simulated paths")] = 4,
    months: Annotated[int, typer.Option("--months", min=2, help="Months per path")] = BACKTEST_MONTHS,
    seed: Annotated[int, typer.Option("--seed")] = BACKTEST_SEED,
) -> None:
    """Tax alpha: four managers through the same simulated markets."""
    from ..optimisation.backtest import TaxAlphaBacktest
    from ..services.demo_optimisation import BACKTEST

    demo = _demo()
    config = replace(BACKTEST, months=months, seed=seed)
    with console.status(f"simulating {paths} paths of {months} months"):
        summary = TaxAlphaBacktest(demo.universe_risk(), config).run_paths(paths)
    rows = [
        (
            row["strategy"],
            f"{float(row['pre_tax']):.2%}",
            f"{float(row['after_tax']):.2%}",
            f"{float(row['tax_alpha']):+.2%}",
            f"{float(row['tax_alpha_held']):+.2%}",
            f"{float(row['tracking_error']):.2%}",
            f"{float(row['turnover']):.0%}",
        )
        for row in summary.table()
    ]
    console.print(
        render_rows(
            table(
                f"Tax alpha over {paths} paths of {months} months",
                ["Manager", "Pre-tax", "After tax", "Tax alpha", "As held", "TE", "Turnover"],
                numeric=[1, 2, 3, 4, 5, 6],
                caption="Annualised; tax alpha against the tax-blind manager on liquidation value.",
            ),
            rows,
        )
    )


@app.command("run")
def run(
    persist: Annotated[bool, typer.Option("--persist/--dry-run", help="Write the proposal and its orders")] = False,
    with_backtest: Annotated[
        bool, typer.Option("--with-backtest", help="Also run and store the tax-alpha backtest")
    ] = False,
) -> None:
    """Check the controls and, with --persist, store the proposal, its orders, lots and frontier."""
    from ..services.optimisation_run import run_demo_optimisation

    demo = _demo()
    try:
        if not persist:
            result = run_demo_optimisation(demo, with_backtest=with_backtest)
        else:
            database = Database(get_settings()).create_all()
            try:
                with database.session() as session:
                    unit_of_work = UnitOfWork(session)
                    result = run_demo_optimisation(demo, unit_of_work, with_backtest=with_backtest)
                    unit_of_work.commit()
            finally:
                database.dispose()
    except ValidationError as error:
        fail(str(error))
    console.print(render_rows(table("Rebalance run", ["Step", "Result"]), result.summary_rows()))
    if persist:
        success("proposal, orders, lot sales and frontier stored")


@app.command("stored")
def stored() -> None:
    """Read the latest proposal back from the database (after run --persist)."""
    database = Database(get_settings())
    try:
        with database.session() as session:
            repository = UnitOfWork(session).optimisation
            proposals = repository.proposals(PORTFOLIO)
            if not proposals:
                fail("nothing stored yet - run `meridian rebalance run --persist` first")
            latest = proposals[-1]
            orders = repository.orders(latest.proposal_id)
            by_term = repository.tax_by_term(latest.proposal_id)
    finally:
        database.dispose()
    rows = [
        ("proposal", latest.proposal_id),
        ("tracking error", f"{latest.tracking_error_before:.2%} to {latest.tracking_error_after:.2%}"),
        ("orders", f"{len(orders)}"),
        ("compliance", latest.compliance_decision),
    ]
    rows += [(f"{term}: gain, tax", f"{_money(gain)}, {_money(tax)}") for term, (gain, tax) in sorted(by_term.items())]
    console.print(render_rows(table("Read back from the database", ["Measure", "Value"]), rows))
