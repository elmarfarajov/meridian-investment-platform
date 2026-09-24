"""SQLAlchemy tables.

The schema mirrors the domain model but stays deliberately flat: identifiers are
columns rather than a separate table, because every query on a security starts
from one of them, and the write volume for reference data is low.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import AMOUNT, QUANTITY, RATE, Base, TimestampMixin


class InstrumentRow(TimestampMixin, Base):
    __tablename__ = "instruments"

    instrument_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str]
    instrument_type: Mapped[str] = mapped_column(String(32), index=True)
    asset_class: Mapped[str] = mapped_column(String(32), index=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    cusip: Mapped[str | None] = mapped_column(String(9), index=True)
    sedol: Mapped[str | None] = mapped_column(String(7))
    figi: Mapped[str | None] = mapped_column(String(12))
    ticker: Mapped[str | None] = mapped_column(String(24), index=True)
    exchange: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str | None] = mapped_column(String(2))
    calendar: Mapped[str] = mapped_column(String(16), default="XNYS")
    status: Mapped[str] = mapped_column(String(16), default="active")
    multiplier: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal(1))
    sector: Mapped[str | None] = mapped_column(String(64), index=True)
    industry: Mapped[str | None] = mapped_column(String(64))
    issuer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    coupon: Mapped[Decimal | None] = mapped_column(RATE)
    maturity: Mapped[date | None] = mapped_column(Date)
    face_value: Mapped[Decimal | None] = mapped_column(AMOUNT)
    expense_ratio: Mapped[Decimal | None] = mapped_column(RATE)
    benchmark_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (UniqueConstraint("isin", name="uq_instruments_isin"),)


class BenchmarkRow(TimestampMixin, Base):
    __tablename__ = "benchmarks"

    benchmark_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str]
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str | None]


class ClientRow(TimestampMixin, Base):
    __tablename__ = "clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str]
    domicile: Mapped[str | None] = mapped_column(String(2))
    tax_residence: Mapped[str | None] = mapped_column(String(2))
    onboarded: Mapped[date | None] = mapped_column(Date)


class HouseholdRow(TimestampMixin, Base):
    __tablename__ = "households"

    household_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str]
    base_currency: Mapped[str] = mapped_column(String(3))


class AccountRow(TimestampMixin, Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str]
    account_type: Mapped[str] = mapped_column(String(32), index=True)
    base_currency: Mapped[str] = mapped_column(String(3))
    household_id: Mapped[str | None] = mapped_column(ForeignKey("households.household_id"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.client_id"), index=True)
    custodian: Mapped[str | None] = mapped_column(String(64))
    opened: Mapped[date | None] = mapped_column(Date)
    closed: Mapped[date | None] = mapped_column(Date)
    calendar: Mapped[str] = mapped_column(String(16), default="XNYS")

    portfolios: Mapped[list[PortfolioRow]] = relationship(back_populates="account", cascade="all, delete-orphan")


class PortfolioRow(TimestampMixin, Base):
    __tablename__ = "portfolios"

    portfolio_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str]
    base_currency: Mapped[str] = mapped_column(String(3))
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    benchmark_id: Mapped[str | None] = mapped_column(ForeignKey("benchmarks.benchmark_id"), index=True)
    strategy: Mapped[str | None] = mapped_column(String(64))
    inception: Mapped[date | None] = mapped_column(Date)
    policy_json: Mapped[str | None] = mapped_column(String(2048))

    account: Mapped[AccountRow | None] = relationship(back_populates="portfolios")
    transactions: Mapped[list[TransactionRow]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class TransactionRow(TimestampMixin, Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id"), index=True)
    instrument_id: Mapped[str | None] = mapped_column(ForeignKey("instruments.instrument_id"), index=True)
    transaction_type: Mapped[str] = mapped_column(String(24), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    settlement_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal(0))
    price: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    gross_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    fees: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    taxes: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3))
    fx_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal(1))
    lot_id: Mapped[str | None] = mapped_column(String(64))
    external_id: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(String(512))

    portfolio: Mapped[PortfolioRow] = relationship(back_populates="transactions")

    __table_args__ = (Index("ix_transactions_portfolio_date", "portfolio_id", "trade_date"),)


class TaxLotRow(TimestampMixin, Base):
    __tablename__ = "tax_lots"

    lot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id"), index=True)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_id"), index=True)
    open_date: Mapped[date] = mapped_column(Date, index=True)
    close_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    cost_per_unit: Mapped[Decimal] = mapped_column(AMOUNT)
    currency: Mapped[str] = mapped_column(String(3))
    transaction_id: Mapped[str | None] = mapped_column(String(64))
    holding_period_start: Mapped[date | None] = mapped_column(Date)
    open_fx_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal(1), server_default="1")
    wash_sale_adjustment: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0), server_default="0")

    __table_args__ = (Index("ix_tax_lots_portfolio_instrument", "portfolio_id", "instrument_id"),)


class PriceRow(TimestampMixin, Base):
    """The published golden copy: one mark per instrument, day and price type."""

    __tablename__ = "prices"

    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_id"), primary_key=True)
    price_date: Mapped[date] = mapped_column(Date, primary_key=True)
    price_type: Mapped[str] = mapped_column(String(24), primary_key=True, default="close")
    price: Mapped[Decimal] = mapped_column(AMOUNT)
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str | None] = mapped_column(String(32))


class FxRateRow(TimestampMixin, Base):
    __tablename__ = "fx_rates"

    base_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(RATE)
    source: Mapped[str | None] = mapped_column(String(32))


class PriceObservationRow(TimestampMixin, Base):
    """Every value any source ever sent, never updated: the bitemporal record (ADR 0009).

    ``recorded_at`` is when the platform learned the value. A vendor correction is
    a new row with a later ``recorded_at``, so any past state of knowledge can be
    rebuilt exactly. The ``prices`` table holds the published golden copy; this one
    holds the evidence it was built from.
    """

    __tablename__ = "price_observations"

    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_id"), primary_key=True)
    price_date: Mapped[date] = mapped_column(Date, primary_key=True)
    price_type: Mapped[str] = mapped_column(String(24), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    price: Mapped[Decimal] = mapped_column(AMOUNT)
    currency: Mapped[str] = mapped_column(String(3))
    bid: Mapped[Decimal | None] = mapped_column(AMOUNT)
    ask: Mapped[Decimal | None] = mapped_column(AMOUNT)
    volume: Mapped[Decimal | None] = mapped_column(QUANTITY)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True)

    __table_args__ = (Index("ix_price_observations_instrument_date", "instrument_id", "price_date"),)


class CorporateActionRow(TimestampMixin, Base):
    """Corporate actions. Common dates are columns; type-specific terms are a JSON document."""

    __tablename__ = "corporate_actions"

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_id"), index=True)
    action_type: Mapped[str] = mapped_column(String(24), index=True)
    ex_date: Mapped[date] = mapped_column(Date, index=True)
    record_date: Mapped[date | None] = mapped_column(Date)
    pay_date: Mapped[date | None] = mapped_column(Date)
    announced: Mapped[date | None] = mapped_column(Date)
    related_instrument_id: Mapped[str | None] = mapped_column(String(64))
    terms_json: Mapped[str] = mapped_column(String(1024))
    notes: Mapped[str | None] = mapped_column(String(512))


class IdentifierXrefRow(TimestampMixin, Base):
    """Identifier-to-instrument mappings with validity intervals (ADR 0012).

    ``instrument_id`` is deliberately not a foreign key: the cross-reference has
    to remember identifiers of securities that have since left the book.
    """

    __tablename__ = "identifier_xref"

    scheme: Mapped[str] = mapped_column(String(16), primary_key=True)
    value: Mapped[str] = mapped_column(String(32), primary_key=True)
    valid_from: Mapped[date] = mapped_column(Date, primary_key=True)
    valid_to: Mapped[date] = mapped_column(Date)
    instrument_id: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str | None] = mapped_column(String(32))


class QualityRunRow(TimestampMixin, Base):
    """One execution of the quality engine, with its headline numbers."""

    __tablename__ = "quality_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    series_count: Mapped[int] = mapped_column(Integer)
    finding_count: Mapped[int] = mapped_column(Integer)
    blocking_count: Mapped[int] = mapped_column(Integer)
    overall_score: Mapped[float] = mapped_column(Float)


class QualityFindingRow(TimestampMixin, Base):
    __tablename__ = "quality_findings"

    run_id: Mapped[str] = mapped_column(ForeignKey("quality_runs.run_id"), primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    rule: Mapped[str] = mapped_column(String(48), index=True)
    series_key: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str | None] = mapped_column(String(32))
    day: Mapped[date] = mapped_column(Date, index=True)
    end_day: Mapped[date | None] = mapped_column(Date)
    severity: Mapped[str] = mapped_column(String(12), index=True)
    dimension: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(512))
    observed: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)


# ---------------------------------------------------------------------------- accounting (Day 3)
class JournalEntryRow(TimestampMixin, Base):
    """One balanced journal entry. Entries are written once and never updated (ADR 0014)."""

    __tablename__ = "journal_entries"

    entry_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id"), index=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    description: Mapped[str] = mapped_column(String(256))
    source_id: Mapped[str | None] = mapped_column(String(96), index=True)
    reverses: Mapped[str | None] = mapped_column(String(96))
    cross_currency: Mapped[bool] = mapped_column(Boolean, default=False)

    postings: Mapped[list[JournalPostingRow]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="JournalPostingRow.line_no"
    )

    __table_args__ = (Index("ix_journal_entries_portfolio_date", "portfolio_id", "effective_date"),)


class JournalPostingRow(Base):
    """A line of a journal entry: debit positive, credit negative, in local and base currency."""

    __tablename__ = "journal_postings"

    entry_id: Mapped[str] = mapped_column(ForeignKey("journal_entries.entry_id", ondelete="CASCADE"), primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_code: Mapped[str] = mapped_column(String(4), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(AMOUNT)
    base_amount: Mapped[Decimal] = mapped_column(AMOUNT)
    instrument_id: Mapped[str | None] = mapped_column(String(64), index=True)
    memo: Mapped[str | None] = mapped_column(String(128))

    entry: Mapped[JournalEntryRow] = relationship(back_populates="postings")


class RealisedLotRow(TimestampMixin, Base):
    """A lot, or part of one, closed by a disposal: the unit every tax report is built from."""

    __tablename__ = "realised_lots"

    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id"), primary_key=True)
    disposal_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    lot_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(String(64), index=True)
    open_date: Mapped[date] = mapped_column(Date)
    holding_start: Mapped[date] = mapped_column(Date)
    close_date: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    currency: Mapped[str] = mapped_column(String(3))
    proceeds: Mapped[Decimal] = mapped_column(AMOUNT)
    cost: Mapped[Decimal] = mapped_column(AMOUNT)
    open_fx_rate: Mapped[Decimal] = mapped_column(RATE)
    close_fx_rate: Mapped[Decimal] = mapped_column(RATE)
    wash_sale_basis: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    disallowed_loss: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    kind: Mapped[str] = mapped_column(String(16))
    term: Mapped[str] = mapped_column(String(8), index=True)


class PortfolioValuationRow(TimestampMixin, Base):
    """Net asset value and its composition, one row per portfolio per day."""

    __tablename__ = "portfolio_valuations"

    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id"), primary_key=True)
    valuation_date: Mapped[date] = mapped_column(Date, primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3))
    nav: Mapped[Decimal] = mapped_column(AMOUNT)
    securities: Mapped[Decimal] = mapped_column(AMOUNT)
    accrued_interest: Mapped[Decimal] = mapped_column(AMOUNT)
    cash_like: Mapped[Decimal] = mapped_column(AMOUNT)
    settled_cash: Mapped[Decimal] = mapped_column(AMOUNT)
    receivables: Mapped[Decimal] = mapped_column(AMOUNT)
    payables: Mapped[Decimal] = mapped_column(AMOUNT)
    cost_base: Mapped[Decimal] = mapped_column(AMOUNT)
    unrealised_price: Mapped[Decimal] = mapped_column(AMOUNT)
    unrealised_fx: Mapped[Decimal] = mapped_column(AMOUNT)
    missing_prices: Mapped[int] = mapped_column(Integer, default=0)


class PositionValuationRow(TimestampMixin, Base):
    __tablename__ = "position_valuations"

    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id"), primary_key=True)
    valuation_date: Mapped[date] = mapped_column(Date, primary_key=True)
    instrument_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    price: Mapped[Decimal] = mapped_column(AMOUNT)
    price_date: Mapped[date] = mapped_column(Date)
    fx_rate: Mapped[Decimal] = mapped_column(RATE)
    market_value: Mapped[Decimal] = mapped_column(AMOUNT)
    market_value_base: Mapped[Decimal] = mapped_column(AMOUNT)
    accrued_base: Mapped[Decimal] = mapped_column(AMOUNT)
    cost_base: Mapped[Decimal] = mapped_column(AMOUNT)
    unrealised_price_base: Mapped[Decimal] = mapped_column(AMOUNT)
    unrealised_fx_base: Mapped[Decimal] = mapped_column(AMOUNT)


class ReconciliationBreakRow(TimestampMixin, Base):
    """A difference between the book and the custodian on one statement date, with its cause."""

    __tablename__ = "reconciliation_breaks"

    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id"), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    break_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    cause: Mapped[str] = mapped_column(String(24), index=True)
    causes: Mapped[str] = mapped_column(String(96))
    currency: Mapped[str] = mapped_column(String(3))
    book_value: Mapped[Decimal] = mapped_column(AMOUNT)
    custodian_value: Mapped[Decimal] = mapped_column(AMOUNT)
    value_base: Mapped[Decimal] = mapped_column(AMOUNT)
    explanation: Mapped[str] = mapped_column(String(256))
