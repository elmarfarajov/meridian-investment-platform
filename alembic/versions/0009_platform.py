"""The web platform: users, the hash-chained audit log, idempotency keys and order requests.

``platform_users`` keeps each user's salted PBKDF2 password hash, roles and (for
a client) the portfolios they may see. ``audit_log`` records every request,
each record carrying the SHA-256 hash of the previous one so that an edited or
deleted record breaks the chain. ``idempotency_keys`` lets a client retry a
write safely. ``order_requests`` keeps orders entered through the platform with
their pre-trade decision and four-eyes approval.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
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
        "platform_users",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("roles", sa.String(length=256), nullable=False),
        sa.Column("portfolios", sa.String(length=512), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("username", name=op.f("pk_platform_users")),
    )
    op.create_table(
        "audit_log",
        sa.Column("sequence", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=256), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("detail", sa.String(length=512), nullable=True),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("sequence", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_username"), "audit_log", ["username"])
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=256), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.String(length=20000), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("key", "username", name=op.f("pk_idempotency_keys")),
    )
    op.create_table(
        "order_requests",
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("pretrade_decision", sa.String(length=24), nullable=False),
        sa.Column("pretrade_reasons", sa.String(length=2000), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("decision_note", sa.String(length=512), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_order_requests")),
    )
    op.create_index(op.f("ix_order_requests_portfolio_id"), "order_requests", ["portfolio_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_order_requests_portfolio_id"), table_name="order_requests")
    op.drop_table("order_requests")
    op.drop_table("idempotency_keys")
    op.drop_index(op.f("ix_audit_log_username"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("platform_users")
