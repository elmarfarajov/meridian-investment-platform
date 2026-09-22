"""Market data: raw observations, corporate actions, the identifier cross-reference, quality results.

``price_observations`` is append-only and keyed by knowledge time as well as
value date, so any past state of knowledge can be rebuilt (ADR 0009).
``identifier_xref`` carries validity intervals and deliberately has no foreign
key to ``instruments``: it must remember identifiers of securities that have
left the book (ADR 0012). Quality findings reference their run, so a run and
everything it found can be read or discarded together.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identifier_xref",
        sa.Column("scheme", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=32), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scheme", "value", "valid_from", name=op.f("pk_identifier_xref")),
    )
    with op.batch_alter_table("identifier_xref", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_identifier_xref_instrument_id"), ["instrument_id"], unique=False)

    op.create_table(
        "quality_runs",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("series_count", sa.Integer(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("blocking_count", sa.Integer(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_quality_runs")),
    )
    with op.batch_alter_table("quality_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_quality_runs_as_of"), ["as_of"], unique=False)

    op.create_table(
        "corporate_actions",
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=24), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("announced", sa.Date(), nullable=True),
        sa.Column("related_instrument_id", sa.String(length=64), nullable=True),
        sa.Column("terms_json", sa.String(length=1024), nullable=False),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.instrument_id"],
            name=op.f("fk_corporate_actions_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint("action_id", name=op.f("pk_corporate_actions")),
    )
    with op.batch_alter_table("corporate_actions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_corporate_actions_action_type"), ["action_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_corporate_actions_ex_date"), ["ex_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_corporate_actions_instrument_id"), ["instrument_id"], unique=False)

    op.create_table(
        "price_observations",
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("price_type", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("bid", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("ask", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("volume", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.instrument_id"],
            name=op.f("fk_price_observations_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint(
            "instrument_id", "price_date", "price_type", "source", "recorded_at", name=op.f("pk_price_observations")
        ),
    )
    with op.batch_alter_table("price_observations", schema=None) as batch_op:
        batch_op.create_index("ix_price_observations_instrument_date", ["instrument_id", "price_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_price_observations_run_id"), ["run_id"], unique=False)

    op.create_table(
        "quality_findings",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("finding_id", sa.String(length=160), nullable=False),
        sa.Column("rule", sa.String(length=48), nullable=False),
        sa.Column("series_key", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("end_day", sa.Date(), nullable=True),
        sa.Column("severity", sa.String(length=12), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.Column("observed", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["quality_runs.run_id"], name=op.f("fk_quality_findings_run_id_quality_runs")
        ),
        sa.PrimaryKeyConstraint("run_id", "finding_id", name=op.f("pk_quality_findings")),
    )
    with op.batch_alter_table("quality_findings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_quality_findings_day"), ["day"], unique=False)
        batch_op.create_index(batch_op.f("ix_quality_findings_rule"), ["rule"], unique=False)
        batch_op.create_index(batch_op.f("ix_quality_findings_series_key"), ["series_key"], unique=False)
        batch_op.create_index(batch_op.f("ix_quality_findings_severity"), ["severity"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("quality_findings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quality_findings_severity"))
        batch_op.drop_index(batch_op.f("ix_quality_findings_series_key"))
        batch_op.drop_index(batch_op.f("ix_quality_findings_rule"))
        batch_op.drop_index(batch_op.f("ix_quality_findings_day"))

    op.drop_table("quality_findings")
    with op.batch_alter_table("price_observations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_price_observations_run_id"))
        batch_op.drop_index("ix_price_observations_instrument_date")

    op.drop_table("price_observations")
    with op.batch_alter_table("corporate_actions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_corporate_actions_instrument_id"))
        batch_op.drop_index(batch_op.f("ix_corporate_actions_ex_date"))
        batch_op.drop_index(batch_op.f("ix_corporate_actions_action_type"))

    op.drop_table("corporate_actions")
    with op.batch_alter_table("quality_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quality_runs_as_of"))

    op.drop_table("quality_runs")
    with op.batch_alter_table("identifier_xref", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_identifier_xref_instrument_id"))

    op.drop_table("identifier_xref")
