"""Initial schema: reference data, portfolios, transactions, tax lots, prices, FX.

Tables are created in dependency order so the foreign keys resolve on a database
that enforces them immediately. Index creation goes through ``batch_alter_table``
because SQLite - the local development database - cannot alter a table in place.

Revision ID: 0001
Revises:
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmarks",
        sa.Column("benchmark_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("benchmark_id", name=op.f("pk_benchmarks")),
    )
    op.create_table(
        "clients",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("domicile", sa.String(length=2), nullable=True),
        sa.Column("tax_residence", sa.String(length=2), nullable=True),
        sa.Column("onboarded", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("client_id", name=op.f("pk_clients")),
    )
    op.create_table(
        "fx_rates",
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=12), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("base_currency", "quote_currency", "rate_date", name=op.f("pk_fx_rates")),
    )
    op.create_table(
        "households",
        sa.Column("household_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("household_id", name=op.f("pk_households")),
    )
    op.create_table(
        "instruments",
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("instrument_type", sa.String(length=32), nullable=False),
        sa.Column("asset_class", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("cusip", sa.String(length=9), nullable=True),
        sa.Column("sedol", sa.String(length=7), nullable=True),
        sa.Column("figi", sa.String(length=12), nullable=True),
        sa.Column("ticker", sa.String(length=24), nullable=True),
        sa.Column("exchange", sa.String(length=16), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("calendar", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("multiplier", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("industry", sa.String(length=64), nullable=True),
        sa.Column("issuer_id", sa.String(length=64), nullable=True),
        sa.Column("coupon", sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column("maturity", sa.Date(), nullable=True),
        sa.Column("face_value", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("expense_ratio", sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column("benchmark_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("instrument_id", name=op.f("pk_instruments")),
        sa.UniqueConstraint("isin", name="uq_instruments_isin"),
    )
    with op.batch_alter_table("instruments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_instruments_asset_class"), ["asset_class"], unique=False)
        batch_op.create_index(batch_op.f("ix_instruments_currency"), ["currency"], unique=False)
        batch_op.create_index(batch_op.f("ix_instruments_cusip"), ["cusip"], unique=False)
        batch_op.create_index(batch_op.f("ix_instruments_instrument_type"), ["instrument_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_instruments_isin"), ["isin"], unique=False)
        batch_op.create_index(batch_op.f("ix_instruments_issuer_id"), ["issuer_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_instruments_sector"), ["sector"], unique=False)
        batch_op.create_index(batch_op.f("ix_instruments_ticker"), ["ticker"], unique=False)

    op.create_table(
        "accounts",
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("household_id", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("custodian", sa.String(length=64), nullable=True),
        sa.Column("opened", sa.Date(), nullable=True),
        sa.Column("closed", sa.Date(), nullable=True),
        sa.Column("calendar", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.client_id"], name=op.f("fk_accounts_client_id_clients")),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.household_id"], name=op.f("fk_accounts_household_id_households")
        ),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_accounts")),
    )
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_accounts_account_type"), ["account_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_accounts_client_id"), ["client_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_accounts_household_id"), ["household_id"], unique=False)

    op.create_table(
        "prices",
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("price_type", sa.String(length=24), nullable=False),
        sa.Column("price", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.instrument_id"], name=op.f("fk_prices_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("instrument_id", "price_date", "price_type", name=op.f("pk_prices")),
    )
    op.create_table(
        "portfolios",
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("benchmark_id", sa.String(length=64), nullable=True),
        sa.Column("strategy", sa.String(length=64), nullable=True),
        sa.Column("inception", sa.Date(), nullable=True),
        sa.Column("policy_json", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.account_id"], name=op.f("fk_portfolios_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_id"], ["benchmarks.benchmark_id"], name=op.f("fk_portfolios_benchmark_id_benchmarks")
        ),
        sa.PrimaryKeyConstraint("portfolio_id", name=op.f("pk_portfolios")),
    )
    with op.batch_alter_table("portfolios", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_portfolios_account_id"), ["account_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_portfolios_benchmark_id"), ["benchmark_id"], unique=False)

    op.create_table(
        "tax_lots",
        sa.Column("lot_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("open_date", sa.Date(), nullable=False),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("cost_per_unit", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("transaction_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.instrument_id"], name=op.f("fk_tax_lots_instrument_id_instruments")
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_tax_lots_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("lot_id", name=op.f("pk_tax_lots")),
    )
    with op.batch_alter_table("tax_lots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_tax_lots_instrument_id"), ["instrument_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_tax_lots_open_date"), ["open_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_tax_lots_portfolio_id"), ["portfolio_id"], unique=False)
        batch_op.create_index("ix_tax_lots_portfolio_instrument", ["portfolio_id", "instrument_id"], unique=False)

    op.create_table(
        "transactions",
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=True),
        sa.Column("transaction_type", sa.String(length=24), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("price", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("gross_amount", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("fees", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("taxes", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fx_rate", sa.Numeric(precision=20, scale=12), nullable=False),
        sa.Column("lot_id", sa.String(length=64), nullable=True),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.instrument_id"], name=op.f("fk_transactions_instrument_id_instruments")
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.portfolio_id"], name=op.f("fk_transactions_portfolio_id_portfolios")
        ),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_transactions")),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_transactions_instrument_id"), ["instrument_id"], unique=False)
        batch_op.create_index("ix_transactions_portfolio_date", ["portfolio_id", "trade_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_transactions_portfolio_id"), ["portfolio_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_transactions_trade_date"), ["trade_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_transactions_transaction_type"), ["transaction_type"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transactions_transaction_type"))
        batch_op.drop_index(batch_op.f("ix_transactions_trade_date"))
        batch_op.drop_index(batch_op.f("ix_transactions_portfolio_id"))
        batch_op.drop_index("ix_transactions_portfolio_date")
        batch_op.drop_index(batch_op.f("ix_transactions_instrument_id"))

    op.drop_table("transactions")
    with op.batch_alter_table("tax_lots", schema=None) as batch_op:
        batch_op.drop_index("ix_tax_lots_portfolio_instrument")
        batch_op.drop_index(batch_op.f("ix_tax_lots_portfolio_id"))
        batch_op.drop_index(batch_op.f("ix_tax_lots_open_date"))
        batch_op.drop_index(batch_op.f("ix_tax_lots_instrument_id"))

    op.drop_table("tax_lots")
    with op.batch_alter_table("portfolios", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_portfolios_benchmark_id"))
        batch_op.drop_index(batch_op.f("ix_portfolios_account_id"))

    op.drop_table("portfolios")
    op.drop_table("prices")
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_accounts_household_id"))
        batch_op.drop_index(batch_op.f("ix_accounts_client_id"))
        batch_op.drop_index(batch_op.f("ix_accounts_account_type"))

    op.drop_table("accounts")
    with op.batch_alter_table("instruments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_instruments_ticker"))
        batch_op.drop_index(batch_op.f("ix_instruments_sector"))
        batch_op.drop_index(batch_op.f("ix_instruments_issuer_id"))
        batch_op.drop_index(batch_op.f("ix_instruments_isin"))
        batch_op.drop_index(batch_op.f("ix_instruments_instrument_type"))
        batch_op.drop_index(batch_op.f("ix_instruments_cusip"))
        batch_op.drop_index(batch_op.f("ix_instruments_currency"))
        batch_op.drop_index(batch_op.f("ix_instruments_asset_class"))

    op.drop_table("instruments")
    op.drop_table("households")
    op.drop_table("fx_rates")
    op.drop_table("clients")
    op.drop_table("benchmarks")
