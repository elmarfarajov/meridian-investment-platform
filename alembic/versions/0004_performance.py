"""Performance: daily returns and linked attribution effects.

``performance_returns`` keeps one row per portfolio per day - the capital at
risk, the investment result, the time-weighted return and the benchmark's - so
any period can be linked again later. ``attribution_effects`` keeps linked
effects per period, dimension and segment (and per currency, and costs),
because linking is not additive across periods and a report must show exactly
the numbers computed for its own period.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attribution_effects",
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("segment", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("average_portfolio_weight", sa.Float(), nullable=True),
        sa.Column("average_benchmark_weight", sa.Float(), nullable=True),
        sa.Column("allocation", sa.Float(), nullable=False),
        sa.Column("selection", sa.Float(), nullable=False),
        sa.Column("interaction", sa.Float(), nullable=False),
        sa.Column("currency", sa.Float(), nullable=False),
        sa.Column("costs", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_attribution_effects_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint(
            "portfolio_id", "period_start", "period_end", "dimension", "segment", name=op.f("pk_attribution_effects")
        ),
    )
    op.create_table(
        "performance_returns",
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("capital", sa.Float(), nullable=False),
        sa.Column("result", sa.Float(), nullable=False),
        sa.Column("portfolio_return", sa.Float(), nullable=False),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("benchmark_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_performance_returns_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("portfolio_id", "return_date", name=op.f("pk_performance_returns")),
    )


def downgrade() -> None:
    op.drop_table("performance_returns")
    op.drop_table("attribution_effects")
