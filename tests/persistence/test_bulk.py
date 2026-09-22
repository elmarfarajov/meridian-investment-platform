"""Bulk upsert: merge semantics at batch speed, on either dialect."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from meridian.marketdata.quotes import Quote
from meridian.persistence import UnitOfWork, seed_reference_data
from meridian.persistence.bulk import bulk_upsert, insert_missing
from meridian.persistence.models import FxRateRow


def test_prices_upsert_many_inserts_then_updates(unit_of_work: UnitOfWork, instruments):
    seed_reference_data(unit_of_work, instruments=instruments)
    marks = [("AAPL", date(2026, 3, day), Decimal(f"{100 + day}.00"), "usd", "golden:exchange") for day in (2, 3, 4)]
    assert unit_of_work.prices.upsert_many(marks) == 3
    corrected = [("AAPL", date(2026, 3, 4), Decimal("99.50"), "USD", "golden:vendor-b")]
    assert unit_of_work.prices.upsert_many(corrected) == 1
    unit_of_work.flush()
    series = dict(unit_of_work.prices.series("AAPL"))
    assert series[date(2026, 3, 4)] == Decimal("99.50")
    assert len(series) == 3


def test_duplicate_keys_in_one_batch_keep_the_last_row(session):
    rows = [
        {"base_currency": "EUR", "quote_currency": "USD", "rate_date": date(2026, 3, 2), "rate": Decimal("1.1")},
        {"base_currency": "EUR", "quote_currency": "USD", "rate_date": date(2026, 3, 2), "rate": Decimal("1.2")},
    ]
    assert bulk_upsert(session, FxRateRow, rows) == (1, 0)
    session.flush()
    assert session.get(FxRateRow, ("EUR", "USD", date(2026, 3, 2))).rate == Decimal("1.2")
    assert bulk_upsert(session, FxRateRow, []) == (0, 0)


def test_fx_upsert_many(unit_of_work: UnitOfWork):
    rates = [("eur", "usd", date(2026, 3, day), Decimal("1.08"), "wm") for day in (2, 3)]
    assert unit_of_work.fx_rates.upsert_many(rates) == 2
    assert unit_of_work.fx_rates.upsert_many(rates) == 2  # both are updates the second time
    unit_of_work.flush()
    assert len(unit_of_work.fx_rates.series("EUR", "USD")) == 2


def test_observations_resent_at_the_same_moment_are_skipped(unit_of_work: UnitOfWork, instruments):
    seed_reference_data(unit_of_work, instruments=instruments)
    moment = datetime(2026, 3, 2, 22, tzinfo=timezone.utc)
    quotes = [
        Quote(instrument_id="AAPL", day=date(2026, 3, day), close=Decimal("100"), currency="USD", source="v")
        for day in (2, 3)
    ]
    assert unit_of_work.observations.record_many(quotes, moment) == 2
    assert unit_of_work.observations.record_many(quotes, moment) == 0
    assert unit_of_work.observations.record_many(quotes, moment + timedelta(hours=1)) == 2  # new knowledge time
    assert unit_of_work.observations.count() == 4


def test_insert_missing_compares_timezones_the_way_the_database_returns_them(unit_of_work: UnitOfWork, instruments):
    seed_reference_data(unit_of_work, instruments=instruments)
    quote = Quote(instrument_id="AAPL", day=date(2026, 3, 2), close=Decimal("100"), currency="USD", source="v")
    utc = datetime(2026, 3, 2, 22, tzinfo=timezone.utc)
    unit_of_work.observations.record_many([quote], utc)
    same_instant_elsewhere = utc.astimezone(timezone(timedelta(hours=4)))
    assert unit_of_work.observations.record_many([quote], same_instant_elsewhere) == 0
    assert insert_missing(unit_of_work.session, FxRateRow, []) == 0
