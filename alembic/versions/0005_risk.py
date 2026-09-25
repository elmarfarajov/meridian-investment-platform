"""Risk: factor returns, daily forecasts with their outcomes, and report exposures.

``risk_factor_returns`` keeps a model's daily factor returns, one row per day
and factor, so any covariance forecast the model made can be rebuilt from SQL.
``risk_forecasts`` keeps each morning's forecast for a portfolio - volatility,
tracking error, the 99% VaR - with the day's realised and active return, so
the backtest can be recomputed from the database. ``risk_exposures`` keeps a
risk report's factor exposures for portfolio and benchmark and each factor's
contribution to tracking error.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_factor_returns",
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("factor", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("model_id", "return_date", "factor", name=op.f("pk_risk_factor_returns")),
    )
    op.create_table(
        "risk_forecasts",
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("weekdays", sa.Integer(), nullable=False),
        sa.Column("volatility", sa.Float(), nullable=False),
        sa.Column("tracking_error", sa.Float(), nullable=False),
        sa.Column("factor_share", sa.Float(), nullable=False),
        sa.Column("var_99", sa.Float(), nullable=False),
        sa.Column("realised", sa.Float(), nullable=False),
        sa.Column("active", sa.Float(), nullable=False),
        sa.Column("exception", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_risk_forecasts_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("portfolio_id", "forecast_date", name=op.f("pk_risk_forecasts")),
    )
    op.create_table(
        "risk_exposures",
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("factor", sa.String(length=64), nullable=False),
        sa.Column("factor_group", sa.String(length=16), nullable=False),
        sa.Column("portfolio", sa.Float(), nullable=False),
        sa.Column("benchmark", sa.Float(), nullable=False),
        sa.Column("active_contribution", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_risk_exposures_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("portfolio_id", "as_of", "factor", name=op.f("pk_risk_exposures")),
    )


def downgrade() -> None:
    op.drop_table("risk_exposures")
    op.drop_table("risk_forecasts")
    op.drop_table("risk_factor_returns")
