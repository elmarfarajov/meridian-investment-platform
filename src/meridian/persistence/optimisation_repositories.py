"""Rebalancing in the database: the proposal, its orders and the lots they relieve, the frontier, the backtests.

A proposal has to answer an investment committee's questions after the fact:
what the optimiser was asked to do (its risk aversion, whether it harvested,
how it chose lots), what it proposed and why (the tracking error it bought and
the tax it paid for it, the rounds it took to settle), what was actually sent
(whole-lot orders beside the continuous trades) and what the compliance engine
said. Saving a proposal again under the same identifier replaces it whole.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from .base import utcnow
from .models import (
    ProposedLotSaleRow,
    ProposedOrderRow,
    RebalanceFrontierRow,
    RebalanceProposalRow,
    TaxAlphaResultRow,
)

if TYPE_CHECKING:  # the optimiser (and cvxpy) is not loaded just to open a session
    from ..optimisation.backtest import BacktestSummary
    from ..optimisation.frontier import Frontier
    from ..optimisation.rebalance import RebalanceResult, Settings
    from ..optimisation.rounding import RoundedRebalance


class OptimisationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ proposals
    def save_proposal(
        self,
        proposal_id: str,
        portfolio_id: str,
        settings: Settings,
        result: RebalanceResult,
        rounded: RoundedRebalance,
        decision: str,
        frontier: Frontier | None = None,
    ) -> dict[str, int]:
        for table in (RebalanceFrontierRow, ProposedLotSaleRow, ProposedOrderRow):
            self.session.execute(delete(table).where(table.proposal_id == proposal_id))
        self.session.execute(delete(RebalanceProposalRow).where(RebalanceProposalRow.proposal_id == proposal_id))
        now = utcnow()
        stamps = {"created_at": now, "updated_at": now}
        sales = rounded.sales
        self.session.execute(
            insert(RebalanceProposalRow),
            [
                {
                    "proposal_id": proposal_id,
                    "portfolio_id": portfolio_id,
                    "as_of": result.as_of,
                    "risk_aversion": settings.risk_aversion,
                    "harvest": settings.harvest,
                    "lot_relief": settings.lot_relief,
                    "status": result.status,
                    "solver": result.solver,
                    "rounds": result.rounds,
                    "nav": result.nav,
                    "tracking_error_before": result.tracking_error_before,
                    "tracking_error_after": rounded.tracking_error_after,
                    "active_share_before": result.active_share_before,
                    "active_share_after": rounded.active_share_after,
                    "tax": rounded.tax,
                    "realised_gains": sum(sale.gain for sale in sales if sale.gain > 0),
                    "realised_losses": -sum(sale.gain for sale in sales if sale.gain < 0),
                    "cost": rounded.cost * result.nav,
                    "turnover": sum(ticket.value for ticket in rounded.tickets) / result.nav,
                    "cash_before": result.cash_before,
                    "cash_after": rounded.cash_after,
                    "compliance_decision": decision,
                    "repairs": "; ".join(result.repairs)[:4000],
                    **stamps,
                }
            ],
        )
        orders = [
            {
                "proposal_id": proposal_id,
                "sequence": sequence,
                "instrument_id": ticket.asset_id,
                "side": ticket.side,
                "units": ticket.units,
                "value": ticket.value,
                "continuous_value": rounded.continuous.get(ticket.asset_id, 0.0),
                **stamps,
            }
            for sequence, ticket in enumerate(rounded.tickets, start=1)
        ]
        if orders:
            self.session.execute(insert(ProposedOrderRow), orders)
        lots = [
            {
                "proposal_id": proposal_id,
                "lot_id": sale.lot.lot_id,
                "instrument_id": sale.lot.asset_id,
                "units": sale.units,
                "gain": sale.gain,
                "tax": sale.tax,
                "long_term": sale.long_term,
                "wash_sale": sale.wash_sale,
                **stamps,
            }
            for sale in sales
        ]
        if lots:
            self.session.execute(insert(ProposedLotSaleRow), lots)
        points = []
        if frontier is not None:
            points = [
                {
                    "proposal_id": proposal_id,
                    "point": index,
                    "tax": point.tax,
                    "tracking_error": point.tracking_error,
                    "cost": point.cost,
                    "turnover": point.turnover,
                    **stamps,
                }
                for index, point in enumerate(frontier.points)
            ]
            if points:
                self.session.execute(insert(RebalanceFrontierRow), points)
        return {"proposal": 1, "order": len(orders), "lot sale": len(lots), "frontier point": len(points)}

    def proposal(self, proposal_id: str) -> RebalanceProposalRow | None:
        return self.session.get(RebalanceProposalRow, proposal_id)

    def proposals(self, portfolio_id: str) -> list[RebalanceProposalRow]:
        return list(
            self.session.scalars(
                select(RebalanceProposalRow)
                .where(RebalanceProposalRow.portfolio_id == portfolio_id)
                .order_by(RebalanceProposalRow.as_of, RebalanceProposalRow.proposal_id)
            )
        )

    def orders(self, proposal_id: str) -> list[ProposedOrderRow]:
        return list(
            self.session.scalars(
                select(ProposedOrderRow)
                .where(ProposedOrderRow.proposal_id == proposal_id)
                .order_by(ProposedOrderRow.sequence)
            )
        )

    def lot_sales(self, proposal_id: str) -> list[ProposedLotSaleRow]:
        return list(
            self.session.scalars(
                select(ProposedLotSaleRow)
                .where(ProposedLotSaleRow.proposal_id == proposal_id)
                .order_by(ProposedLotSaleRow.instrument_id, ProposedLotSaleRow.lot_id)
            )
        )

    def tax_by_term(self, proposal_id: str) -> dict[str, tuple[float, float]]:
        """Gain and tax realised by holding period (and wash-sale deferrals), summed in SQL."""
        statement = (
            select(
                ProposedLotSaleRow.long_term,
                ProposedLotSaleRow.wash_sale,
                func.sum(ProposedLotSaleRow.gain),
                func.sum(ProposedLotSaleRow.tax),
            )
            .where(ProposedLotSaleRow.proposal_id == proposal_id)
            .group_by(ProposedLotSaleRow.long_term, ProposedLotSaleRow.wash_sale)
        )
        output: dict[str, tuple[float, float]] = {}
        for long_term, wash_sale, gain, tax in self.session.execute(statement):
            key = "wash sale" if wash_sale else "long-term" if long_term else "short-term"
            previous = output.get(key, (0.0, 0.0))
            output[key] = (previous[0] + float(gain), previous[1] + float(tax))
        return output

    def frontier(self, proposal_id: str) -> list[RebalanceFrontierRow]:
        return list(
            self.session.scalars(
                select(RebalanceFrontierRow)
                .where(RebalanceFrontierRow.proposal_id == proposal_id)
                .order_by(RebalanceFrontierRow.point)
            )
        )

    # ------------------------------------------------------------------ backtests
    def save_backtest(self, backtest_id: str, summary: BacktestSummary) -> int:
        self.session.execute(delete(TaxAlphaResultRow).where(TaxAlphaResultRow.backtest_id == backtest_id))
        now = utcnow()
        rows = [
            {
                "backtest_id": backtest_id,
                "strategy": str(row["strategy"]),
                "paths": len(summary.paths),
                "months": summary.config.months,
                "pre_tax": float(row["pre_tax"]),
                "after_tax": float(row["after_tax"]),
                "tax_alpha": float(row["tax_alpha"]),
                "tax_alpha_held": float(row["tax_alpha_held"]),
                "tracking_error": float(row["tracking_error"]),
                "harvested": float(row["harvested"]),
                "turnover": float(row["turnover"]),
                "created_at": now,
                "updated_at": now,
            }
            for row in summary.table()
        ]
        self.session.execute(insert(TaxAlphaResultRow), rows)
        return len(rows)

    def backtest(self, backtest_id: str) -> list[TaxAlphaResultRow]:
        return list(
            self.session.scalars(
                select(TaxAlphaResultRow)
                .where(TaxAlphaResultRow.backtest_id == backtest_id)
                .order_by(TaxAlphaResultRow.tax_alpha.desc())
            )
        )
