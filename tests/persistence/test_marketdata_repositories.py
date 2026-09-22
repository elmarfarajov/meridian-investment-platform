"""The market data tables: observations answer 'as known at' in SQL exactly as the reference store does."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from meridian.core.exceptions import EntityNotFoundError, ValidationError
from meridian.domain.corporate_actions import (
    CashDividend,
    RightsIssue,
    SpinOff,
    StockMerger,
    SymbolChange,
    dividend,
    split,
)
from meridian.marketdata.bitemporal import BitemporalStore
from meridian.marketdata.quotes import Quote
from meridian.persistence import UnitOfWork, seed_reference_data
from meridian.persistence.marketdata_mappers import corporate_action_to_row, row_to_corporate_action
from meridian.quality.engine import QualityReport
from meridian.quality.findings import Dimension, Finding, Severity
from meridian.refdata import CrossReference, IdentifierScheme, XrefEntry, demo_cross_reference


@pytest.fixture
def uow(unit_of_work: UnitOfWork, instruments, benchmark, client, household, account, portfolio) -> UnitOfWork:
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


def at(day: int, hour: int = 22) -> datetime:
    return datetime(2026, 3, day, hour, tzinfo=timezone.utc)


def quote(day: int, close: str, source: str = "vendor") -> Quote:
    return Quote(instrument_id="AAPL", day=date(2026, 3, day), close=Decimal(close), currency="USD", source=source)


# ---------------------------------------------------------------------------- observations
def test_observations_answer_as_known_at_like_the_reference_store(uow: UnitOfWork):
    records = [
        (quote(2, "100.00"), at(2)),
        (quote(3, "101.00"), at(3)),
        (quote(4, "150.00"), at(4)),
        (quote(4, "102.00"), at(5, 9)),  # the correction
        (quote(5, "103.00"), at(5)),
    ]
    store = BitemporalStore()
    for item, moment in records:
        uow.observations.record(item, moment, run_id="r1")
        store.record("AAPL", item.day, item.close, moment)
    uow.flush()

    for known_at in (at(2, 23), at(4, 23), at(5, 10), None):
        assert uow.observations.as_known_at("AAPL", known_at).values == store.as_known_at("AAPL", known_at).values
    assert uow.observations.as_known_at("AAPL", at(4, 23))[date(2026, 3, 4)] == Decimal("150.00")
    assert uow.observations.as_known_at("AAPL")[date(2026, 3, 4)] == Decimal("102.00")


def test_versions_sources_and_counts(uow: UnitOfWork):
    uow.observations.record_many([quote(2, "100.00"), quote(2, "100.02", "exchange")], at(2))
    uow.observations.record(quote(2, "100.01"), at(3))
    uow.flush()
    versions = uow.observations.versions("AAPL", date(2026, 3, 2), source="vendor")
    assert [price for _, _, price in versions] == [Decimal("100.00"), Decimal("100.01")]
    assert uow.observations.count() == 3
    assert uow.observations.count("AAPL") == 3
    assert list(uow.observations.sources()) == ["exchange", "vendor"]
    only_exchange = uow.observations.as_known_at("AAPL", source="exchange")
    assert only_exchange.values == (Decimal("100.02"),)


def test_resending_the_same_observation_is_idempotent(uow: UnitOfWork):
    uow.observations.record(quote(2, "100.00"), at(2))
    uow.observations.record(quote(2, "100.00"), at(2))
    uow.flush()
    assert uow.observations.count() == 1


def test_window_filters_on_observations(uow: UnitOfWork):
    uow.observations.record_many([quote(day, str(100 + day)) for day in range(2, 7)], at(9))
    uow.flush()
    window = uow.observations.as_known_at("AAPL", start=date(2026, 3, 3), end=date(2026, 3, 4))
    assert window.days == (date(2026, 3, 3), date(2026, 3, 4))


# ---------------------------------------------------------------------------- corporate actions
ACTIONS = [
    split("S1", "AAPL", date(2026, 6, 10), 4),
    dividend("D1", "AAPL", date(2026, 5, 11), "0.26", "USD", pay_date=date(2026, 5, 14), withholding_rate="0.15"),
    SpinOff(
        action_id="SO1",
        instrument_id="MSFT",
        ex_date=date(2026, 7, 1),
        child_instrument_id="MSFT-CHILD",
        ratio=Decimal("0.25"),
        cost_allocation=Decimal("0.0725"),
    ),
    RightsIssue(
        action_id="R1",
        instrument_id="SAP",
        ex_date=date(2026, 8, 3),
        ratio=Decimal("0.2"),
        subscription_price=Decimal("88.5"),
    ),
    StockMerger(
        action_id="M1",
        instrument_id="MSFT",
        ex_date=date(2026, 9, 1),
        acquirer_instrument_id="AAPL",
        ratio=Decimal("1.5"),
        cash_per_share=Decimal("12.25"),
    ),
    SymbolChange(action_id="N1", instrument_id="IVV", ex_date=date(2026, 4, 1), old_symbol="IVV", new_symbol="IVVX"),
]


@pytest.mark.parametrize("action", ACTIONS, ids=lambda action: action.action_type.value)
def test_every_action_type_round_trips_exactly(action):
    assert row_to_corporate_action(corporate_action_to_row(action)) == action


def test_corporate_action_repository(uow: UnitOfWork):
    assert uow.corporate_actions.add_all(ACTIONS) == len(ACTIONS)
    uow.flush()
    stored = uow.corporate_actions.get("D1")
    assert isinstance(stored, CashDividend)
    assert stored.amount == Decimal("0.26")
    assert stored.withholding_rate == Decimal("0.15")
    assert [item.action_id for item in uow.corporate_actions.for_instrument("AAPL")] == ["D1", "S1"]
    assert [item.action_id for item in uow.corporate_actions.for_instrument("AAPL", start=date(2026, 6, 1))] == ["S1"]
    assert [item.action_id for item in uow.corporate_actions.list(action_type="spin_off")] == ["SO1"]
    assert len(uow.corporate_actions.list(start=date(2026, 7, 1), end=date(2026, 8, 31))) == 2
    assert uow.corporate_actions.count() == len(ACTIONS)
    with pytest.raises(EntityNotFoundError):
        uow.corporate_actions.get("NOPE")


def test_an_unknown_action_type_in_the_database_is_reported():
    row = corporate_action_to_row(ACTIONS[0])
    row.action_type = "reverse_takeover"
    with pytest.raises(ValidationError, match="unknown corporate action type"):
        row_to_corporate_action(row)


# ---------------------------------------------------------------------------- cross-reference
def test_the_cross_reference_round_trips_and_resolves_in_sql(uow: UnitOfWork):
    reference = demo_cross_reference()
    assert uow.xref.save(reference) == len(reference)
    uow.flush()
    loaded = uow.xref.load()
    assert len(loaded) == len(reference)
    assert loaded.resolve("ticker", "FB", date(2021, 1, 4)) == "US-META"
    assert uow.xref.resolve(IdentifierScheme.TICKER, "fb", date(2021, 1, 4)) == "US-META"
    assert uow.xref.resolve("ticker", "FB", date(2022, 6, 9)) is None
    assert uow.xref.resolve("ticker", "MRDN", date(2024, 1, 2)) == "DEMO-NEWCO"


def test_saving_replaces_the_previous_cross_reference(uow: UnitOfWork):
    uow.xref.save(demo_cross_reference())
    uow.flush()
    small = CrossReference([XrefEntry(IdentifierScheme.TICKER, "ZZZ", "Z", date(2020, 1, 1))])
    assert uow.xref.save(small) == 1
    uow.flush()
    assert len(uow.xref.load()) == 1


# ---------------------------------------------------------------------------- quality results
def finding(rule: str, day: int, severity: Severity = Severity.ERROR) -> Finding:
    return Finding(
        rule=rule,
        key="AAPL",
        day=date(2026, 3, day),
        severity=severity,
        dimension=Dimension.ACCURACY,
        message=f"{rule} on the {day}th",
        source="vendor",
        observed=0.25,
        score=12.5,
    )


def test_a_quality_run_and_its_findings_are_stored_and_read_back(uow: UnitOfWork):
    report = QualityReport(
        run_id="run-1",
        as_of=date(2026, 3, 31),
        findings=[finding("robust_outlier", 4), finding("stale_mark", 9, Severity.WARNING)],
        scores=[],
    )
    assert uow.quality.save(report) == 2
    uow.flush()
    run = uow.quality.latest_run()
    assert run is not None and run.run_id == "run-1"
    assert run.blocking_count == 1
    stored = uow.quality.findings("run-1")
    assert [item.rule for item in stored] == ["robust_outlier", "stale_mark"]
    assert stored[0].score == 12.5
    assert stored[0] == report.findings[0]
    assert uow.quality.findings("run-1", severity="warning")[0].rule == "stale_mark"
    assert uow.quality.findings("run-1", key="MSFT") == []
    assert len(uow.quality.runs()) == 1


def test_saving_a_run_twice_replaces_it(uow: UnitOfWork):
    report = QualityReport(run_id="run-2", as_of=date(2026, 3, 31), findings=[finding("x", 4)], scores=[])
    uow.quality.save(report)
    uow.flush()
    report.findings.append(finding("y", 5))
    uow.quality.save(report)
    uow.flush()
    assert len(uow.quality.findings("run-2")) == 2
    assert len(uow.quality.runs()) == 1


def test_timezones_are_normalised_on_the_way_in(uow: UnitOfWork):
    local = datetime(2026, 3, 2, 23, 30, tzinfo=timezone(timedelta(hours=1)))  # 22:30 UTC
    uow.observations.record(quote(2, "100.00"), local)
    uow.flush()
    assert len(uow.observations.as_known_at("AAPL", at(2, 22))) == 0
    assert len(uow.observations.as_known_at("AAPL", at(2, 23))) == 1
