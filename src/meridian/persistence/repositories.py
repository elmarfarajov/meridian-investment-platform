"""Repositories: the only place the rest of the platform touches the database.

Each repository speaks domain objects, so analytics code never imports SQLAlchemy
and can be tested with in-memory fixtures. ``upsert`` semantics are used for
reference data because market data feeds resend the same records constantly.

Queries return ``Sequence`` rather than ``list``: a query result is a snapshot of
the database, not a collection for the caller to mutate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Generic, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.exceptions import EntityNotFoundError
from ..domain.instruments import Instrument
from ..domain.portfolios import Account, Benchmark, Client, Household, Portfolio
from ..domain.positions import TaxLot
from ..domain.transactions import Transaction
from . import mappers
from .marketdata_repositories import (
    CorporateActionRepository,
    PriceObservationRepository,
    QualityRepository,
    XrefRepository,
)
from .models import (
    AccountRow,
    BenchmarkRow,
    ClientRow,
    FxRateRow,
    HouseholdRow,
    InstrumentRow,
    PortfolioRow,
    PriceRow,
    TaxLotRow,
    TransactionRow,
)

T = TypeVar("T")


class Repository(Generic[T]):
    def __init__(self, session: Session) -> None:
        self.session = session


class InstrumentRepository(Repository[Instrument]):
    def add(self, instrument: Instrument) -> Instrument:
        self.session.merge(mappers.instrument_to_row(instrument))
        return instrument

    def add_all(self, instruments: Iterable[Instrument]) -> int:
        count = 0
        for instrument in instruments:
            self.add(instrument)
            count += 1
        return count

    def get(self, instrument_id: str) -> Instrument:
        row = self.session.get(InstrumentRow, instrument_id)
        if row is None:
            raise EntityNotFoundError("Instrument", instrument_id)
        return mappers.row_to_instrument(row)

    def find(self, instrument_id: str) -> Instrument | None:
        row = self.session.get(InstrumentRow, instrument_id)
        return mappers.row_to_instrument(row) if row else None

    def by_isin(self, isin: str) -> Instrument | None:
        row = self.session.scalar(select(InstrumentRow).where(InstrumentRow.isin == isin.upper()))
        return mappers.row_to_instrument(row) if row else None

    def by_ticker(self, ticker: str) -> Sequence[Instrument]:
        pattern = ticker.upper()
        rows = self.session.scalars(
            select(InstrumentRow).where((InstrumentRow.ticker == pattern) | (InstrumentRow.ticker.like(f"{pattern}.%")))
        ).all()
        return [mappers.row_to_instrument(row) for row in rows]

    def list(
        self,
        *,
        asset_class: str | None = None,
        currency: str | None = None,
        sector: str | None = None,
        limit: int | None = None,
    ) -> Sequence[Instrument]:
        statement = select(InstrumentRow).order_by(InstrumentRow.instrument_id)
        if asset_class:
            statement = statement.where(InstrumentRow.asset_class == asset_class)
        if currency:
            statement = statement.where(InstrumentRow.currency == currency.upper())
        if sector:
            statement = statement.where(InstrumentRow.sector == sector)
        if limit:
            statement = statement.limit(limit)
        return [mappers.row_to_instrument(row) for row in self.session.scalars(statement)]

    def count(self) -> int:
        return len(self.session.scalars(select(InstrumentRow.instrument_id)).all())

    def delete(self, instrument_id: str) -> None:
        self.session.execute(delete(InstrumentRow).where(InstrumentRow.instrument_id == instrument_id))


class PortfolioRepository(Repository[Portfolio]):
    def add(self, portfolio: Portfolio) -> Portfolio:
        self.session.merge(mappers.portfolio_to_row(portfolio))
        return portfolio

    def get(self, portfolio_id: str) -> Portfolio:
        row = self.session.get(PortfolioRow, portfolio_id)
        if row is None:
            raise EntityNotFoundError("Portfolio", portfolio_id)
        return mappers.row_to_portfolio(row)

    def find(self, portfolio_id: str) -> Portfolio | None:
        row = self.session.get(PortfolioRow, portfolio_id)
        return mappers.row_to_portfolio(row) if row else None

    def list(self, *, account_id: str | None = None) -> Sequence[Portfolio]:
        statement = select(PortfolioRow).order_by(PortfolioRow.portfolio_id)
        if account_id:
            statement = statement.where(PortfolioRow.account_id == account_id)
        return [mappers.row_to_portfolio(row) for row in self.session.scalars(statement)]

    def for_household(self, household_id: str) -> Sequence[Portfolio]:
        statement = (
            select(PortfolioRow)
            .join(AccountRow, PortfolioRow.account_id == AccountRow.account_id)
            .where(AccountRow.household_id == household_id)
            .order_by(PortfolioRow.portfolio_id)
        )
        return [mappers.row_to_portfolio(row) for row in self.session.scalars(statement)]


class AccountRepository(Repository[Account]):
    def add(self, account: Account) -> Account:
        self.session.merge(mappers.account_to_row(account))
        return account

    def get(self, account_id: str) -> Account:
        row = self.session.get(AccountRow, account_id)
        if row is None:
            raise EntityNotFoundError("Account", account_id)
        return mappers.row_to_account(row)

    def list(self, *, household_id: str | None = None) -> Sequence[Account]:
        statement = select(AccountRow).order_by(AccountRow.account_id)
        if household_id:
            statement = statement.where(AccountRow.household_id == household_id)
        return [mappers.row_to_account(row) for row in self.session.scalars(statement)]


class HouseholdRepository(Repository[Household]):
    def add(self, household: Household) -> Household:
        self.session.merge(mappers.household_to_row(household))
        return household

    def get(self, household_id: str) -> Household:
        row = self.session.get(HouseholdRow, household_id)
        if row is None:
            raise EntityNotFoundError("Household", household_id)
        return mappers.row_to_household(row)


class ClientRepository(Repository[Client]):
    def add(self, client: Client) -> Client:
        self.session.merge(mappers.client_to_row(client))
        return client

    def get(self, client_id: str) -> Client:
        row = self.session.get(ClientRow, client_id)
        if row is None:
            raise EntityNotFoundError("Client", client_id)
        return mappers.row_to_client(row)


class BenchmarkRepository(Repository[Benchmark]):
    def add(self, benchmark: Benchmark) -> Benchmark:
        self.session.merge(mappers.benchmark_to_row(benchmark))
        return benchmark

    def get(self, benchmark_id: str) -> Benchmark:
        row = self.session.get(BenchmarkRow, benchmark_id)
        if row is None:
            raise EntityNotFoundError("Benchmark", benchmark_id)
        return mappers.row_to_benchmark(row)

    def list(self) -> Sequence[Benchmark]:
        rows = self.session.scalars(select(BenchmarkRow).order_by(BenchmarkRow.benchmark_id))
        return [mappers.row_to_benchmark(row) for row in rows]


class TransactionRepository(Repository[Transaction]):
    def add(self, transaction: Transaction) -> Transaction:
        self.session.merge(mappers.transaction_to_row(transaction))
        return transaction

    def add_all(self, transactions: Iterable[Transaction]) -> int:
        count = 0
        for transaction in transactions:
            self.add(transaction)
            count += 1
        return count

    def get(self, transaction_id: str) -> Transaction:
        row = self.session.get(TransactionRow, transaction_id)
        if row is None:
            raise EntityNotFoundError("Transaction", transaction_id)
        return mappers.row_to_transaction(row)

    def for_portfolio(
        self,
        portfolio_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        instrument_id: str | None = None,
    ) -> Sequence[Transaction]:
        """Transactions in trade-date order, which is the order accounting replays them."""
        statement = (
            select(TransactionRow)
            .where(TransactionRow.portfolio_id == portfolio_id)
            .order_by(TransactionRow.trade_date, TransactionRow.transaction_id)
        )
        if start:
            statement = statement.where(TransactionRow.trade_date >= start)
        if end:
            statement = statement.where(TransactionRow.trade_date <= end)
        if instrument_id:
            statement = statement.where(TransactionRow.instrument_id == instrument_id)
        return [mappers.row_to_transaction(row) for row in self.session.scalars(statement)]

    def count(self, portfolio_id: str | None = None) -> int:
        statement = select(TransactionRow.transaction_id)
        if portfolio_id:
            statement = statement.where(TransactionRow.portfolio_id == portfolio_id)
        return len(self.session.scalars(statement).all())


class TaxLotRepository(Repository[TaxLot]):
    def add(self, lot: TaxLot, portfolio_id: str) -> TaxLot:
        self.session.merge(mappers.tax_lot_to_row(lot, portfolio_id))
        return lot

    def open_lots(self, portfolio_id: str, instrument_id: str | None = None) -> Sequence[TaxLot]:
        statement = (
            select(TaxLotRow)
            .where(TaxLotRow.portfolio_id == portfolio_id, TaxLotRow.close_date.is_(None))
            .order_by(TaxLotRow.open_date, TaxLotRow.lot_id)
        )
        if instrument_id:
            statement = statement.where(TaxLotRow.instrument_id == instrument_id)
        return [mappers.row_to_tax_lot(row) for row in self.session.scalars(statement)]

    def close(self, lot_id: str, close_date: date) -> None:
        row = self.session.get(TaxLotRow, lot_id)
        if row is None:
            raise EntityNotFoundError("TaxLot", lot_id)
        row.close_date = close_date


class PriceRepository(Repository[PriceRow]):
    """The published golden copy of end-of-day marks."""

    def upsert(
        self,
        instrument_id: str,
        price_date: date,
        price: Decimal,
        currency: str,
        *,
        price_type: str = "close",
        source: str | None = None,
    ) -> None:
        self.session.merge(
            PriceRow(
                instrument_id=instrument_id,
                price_date=price_date,
                price_type=price_type,
                price=price,
                currency=currency.upper(),
                source=source,
            )
        )

    def series(
        self, instrument_id: str, *, start: date | None = None, end: date | None = None, price_type: str = "close"
    ) -> Sequence[tuple[date, Decimal]]:
        statement = (
            select(PriceRow.price_date, PriceRow.price)
            .where(PriceRow.instrument_id == instrument_id, PriceRow.price_type == price_type)
            .order_by(PriceRow.price_date)
        )
        if start:
            statement = statement.where(PriceRow.price_date >= start)
        if end:
            statement = statement.where(PriceRow.price_date <= end)
        return [(row.price_date, row.price) for row in self.session.execute(statement)]

    def latest(self, instrument_id: str, as_of: date, price_type: str = "close") -> Decimal | None:
        """Most recent mark on or before a date, which is what valuation needs."""
        statement = (
            select(PriceRow.price)
            .where(
                PriceRow.instrument_id == instrument_id,
                PriceRow.price_type == price_type,
                PriceRow.price_date <= as_of,
            )
            .order_by(PriceRow.price_date.desc())
            .limit(1)
        )
        return self.session.scalar(statement)


class FxRateRepository(Repository[FxRateRow]):
    def upsert(self, base: str, quote: str, rate_date: date, rate: Decimal, source: str | None = None) -> None:
        self.session.merge(
            FxRateRow(
                base_currency=base.upper(),
                quote_currency=quote.upper(),
                rate_date=rate_date,
                rate=rate,
                source=source,
            )
        )

    def series(self, base: str, quote: str) -> Sequence[tuple[date, Decimal]]:
        rows = self.session.execute(
            select(FxRateRow.rate_date, FxRateRow.rate)
            .where(FxRateRow.base_currency == base.upper(), FxRateRow.quote_currency == quote.upper())
            .order_by(FxRateRow.rate_date)
        )
        return [(row.rate_date, row.rate) for row in rows]

    def on(self, rate_date: date) -> Sequence[tuple[str, str, Decimal]]:
        rows = self.session.execute(
            select(FxRateRow.base_currency, FxRateRow.quote_currency, FxRateRow.rate).where(
                FxRateRow.rate_date == rate_date
            )
        )
        return [(row.base_currency, row.quote_currency, row.rate) for row in rows]


class UnitOfWork:
    """All repositories bound to one session, so a use case commits atomically."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.instruments = InstrumentRepository(session)
        self.portfolios = PortfolioRepository(session)
        self.accounts = AccountRepository(session)
        self.households = HouseholdRepository(session)
        self.clients = ClientRepository(session)
        self.benchmarks = BenchmarkRepository(session)
        self.transactions = TransactionRepository(session)
        self.tax_lots = TaxLotRepository(session)
        self.prices = PriceRepository(session)
        self.fx_rates = FxRateRepository(session)
        self.observations = PriceObservationRepository(session)
        self.corporate_actions = CorporateActionRepository(session)
        self.xref = XrefRepository(session)
        self.quality = QualityRepository(session)

    def flush(self) -> None:
        self.session.flush()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()


def seed_reference_data(
    unit_of_work: UnitOfWork,
    *,
    instruments: Sequence[Instrument] = (),
    benchmarks: Sequence[Benchmark] = (),
    clients: Sequence[Client] = (),
    households: Sequence[Household] = (),
    accounts: Sequence[Account] = (),
    portfolios: Sequence[Portfolio] = (),
) -> dict[str, int]:
    """Load reference data in dependency order and report what was written."""
    for client in clients:
        unit_of_work.clients.add(client)
    for household in households:
        unit_of_work.households.add(household)
    for benchmark in benchmarks:
        unit_of_work.benchmarks.add(benchmark)
    for instrument in instruments:
        unit_of_work.instruments.add(instrument)
    unit_of_work.flush()
    for account in accounts:
        unit_of_work.accounts.add(account)
    unit_of_work.flush()
    for portfolio in portfolios:
        unit_of_work.portfolios.add(portfolio)
    unit_of_work.flush()
    return {
        "clients": len(clients),
        "households": len(households),
        "benchmarks": len(benchmarks),
        "instruments": len(instruments),
        "accounts": len(accounts),
        "portfolios": len(portfolios),
    }
