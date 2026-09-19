"""Shared fixtures.

Unit tests run against an in-memory SQLite database so the suite stays fast and
hermetic. The integration tests use whatever ``MERIDIAN_DATABASE_URL`` points at,
which in CI is a real PostgreSQL service, so the same repository code is exercised
against both engines.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from meridian.config import Settings
from meridian.core import ISIN, AccountType, Ticker
from meridian.core.identifiers import CUSIP
from meridian.domain import (
    Account,
    Benchmark,
    Bond,
    Client,
    Equity,
    Fund,
    Household,
    InvestmentPolicy,
    Portfolio,
    SecurityIdentifiers,
    Transaction,
    build_trade,
)
from meridian.persistence import Database, UnitOfWork


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        reports_dir=tmp_path / "reports",
    )


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    database = Database(settings).create_all()
    yield database
    database.dispose()


@pytest.fixture
def session(database: Database) -> Iterator[Session]:
    with database.session() as session:
        yield session


@pytest.fixture
def unit_of_work(session: Session) -> UnitOfWork:
    return UnitOfWork(session)


@pytest.fixture
def postgres_database() -> Iterator[Database]:
    """A real PostgreSQL database, skipped unless one is configured."""
    url = os.environ.get("MERIDIAN_DATABASE_URL", "")
    if not url or url.startswith("sqlite"):
        pytest.skip("MERIDIAN_DATABASE_URL does not point at a server database")
    database = Database(Settings(database_url=url)).create_all()
    yield database
    database.dispose()


@pytest.fixture
def instruments() -> list[Equity | Fund | Bond]:
    return [
        Equity(
            instrument_id="AAPL",
            name="Apple Inc",
            currency="USD",
            identifiers=SecurityIdentifiers(
                isin=ISIN("US0378331005"), cusip=CUSIP("037833100"), ticker=Ticker("AAPL", "XNAS")
            ),
            country="US",
            exchange="XNAS",
            sector="Information Technology",
            issuer_id="APPLE",
        ),
        Equity(
            instrument_id="MSFT",
            name="Microsoft Corporation",
            currency="USD",
            identifiers=SecurityIdentifiers(isin=ISIN("US5949181045"), ticker=Ticker("MSFT", "XNAS")),
            country="US",
            exchange="XNAS",
            sector="Information Technology",
            issuer_id="MICROSOFT",
        ),
        Equity(
            instrument_id="SAP",
            name="SAP SE",
            currency="EUR",
            identifiers=SecurityIdentifiers(isin=ISIN("DE000BAY0017"), ticker=Ticker("SAP", "XETR")),
            country="DE",
            exchange="XETR",
            sector="Information Technology",
            calendar="TARGET",
            issuer_id="SAP",
        ),
        Fund(
            instrument_id="IVV",
            name="iShares Core S&P 500 ETF",
            currency="USD",
            identifiers=SecurityIdentifiers(ticker=Ticker("IVV", "ARCX")),
            expense_ratio="0.0003",
            benchmark_id="SPX",
            country="US",
        ),
        Bond(
            instrument_id="T-2032",
            name="US Treasury 2.5% 2032",
            currency="USD",
            identifiers=SecurityIdentifiers(ticker=Ticker("T2032")),
            coupon="0.025",
            issue_date=date(2022, 5, 15),
            maturity=date(2032, 5, 15),
            face_value=1000,
        ),
    ]


@pytest.fixture
def benchmark() -> Benchmark:
    return Benchmark(benchmark_id="SPX", name="S&P 500", currency="USD", description="US large cap")


@pytest.fixture
def client() -> Client:
    return Client(client_id="C1", name="Karimov Family", domicile="AZ", tax_residence="GB")


@pytest.fixture
def household() -> Household:
    return Household(household_id="H1", name="Karimov Household", base_currency="USD")


@pytest.fixture
def account() -> Account:
    return Account(
        account_id="A1",
        name="Karimov Taxable",
        account_type=AccountType.TAXABLE,
        base_currency="USD",
        household_id="H1",
        client_id="C1",
        custodian="Schwab",
        opened=date(2023, 1, 5),
    )


@pytest.fixture
def portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id="P1",
        name="Global Balanced",
        base_currency="USD",
        account_id="A1",
        benchmark_id="SPX",
        strategy="balanced",
        inception=date(2023, 1, 10),
        policy=InvestmentPolicy(target_equity_weight=Decimal("0.6"), max_single_issuer_weight=Decimal("0.05")),
    )


@pytest.fixture
def transactions() -> list[Transaction]:
    return [
        build_trade(
            transaction_id="T1",
            portfolio_id="P1",
            instrument_id="AAPL",
            trade_date=date(2026, 1, 5),
            quantity=100,
            price="185.50",
            currency="USD",
            fees="4.95",
            settlement_date=date(2026, 1, 6),
        ),
        build_trade(
            transaction_id="T2",
            portfolio_id="P1",
            instrument_id="MSFT",
            trade_date=date(2026, 2, 10),
            quantity=40,
            price="410.25",
            currency="USD",
            fees="4.95",
        ),
        build_trade(
            transaction_id="T3",
            portfolio_id="P1",
            instrument_id="AAPL",
            trade_date=date(2026, 6, 15),
            quantity=30,
            price="205.10",
            currency="USD",
            buy=False,
            fees="4.95",
        ),
    ]
