"""Execution in the database: orders with their audit trail, fills, allocations, and what trading cost.

A best-execution review asks, for any order: who asked for it, when the desk
had it, how it was worked, at what prices it filled, how the fills were shared
among the accounts, and what it cost against the decision. Every one of those
answers is a row here. Storing a trading day again replaces that day whole.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from .base import utcnow
from .models import ExecutionEventRow, ExecutionFillRow, ExecutionOrderRow, OrderAllocationRow, TransactionCostRow

if TYPE_CHECKING:  # the simulator is not loaded just to open a session
    from ..execution.algorithms import ExecutionResult
    from ..execution.allocation import Allocation
    from ..execution.orders import Order
    from ..execution.tca import OrderCost


class ExecutionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _clear(self, trade_date: date) -> None:
        orders = select(ExecutionOrderRow.order_id).where(ExecutionOrderRow.trade_date == trade_date)
        for table in (TransactionCostRow, OrderAllocationRow, ExecutionFillRow, ExecutionEventRow):
            self.session.execute(delete(table).where(table.order_id.in_(orders)))
        # children before parents, for the self-reference
        self.session.execute(
            delete(ExecutionOrderRow).where(
                ExecutionOrderRow.trade_date == trade_date, ExecutionOrderRow.parent_id.is_not(None)
            )
        )
        self.session.execute(delete(ExecutionOrderRow).where(ExecutionOrderRow.trade_date == trade_date))

    def save_day(
        self,
        trade_date: date,
        executions: Sequence[ExecutionResult],
        costs: Sequence[OrderCost],
        allocations: Sequence[Sequence[Allocation]],
    ) -> dict[str, int]:
        self._clear(trade_date)
        now = utcnow()
        stamps = {"created_at": now, "updated_at": now}

        def order_row(order: Order) -> dict:
            return {
                "order_id": order.order_id,
                "parent_id": order.parent_id,
                "trade_date": order.trade_date,
                "instrument_id": order.instrument_id,
                "side": order.side.value,
                "quantity": order.quantity,
                "filled": order.cumulative,
                "average_price": order.average_price,
                "status": order.status.value,
                "algorithm": order.algorithm,
                "decision_price": order.decision_price,
                "limit_price": order.limit_price,
                **stamps,
            }

        parents = [result.parent for result in executions]
        children = [child for result in executions for child in result.children]
        self.session.execute(insert(ExecutionOrderRow), [order_row(order) for order in parents])
        if children:
            self.session.execute(insert(ExecutionOrderRow), [order_row(order) for order in children])
        events = [
            {
                "order_id": order.order_id,
                "sequence": number,
                "minute": event.minute,
                "status": event.status.value,
                "note": event.note[:256],
                **stamps,
            }
            for order in [*parents, *children]
            for number, event in enumerate(order.events, start=1)
        ]
        self.session.execute(insert(ExecutionEventRow), events)
        fills = [
            {
                "fill_id": fill.fill_id,
                "order_id": fill.order_id,
                "minute": fill.minute,
                "quantity": fill.quantity,
                "price": fill.price,
                **stamps,
            }
            for order in children
            for fill in order.fills
        ]
        if fills:
            self.session.execute(insert(ExecutionFillRow), fills)
        shares = [
            {
                "order_id": result.parent.order_id,
                "portfolio_id": item.portfolio_id,
                "instrument_id": item.instrument_id,
                "side": item.side.value,
                "requested": item.requested,
                "quantity": item.quantity,
                "price": item.price,
                **stamps,
            }
            for result, items in zip(executions, allocations, strict=True)
            for item in items
        ]
        if shares:
            self.session.execute(insert(OrderAllocationRow), shares)
        cost_rows = [
            {
                "order_id": cost.order_id,
                "algorithm": cost.algorithm,
                "decision_price": cost.decision,
                "arrival_price": cost.arrival,
                "close_price": cost.close,
                "vwap": cost.vwap,
                "participation": cost.participation,
                "size_adv": cost.size_adv,
                "paper_value": cost.paper_value,
                "delay": cost.delay,
                "spread": cost.spread,
                "temporary_impact": cost.temporary,
                "permanent_impact": cost.permanent,
                "timing": cost.timing,
                "opportunity": cost.opportunity,
                "fees": cost.fees,
                "shortfall": cost.shortfall,
                **stamps,
            }
            for cost in costs
        ]
        self.session.execute(insert(TransactionCostRow), cost_rows)
        return {
            "order": len(parents) + len(children),
            "event": len(events),
            "fill": len(fills),
            "allocation": len(shares),
            "transaction cost": len(cost_rows),
        }

    def blocks(self, trade_date: date) -> list[ExecutionOrderRow]:
        return list(
            self.session.scalars(
                select(ExecutionOrderRow)
                .where(ExecutionOrderRow.trade_date == trade_date, ExecutionOrderRow.parent_id.is_(None))
                .order_by(ExecutionOrderRow.order_id)
            )
        )

    def children(self, parent_id: str) -> list[ExecutionOrderRow]:
        return list(
            self.session.scalars(
                select(ExecutionOrderRow)
                .where(ExecutionOrderRow.parent_id == parent_id)
                .order_by(ExecutionOrderRow.order_id)
            )
        )

    def events(self, order_id: str) -> list[ExecutionEventRow]:
        return list(
            self.session.scalars(
                select(ExecutionEventRow)
                .where(ExecutionEventRow.order_id == order_id)
                .order_by(ExecutionEventRow.sequence)
            )
        )

    def filled_by_block(self, trade_date: date) -> dict[str, float]:
        """Shares filled per block, summed in SQL from its children's fills."""
        statement = (
            select(ExecutionOrderRow.parent_id, func.sum(ExecutionFillRow.quantity))
            .join(ExecutionFillRow, ExecutionFillRow.order_id == ExecutionOrderRow.order_id)
            .where(ExecutionOrderRow.trade_date == trade_date)
            .group_by(ExecutionOrderRow.parent_id)
        )
        return {str(parent): float(total) for parent, total in self.session.execute(statement)}

    def allocations(self, portfolio_id: str) -> list[OrderAllocationRow]:
        return list(
            self.session.scalars(
                select(OrderAllocationRow)
                .where(OrderAllocationRow.portfolio_id == portfolio_id)
                .order_by(OrderAllocationRow.order_id)
            )
        )

    def cost_by_algorithm(self, trade_date: date) -> dict[str, tuple[float, float]]:
        """Shortfall and paper value by algorithm, summed in SQL."""
        statement = (
            select(
                TransactionCostRow.algorithm,
                func.sum(TransactionCostRow.shortfall),
                func.sum(TransactionCostRow.paper_value),
            )
            .join(ExecutionOrderRow, ExecutionOrderRow.order_id == TransactionCostRow.order_id)
            .where(ExecutionOrderRow.trade_date == trade_date)
            .group_by(TransactionCostRow.algorithm)
        )
        return {str(name): (float(total), float(value)) for name, total, value in self.session.execute(statement)}
