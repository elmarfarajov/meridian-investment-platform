"""A breach is recorded per rule and group: which issuer, sector or currency broke the limit.

Until the Day 6 revisit the register kept one breach per rule, so two issuers over
a single-issuer limit were one record, judged active or passive by the heaviest
alone. ``group_label`` names the group (empty for a rule that is one number, such
as a cash band).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "compliance_breaches",
        sa.Column("group_label", sa.String(length=128), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("compliance_breaches", "group_label")
