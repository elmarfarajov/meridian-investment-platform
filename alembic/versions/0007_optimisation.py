"""Tax-aware rebalancing: proposals, their orders and lot sales, the frontier, and tax-alpha backtests.

``rebalance_proposals`` keeps each proposal with the settings it ran with,
what it achieved (tracking error, active share, tax, cost, turnover) and the
compliance engine's decision on it. ``proposed_orders`` are its tickets, rounded
to whole lots, beside the optimiser's continuous trade; ``proposed_lot_sales``
the tax lots they relieve. ``rebalance_frontier`` keeps the tracking-error /
tax frontier computed with it, and ``tax_alpha_results`` each manager's
averages over a backtest.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPS = (
    ("created_at", sa.DateTime(timezone=True)),
    ("updated_at", sa.DateTime(timezone=True)),
)


def _timestamps() -> list[sa.Column]:
    return [sa.Column(name, kind, nullable=False) for name, kind in TIMESTAMPS]


def _floats(*names: str) -> list[sa.Column]:
    return [sa.Column(name, sa.Float(), nullable=False) for name in names]


def upgrade() -> None:
    op.create_table(
        "rebalance_proposals",
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("risk_aversion", sa.Float(), nullable=False),
        sa.Column("harvest", sa.Boolean(), nullable=False),
        sa.Column("lot_relief", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("solver", sa.String(length=16), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=False),
        *_floats(
            "nav",
            "tracking_error_before",
            "tracking_error_after",
            "active_share_before",
            "active_share_after",
            "tax",
            "realised_gains",
            "realised_losses",
            "cost",
            "turnover",
            "cash_before",
            "cash_after",
        ),
        sa.Column("compliance_decision", sa.String(length=24), nullable=False),
        sa.Column("repairs", sa.String(length=4000), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_rebalance_proposals_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("proposal_id", name=op.f("pk_rebalance_proposals")),
    )
    op.create_index(op.f("ix_rebalance_proposals_portfolio_id"), "rebalance_proposals", ["portfolio_id"])
    op.create_table(
        "proposed_orders",
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        *_floats("units", "value", "continuous_value"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["rebalance_proposals.proposal_id"],
            name=op.f("fk_proposed_orders_proposal_id_rebalance_proposals"),
        ),
        sa.PrimaryKeyConstraint("proposal_id", "sequence", name=op.f("pk_proposed_orders")),
    )
    op.create_table(
        "proposed_lot_sales",
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("lot_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        *_floats("units", "gain", "tax"),
        sa.Column("long_term", sa.Boolean(), nullable=False),
        sa.Column("wash_sale", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["rebalance_proposals.proposal_id"],
            name=op.f("fk_proposed_lot_sales_proposal_id_rebalance_proposals"),
        ),
        sa.PrimaryKeyConstraint("proposal_id", "lot_id", name=op.f("pk_proposed_lot_sales")),
    )
    op.create_index(op.f("ix_proposed_lot_sales_instrument_id"), "proposed_lot_sales", ["instrument_id"])
    op.create_table(
        "rebalance_frontier",
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("point", sa.Integer(), nullable=False),
        *_floats("tax", "tracking_error", "cost", "turnover"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["rebalance_proposals.proposal_id"],
            name=op.f("fk_rebalance_frontier_proposal_id_rebalance_proposals"),
        ),
        sa.PrimaryKeyConstraint("proposal_id", "point", name=op.f("pk_rebalance_frontier")),
    )
    op.create_table(
        "tax_alpha_results",
        sa.Column("backtest_id", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("paths", sa.Integer(), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        *_floats("pre_tax", "after_tax", "tax_alpha", "tax_alpha_held", "tracking_error", "harvested", "turnover"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("backtest_id", "strategy", name=op.f("pk_tax_alpha_results")),
    )


def downgrade() -> None:
    op.drop_table("tax_alpha_results")
    op.drop_table("rebalance_frontier")
    op.drop_index(op.f("ix_proposed_lot_sales_instrument_id"), table_name="proposed_lot_sales")
    op.drop_table("proposed_lot_sales")
    op.drop_table("proposed_orders")
    op.drop_index(op.f("ix_rebalance_proposals_portfolio_id"), table_name="rebalance_proposals")
    op.drop_table("rebalance_proposals")
