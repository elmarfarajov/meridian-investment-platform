"""Compliance: versioned rules, daily results, the breach register and pre-trade decisions.

``compliance_rules`` keeps every version of a mandate as the text of each rule
with its SHA-256 hash, so a result can be traced to the wording in force.
``compliance_results`` keeps each rule's value, status, utilisation and
headroom per portfolio per day. ``compliance_breaches`` is the register: when
each breach opened and closed, active or passive, its deadline and how it
ended. ``pretrade_checks`` keeps every order's decision and the rules behind it.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPS = (
    ("created_at", sa.DateTime(timezone=True)),
    ("updated_at", sa.DateTime(timezone=True)),
)


def _timestamps() -> list[sa.Column]:
    return [sa.Column(name, kind, nullable=False) for name, kind in TIMESTAMPS]


def upgrade() -> None:
    op.create_table(
        "compliance_rules",
        sa.Column("mandate", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("effective", sa.Date(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("mandate", "version", "rule_id", name=op.f("pk_compliance_rules")),
    )
    op.create_table(
        "compliance_results",
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("check_date", sa.Date(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("mandate_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("utilisation", sa.Float(), nullable=True),
        sa.Column("headroom", sa.Float(), nullable=True),
        sa.Column("top_contributor", sa.String(length=128), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_compliance_results_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("portfolio_id", "check_date", "rule_id", name=op.f("pk_compliance_results")),
    )
    op.create_table(
        "compliance_breaches",
        sa.Column("breach_id", sa.String(length=32), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("opened", sa.Date(), nullable=False),
        sa.Column("closed", sa.Date(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("peak_utilisation", sa.Float(), nullable=False),
        sa.Column("peak_value", sa.Float(), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_compliance_breaches_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("breach_id", name=op.f("pk_compliance_breaches")),
    )
    op.create_index(op.f("ix_compliance_breaches_portfolio_id"), "compliance_breaches", ["portfolio_id"])
    op.create_table(
        "pretrade_checks",
        sa.Column("check_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("check_date", sa.Date(), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("maximum", sa.Float(), nullable=True),
        sa.Column("reasons", sa.String(length=2000), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_pretrade_checks_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("check_id", name=op.f("pk_pretrade_checks")),
    )
    op.create_index(op.f("ix_pretrade_checks_portfolio_id"), "pretrade_checks", ["portfolio_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_pretrade_checks_portfolio_id"), table_name="pretrade_checks")
    op.drop_table("pretrade_checks")
    op.drop_index(op.f("ix_compliance_breaches_portfolio_id"), table_name="compliance_breaches")
    op.drop_table("compliance_breaches")
    op.drop_table("compliance_results")
    op.drop_table("compliance_rules")
