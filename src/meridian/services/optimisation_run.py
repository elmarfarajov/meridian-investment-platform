"""The rebalance run: propose, round, check, and store - or store nothing.

Before anything is written the run checks its own controls:

* **value is conserved** - the weights after the trades, the cash and the
  costs add up to the account, to the dollar;
* **no wash sale** - no stock is both sold at a loss and bought;
* **the orders are tradable** - whole lots, no sale larger than the position,
  cash after the orders within its band;
* **the compliance engine does not block it** - the proposal as one basket;
* **the frontier is a frontier** - more tax never buys more tracking error,
  and the proposal is not beaten by it.

A failed control writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.exceptions import ValidationError
from ..persistence.repositories import UnitOfWork, seed_reference_data
from ..seed import demo_book
from .demo_optimisation import HOUSE, DemoOptimisation

CONSERVATION_TOLERANCE = 1e-9
FRONTIER_TOLERANCE = 1e-5


@dataclass
class OptimisationRunResult:
    portfolio_id: str
    proposal_id: str
    tracking_error: tuple[float, float]
    tax: float
    harvested: float
    orders: int
    decision: str
    backtest_id: str | None = None
    stored: dict[str, int] = field(default_factory=dict)

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("portfolio", self.portfolio_id),
            ("proposal", self.proposal_id),
            ("tracking error", f"{self.tracking_error[0]:.2%} to {self.tracking_error[1]:.2%}"),
            ("tax realised", f"{self.tax:,.0f}"),
            ("losses harvested", f"{self.harvested:,.0f}"),
            ("orders", f"{self.orders}"),
            ("compliance engine", self.decision),
        ]
        if self.backtest_id is not None:
            rows.append(("backtest", self.backtest_id))
        rows += [(f"{table} rows stored", f"{count:,}") for table, count in self.stored.items()]
        return rows


def check_controls(demo: DemoOptimisation, *, frontier: bool = True) -> None:
    result, rounded, house = demo.proposal, demo.tickets, demo.house
    total = sum(result.after.values()) + result.cash_after + result.cost
    if abs(total - 1.0) > CONSERVATION_TOLERANCE:
        raise ValidationError(f"the proposal does not conserve value ({total:.12f} of the account); nothing written")
    losers = {sale.lot.asset_id for sale in result.sales if sale.gain < 0 and not sale.wash_sale}
    if losers & set(result.buys):
        raise ValidationError(
            f"wash sale: {sorted(losers & set(result.buys))} sold at a loss and bought; nothing written"
        )
    for ticket in rounded.tickets:
        asset = house.assets[house.asset_index[ticket.asset_id]]
        lots = ticket.units / asset.lot_size
        if abs(lots - round(lots)) > 1e-9:
            raise ValidationError(f"{ticket.asset_id}: {ticket.units} is not a whole number of lots; nothing written")
        if ticket.side == "sell" and ticket.units > asset.quantity + 1e-9:
            raise ValidationError(f"{ticket.asset_id}: the order sells more than is held; nothing written")
    low, high = HOUSE.cash_band
    if not low - 1e-6 <= rounded.cash_after <= high + 1e-6:
        raise ValidationError(f"cash after the orders {rounded.cash_after:.2%} is outside its band; nothing written")
    if demo.compliance_check.decision == "blocked":
        raise ValidationError("the compliance engine blocks the proposal; nothing written")
    if frontier:
        errors = demo.frontier.tracking_errors()
        if np.any(np.diff(errors) > FRONTIER_TOLERANCE):
            raise ValidationError("the frontier is not monotone; nothing written")
        if demo.frontier.excess(result) < -FRONTIER_TOLERANCE:
            raise ValidationError("the frontier is beaten by the proposal itself; nothing written")


def run_demo_optimisation(
    demo: DemoOptimisation,
    unit_of_work: UnitOfWork | None = None,
    *,
    with_frontier: bool = True,
    with_backtest: bool = False,
) -> OptimisationRunResult:
    check_controls(demo, frontier=with_frontier)
    result, rounded = demo.proposal, demo.tickets
    portfolio = demo.accounting.portfolio
    proposal_id = f"RB-{portfolio.portfolio_id}-{result.as_of.isoformat()}"
    harvested = -sum(sale.gain for sale in rounded.sales if sale.gain < 0 and not sale.wash_sale)
    outcome = OptimisationRunResult(
        portfolio_id=portfolio.portfolio_id,
        proposal_id=proposal_id,
        tracking_error=(result.tracking_error_before, rounded.tracking_error_after),
        tax=rounded.tax,
        harvested=harvested,
        orders=len(rounded.tickets),
        decision=demo.compliance_check.decision,
        backtest_id=f"TAX-ALPHA-{result.as_of.isoformat()}" if with_backtest else None,
    )
    if unit_of_work is None:
        return outcome
    if unit_of_work.portfolios.find(portfolio.portfolio_id) is None:
        reference = demo_book()
        seed_reference_data(
            unit_of_work,
            instruments=reference.instruments,
            benchmarks=reference.benchmarks,
            clients=reference.clients,
            households=reference.households,
            accounts=reference.accounts,
            portfolios=reference.portfolios,
        )
        unit_of_work.portfolios.add(portfolio)
        unit_of_work.flush()
    repository = unit_of_work.optimisation
    outcome.stored = repository.save_proposal(
        proposal_id,
        portfolio.portfolio_id,
        HOUSE,
        result,
        rounded,
        outcome.decision,
        demo.frontier if with_frontier else None,
    )
    if with_backtest and outcome.backtest_id is not None:
        outcome.stored["tax-alpha result"] = repository.save_backtest(outcome.backtest_id, demo.backtest)
    unit_of_work.flush()
    return outcome
