"""SQLAlchemy tables.

The schema mirrors the domain model but stays deliberately flat: identifiers are
columns rather than a separate table, because every query on a security starts
from one of them, and the write volume for reference data is low.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, String, UniqueConstraint
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

    __table_args__ = (Index("ix_tax_lots_portfolio_instrument", "portfolio_id", "instrument_id"),)


class PriceRow(TimestampMixin, Base):
    """End-of-day marks; the market data module fills this from Day 2."""

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
