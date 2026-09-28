"""The trading-day run: check the day's orders, fills, allocations and costs, and store them - or nothing.

Before anything is written the run checks its own controls:

* **every order is consistent** - quantities, states and its audit trail (the
  order state machine's own invariants), and a parent's fills are its
  children's fills;
* **every fill is at a price the market traded** - within the day's range of
  prices, spread and impact included;
* **every block is allocated in full**, at one price, no account over its
  request;
* **every shortfall adds up** - the components equal the shortfall computed
  directly from the fills.

A failed control writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..core.exceptions import ValidationError
from ..execution.allocation import check_allocations
from ..execution.tca import check_decomposition
from ..persistence.repositories import UnitOfWork
from .demo_execution import DemoExecution

PRICE_TOLERANCE = 0.05  # a fill may be at most 5% away from the day's range of mid-prices


@dataclass
class ExecutionRunResult:
    trade_date: date
    blocks: int
    filled_value: float
    shortfall_bps: float
    controllable_bps: float
    stored: dict[str, int] = field(default_factory=dict)

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("trade date", f"{self.trade_date}"),
            ("blocks worked", f"{self.blocks}"),
            ("value traded", f"{self.filled_value:,.0f}"),
            ("implementation shortfall", f"{self.shortfall_bps:+.1f} bp"),
            ("of which the desk controls", f"{self.controllable_bps:+.1f} bp"),
        ]
        rows += [(f"{table} rows stored", f"{count:,}") for table, count in self.stored.items()]
        return rows


def check_controls(demo: DemoExecution) -> None:
    for result, cost in zip(demo.executions, demo.costs, strict=True):
        parent = result.parent
        parent.check()
        child_fills = sum(child.cumulative for child in result.children)
        if abs(child_fills - parent.cumulative) > 1e-6:
            raise ValidationError(
                f"{parent.order_id}: children filled {child_fills}, the parent {parent.cumulative}; nothing written"
            )
        for child in result.children:
            child.check()
        market = result.market
        low = float(min(market.unimpacted.min(), (market.unimpacted * (1 + market.shift)).min()))
        high = float(max(market.unimpacted.max(), (market.unimpacted * (1 + market.shift)).max()))
        for record in result.records:
            if not low * (1 - PRICE_TOLERANCE) <= record.price <= high * (1 + PRICE_TOLERANCE):
                raise ValidationError(
                    f"{parent.order_id}: a fill at {record.price} is outside the day's prices; nothing written"
                )
        check_decomposition(cost, records_value=sum(record.quantity * record.price for record in result.records))
    for block, allocations in zip(demo.blocks, demo.allocations, strict=True):
        check_allocations(block, allocations)


def run_demo_execution(demo: DemoExecution, unit_of_work: UnitOfWork | None = None) -> ExecutionRunResult:
    check_controls(demo)
    totals = demo.totals()
    controllable = totals["spread"] + totals["temporary impact"] + totals["permanent impact"] + totals["fees"]
    outcome = ExecutionRunResult(
        trade_date=demo.trade_date,
        blocks=len(demo.blocks),
        filled_value=sum(result.parent.notional for result in demo.executions),
        shortfall_bps=totals["shortfall"] / totals["paper value"] * 1e4,
        controllable_bps=controllable / totals["paper value"] * 1e4,
    )
    if unit_of_work is None:
        return outcome
    outcome.stored = unit_of_work.execution.save_day(demo.trade_date, demo.executions, demo.costs, demo.allocations)
    unit_of_work.flush()
    return outcome
