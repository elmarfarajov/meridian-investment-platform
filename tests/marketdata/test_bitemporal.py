"""Point-in-time storage: corrections are new records, and any past state can be rebuilt."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from meridian.core.exceptions import ValidationError
from meridian.marketdata.bitemporal import BitemporalStore, Observation, as_utc, end_of_day, lookahead_error
from meridian.marketdata.series import TimeSeries

KEY = "US-AAPL:close"


def moment(day: int, hour: int = 22) -> datetime:
    return datetime(2026, 3, day, hour, 0, tzinfo=timezone.utc)


@pytest.fixture
def store() -> BitemporalStore:
    store = BitemporalStore()
    store.record(KEY, date(2026, 3, 2), "100.00", moment(2), source="vendor")
    store.record(KEY, date(2026, 3, 3), "101.00", moment(3), source="vendor")
    store.record(KEY, date(2026, 3, 4), "150.00", moment(4), source="vendor")  # a bad print
    store.record(KEY, date(2026, 3, 4), "102.00", moment(5, 9), source="vendor", note="corrected")
    store.record(KEY, date(2026, 3, 5), "103.00", moment(5), source="vendor")
    return store


def test_latest_knowledge_sees_the_correction(store: BitemporalStore):
    assert store.value(KEY, date(2026, 3, 4)) == Decimal("102.00")
    assert store.as_known_at(KEY)[date(2026, 3, 4)] == Decimal("102.00")


def test_the_past_state_of_knowledge_is_reconstructed_exactly(store: BitemporalStore):
    evening_of_the_fourth = moment(4, 23)
    series = store.as_known_at(KEY, evening_of_the_fourth)
    assert series[date(2026, 3, 4)] == Decimal("150.00")
    assert date(2026, 3, 5) not in series  # not yet published at that moment


def test_nothing_is_known_before_the_first_record(store: BitemporalStore):
    assert len(store.as_known_at(KEY, moment(1))) == 0
    assert store.value(KEY, date(2026, 3, 2), known_at=moment(2, 21)) is None


def test_versions_are_in_the_order_they_were_learned(store: BitemporalStore):
    versions = store.versions(KEY, date(2026, 3, 4))
    assert [item.value for item in versions] == [Decimal("150.00"), Decimal("102.00")]
    assert versions[1].note == "corrected"


def test_revisions_report_what_changed_and_how_late(store: BitemporalStore):
    (revision,) = store.revisions()
    assert revision.value_date == date(2026, 3, 4)
    assert revision.change == Decimal("-48.00")
    assert revision.change_bps == pytest.approx(-3200)
    assert revision.delay_days == 1
    assert revision.versions == 2


def test_first_published_is_what_a_live_system_saw(store: BitemporalStore):
    first = store.first_published(KEY)
    assert first[date(2026, 3, 4)] == Decimal("150.00")


def test_lookahead_error_measures_what_a_backtest_would_have_cheated_with(store: BitemporalStore):
    errors = dict(lookahead_error(store, KEY, moment(4, 23)))
    assert errors[date(2026, 3, 4)] == pytest.approx((102 / 150 - 1) * 10_000)
    assert errors[date(2026, 3, 2)] == 0


def test_an_exact_resend_is_idempotent(store: BitemporalStore):
    before = len(store)
    store.record(KEY, date(2026, 3, 2), "100.00", moment(2))
    assert len(store) == before


def test_two_values_at_the_same_instant_are_refused(store: BitemporalStore):
    with pytest.raises(ValidationError, match="same instant"):
        store.record(KEY, date(2026, 3, 2), "99.00", moment(2))


def test_a_value_cannot_be_known_before_its_own_date():
    with pytest.raises(ValidationError, match="cannot be known"):
        Observation(recorded_at=moment(1), value_date=date(2026, 3, 2), value=Decimal(1), key=KEY)


def test_knowledge_times_and_keys(store: BitemporalStore):
    assert store.keys() == (KEY,)
    assert len(store.knowledge_times(KEY)) == 5


def test_naive_datetimes_are_treated_as_utc():
    naive = datetime(2026, 3, 2, 22, 0)
    assert as_utc(naive) == datetime(2026, 3, 2, 22, 0, tzinfo=timezone.utc)
    shifted = datetime(2026, 3, 2, 23, 0, tzinfo=timezone(timedelta(hours=1)))
    assert as_utc(shifted) == datetime(2026, 3, 2, 22, 0, tzinfo=timezone.utc)


def test_record_series_with_a_publication_lag():
    store = BitemporalStore()
    series = TimeSeries([(date(2026, 3, 2), 1), (date(2026, 3, 3), 2)])
    assert store.record_series("k", series, lag_days=1) == 2
    assert len(store.as_known_at("k", end_of_day(date(2026, 3, 2)))) == 0
    assert len(store.as_known_at("k", end_of_day(date(2026, 3, 3)))) == 1


def test_window_filters(store: BitemporalStore):
    part = store.as_known_at(KEY, start=date(2026, 3, 3), end=date(2026, 3, 4))
    assert part.days == (date(2026, 3, 3), date(2026, 3, 4))
