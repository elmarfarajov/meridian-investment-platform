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


def test_bitemporal_observations_on_postgres(pg_unit_of_work: UnitOfWork):
    """timestamptz comparisons are what SQLite cannot prove: a correction must not leak into the past."""
    from datetime import datetime, timezone

    from meridian.marketdata.quotes import Quote

    def quote(close: str) -> Quote:
        return Quote(instrument_id="AAPL", day=date(2026, 3, 4), close=Decimal(close), currency="USD", source="v")

    first = datetime(2026, 3, 4, 22, 0, tzinfo=timezone.utc)
    corrected = datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc)
    pg_unit_of_work.observations.record(quote("150.00"), first)
    pg_unit_of_work.observations.record(quote("102.00"), corrected)
    pg_unit_of_work.flush()
    then = pg_unit_of_work.observations.as_known_at("AAPL", datetime(2026, 3, 4, 23, 0, tzinfo=timezone.utc))
    assert then[date(2026, 3, 4)] == Decimal("150.00")
    assert pg_unit_of_work.observations.as_known_at("AAPL")[date(2026, 3, 4)] == Decimal("102.00")


def test_corporate_actions_and_quality_runs_on_postgres(pg_unit_of_work: UnitOfWork):
    from meridian.domain.corporate_actions import dividend, split
    from meridian.quality.engine import QualityReport
    from meridian.quality.findings import Dimension, Finding, Severity

    pg_unit_of_work.corporate_actions.add_all(
        [split("S1", "AAPL", date(2026, 6, 10), 4), dividend("D1", "AAPL", date(2026, 5, 11), "0.2475", "USD")]
    )
    pg_unit_of_work.flush()
    assert pg_unit_of_work.corporate_actions.get("D1").amount == Decimal("0.2475")  # type: ignore[attr-defined]
    report = QualityReport(
        run_id="pg-run",
        as_of=date(2026, 3, 31),
        findings=[
            Finding(
                rule="stale_mark",
                key="AAPL",
                day=date(2026, 3, 4),
                severity=Severity.ERROR,
                dimension=Dimension.TIMELINESS,
                message="stale",
                observed=5.0,
            )
        ],
        scores=[],
    )
    pg_unit_of_work.quality.save(report)
    pg_unit_of_work.flush()
    assert [item.rule for item in pg_unit_of_work.quality.findings("pg-run")] == ["stale_mark"]


def test_identifier_xref_on_postgres(pg_unit_of_work: UnitOfWork):
    from meridian.refdata import demo_cross_reference

    pg_unit_of_work.xref.save(demo_cross_reference())
    pg_unit_of_work.flush()
    assert pg_unit_of_work.xref.resolve("ticker", "FB", date(2021, 1, 4)) == "US-META"
    assert pg_unit_of_work.xref.resolve("ticker", "FB", date(2023, 1, 4)) is None


def test_the_book_of_record_on_postgres(pg_session: Session):
    """The demonstration book persisted to PostgreSQL: the SQL trial balance equals the ledger's."""
    from meridian.services.accounting_run import run_demo_accounting
    from meridian.services.demo_accounting import PORTFOLIO_ID, build_demo_accounting

    demo = build_demo_accounting()
    unit_of_work = UnitOfWork(pg_session)
    result = run_demo_accounting(demo, unit_of_work)
    assert result.passed
    in_sql = {line.account.code: line.balance for line in unit_of_work.ledger.trial_balance(PORTFOLIO_ID).lines}
    in_memory = {line.account.code: line.balance for line in demo.book.ledger.trial_balance().lines}
    assert set(in_sql) == set(in_memory)
    for code, balance in in_memory.items():
        assert abs(in_sql[code] - balance) < Decimal("1e-6"), code
    lots = unit_of_work.tax_lots.open_lots(PORTFOLIO_ID)
    assert any(lot.wash_sale_adjustment for lot in lots)
    assert len(unit_of_work.valuations.nav_series(PORTFOLIO_ID)) == len(demo.valuations)
