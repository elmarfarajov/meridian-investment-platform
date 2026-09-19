"""Integration tests against a real server database.

CI runs ``alembic upgrade head`` against a PostgreSQL service container and then
``pytest -m integration``. These tests prove the parts SQLite cannot: enforced
foreign keys on a server engine, NUMERIC round-tripping at full scale, and that
repository queries behave identically on both dialects. Every test rolls back, so
the database is left exactly as it was found.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meridian.persistence import Database, UnitOfWork, seed_reference_data
from meridian.persistence.models import TransactionRow

pytestmark = pytest.mark.integration


@pytest.fixture
def pg_session(postgres_database: Database) -> Iterator[Session]:
    """A session whose work is always rolled back, so tests never leave residue."""
    session = postgres_database.session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def pg_unit_of_work(pg_session: Session, instruments, benchmark, client, household, account, portfolio) -> UnitOfWork:
    unit_of_work = UnitOfWork(pg_session)
    seed_reference_data(
        unit_of_work,
        instruments=instruments,
        benchmarks=[benchmark],
        clients=[client],
        households=[household],
        accounts=[account],
        portfolios=[portfolio],
    )
    return unit_of_work


def test_reference_data_round_trips_on_postgres(pg_unit_of_work: UnitOfWork):
    assert pg_unit_of_work.instruments.get("AAPL").name == "Apple Inc"
    assert pg_unit_of_work.portfolios.get("P1").base_currency.code == "USD"
    assert [item.portfolio_id for item in pg_unit_of_work.portfolios.for_household("H1")] == ["P1"]


def test_numeric_columns_keep_full_scale(pg_unit_of_work: UnitOfWork):
    """PostgreSQL NUMERIC must return Decimal, not float, or cents go missing."""
    pg_unit_of_work.prices.upsert("AAPL", date(2026, 9, 18), Decimal("227.4012345678"), "USD")
    pg_unit_of_work.flush()
    stored = pg_unit_of_work.prices.latest("AAPL", date(2026, 9, 18))
    assert isinstance(stored, Decimal)
    assert stored == Decimal("227.4012345678")


def test_foreign_keys_are_enforced(pg_unit_of_work: UnitOfWork, pg_session: Session):
    pg_session.add(
        TransactionRow(
            transaction_id="BAD",
            portfolio_id="DOES-NOT-EXIST",
            instrument_id="AAPL",
            transaction_type="buy",
            trade_date=date(2026, 9, 18),
            quantity=Decimal(1),
            price=Decimal(1),
            fees=Decimal(0),
            taxes=Decimal(0),
            currency="USD",
            fx_rate=Decimal(1),
        )
    )
    with pytest.raises(IntegrityError):
        pg_session.flush()


def test_transaction_ordering_matches_sqlite(pg_unit_of_work: UnitOfWork, transactions):
    pg_unit_of_work.transactions.add_all(transactions)
    pg_unit_of_work.flush()
    stored = pg_unit_of_work.transactions.for_portfolio("P1")
    assert [item.transaction_id for item in stored] == ["T1", "T2", "T3"]
    assert stored[0].cash_impact.amount == Decimal("-18554.95")


def test_the_migrated_database_is_the_one_under_test(postgres_database: Database):
    assert postgres_database.dialect == "postgresql"
