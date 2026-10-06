"""Order numbers come from a counter, incremented atomically, not from counting the orders.

Until the Day 9 revisit the next order number was the number of orders plus
one. Two requests at the same moment counted the same orders and took the same
number, and on four processes nearly a fifth of simultaneous orders failed. The
counter row is incremented by one ``UPDATE ... RETURNING`` inside the order's
own transaction: the database hands out each number once, and an order rolled
back gives its number back.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    counters = op.create_table(
        "platform_counters",
        sa.Column("name", sa.String(length=32), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )
    existing = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM order_requests")).scalar_one()
    op.bulk_insert(counters, [{"name": "orders", "value": int(existing)}])


def downgrade() -> None:
    op.drop_table("platform_counters")
