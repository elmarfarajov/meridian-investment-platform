"""Execution: orders and their audit trail, fills, allocations to accounts, and transaction costs.

``execution_orders`` keeps block orders and their child orders (a child points
at its parent) with the final state; ``execution_events`` every transition of
every order, the audit trail; ``execution_fills`` the execution reports;
``order_allocations`` each account's share of a block, at one price; and
``transaction_costs`` each block's implementation shortfall, decomposed.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPS = (
    ("created_at", sa.DateTime(timezone=True)),
    ("updated_at", sa.DateTime(timezone=True)),
)


def _timestamps() -> list[sa.Column]:
    return [sa.Column(name, kind, nullable=False) for name, kind in TIMESTAMPS]


def _floats(*names: str, nullable: bool = False) -> list[sa.Column]:
    return [sa.Column(name, sa.Float(), nullable=nullable) for name in names]


def _order_key(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["order_id"], ["execution_orders.order_id"], name=op.f(f"fk_{table}_order_id_execution_orders")
    )


def upgrade() -> None:
    op.create_table(
        "execution_orders",
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        *_floats("quantity", "filled"),
        sa.Column("average_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("algorithm", sa.String(length=16), nullable=True),
        *_floats("decision_price", "limit_price", nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["execution_orders.order_id"], name=op.f("fk_execution_orders_parent_id_execution_orders")
        ),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_execution_orders")),
    )
    op.create_index(op.f("ix_execution_orders_parent_id"), "execution_orders", ["parent_id"])
    op.create_index(op.f("ix_execution_orders_trade_date"), "execution_orders", ["trade_date"])
    op.create_table(
        "execution_events",
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("note", sa.String(length=256), nullable=False),
        *_timestamps(),
        _order_key("execution_events"),
        sa.PrimaryKeyConstraint("order_id", "sequence", name=op.f("pk_execution_events")),
    )
    op.create_table(
        "execution_fills",
        sa.Column("fill_id", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        *_floats("quantity", "price"),
        *_timestamps(),
        _order_key("execution_fills"),
        sa.PrimaryKeyConstraint("fill_id", name=op.f("pk_execution_fills")),
    )
    op.create_index(op.f("ix_execution_fills_order_id"), "execution_fills", ["order_id"])
    op.create_table(
        "order_allocations",
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        *_floats("requested", "quantity", "price"),
        *_timestamps(),
        _order_key("order_allocations"),
        sa.PrimaryKeyConstraint("order_id", "portfolio_id", name=op.f("pk_order_allocations")),
    )
    op.create_table(
        "transaction_costs",
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=16), nullable=False),
        *_floats("decision_price", "arrival_price", "close_price"),
        sa.Column("vwap", sa.Float(), nullable=True),
        *_floats(
            "participation",
            "size_adv",
            "paper_value",
            "delay",
            "spread",
            "temporary_impact",
            "permanent_impact",
            "timing",
            "opportunity",
            "fees",
            "shortfall",
        ),
        *_timestamps(),
        _order_key("transaction_costs"),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_transaction_costs")),
    )


def downgrade() -> None:
    op.drop_table("transaction_costs")
    op.drop_table("order_allocations")
    op.drop_index(op.f("ix_execution_fills_order_id"), table_name="execution_fills")
    op.drop_table("execution_fills")
    op.drop_table("execution_events")
    op.drop_index(op.f("ix_execution_orders_trade_date"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_parent_id"), table_name="execution_orders")
    op.drop_table("execution_orders")
