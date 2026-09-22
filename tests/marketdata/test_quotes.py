"""Quotes record what a vendor sent, however wrong; only unrecordable input is refused."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from meridian.core.exceptions import ValidationError
from meridian.marketdata.quotes import FxQuote, MarketDataset, Quote


def quote(day: int, close: str, source: str = "a", **extra) -> Quote:
    return Quote(
        instrument_id="X", day=date(2026, 5, day), close=Decimal(close), currency="usd", source=source, **extra
    )


def test_a_bad_price_is_recorded_not_rejected():
    zero = quote(4, "0")
    assert zero.close == 0
    crossed = quote(4, "10", bid=Decimal("10.2"), ask=Decimal("10.1"))
    assert crossed.is_crossed


def test_unrecordable_input_is_refused():
    with pytest.raises(ValidationError):
        Quote(instrument_id=" ", day=date(2026, 5, 4), close=Decimal(1), currency="USD")
    with pytest.raises(ValidationError):
        Quote(instrument_id="X", day=date(2026, 5, 4), close="abc", currency="USD")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Quote(instrument_id="X", day=date(2026, 5, 4), close=Decimal(1), currency="USD", volume=-1)


def test_mid_and_spread():
    item = quote(4, "100", bid=Decimal("99.95"), ask=Decimal("100.05"))
    assert item.currency == "USD"
    assert item.mid == Decimal("100.00")
    assert item.spread_bps == pytest.approx(10.0)
    assert quote(4, "100").spread_bps is None


def test_with_close_changes_one_field_and_keeps_the_rest():
    item = quote(4, "100", bid=Decimal("99"), ask=Decimal("101"), volume=10)
    changed = item.with_close("105", day=date(2026, 5, 5))
    assert changed.close == Decimal("105")
    assert changed.day == date(2026, 5, 5)
    assert (changed.bid, changed.ask, changed.volume) == (item.bid, item.ask, item.volume)


def test_fx_quote_normalises_and_refuses_a_pair_of_one_currency():
    rate = FxQuote(base="eur", quote="usd", day=date(2026, 5, 4), rate=Decimal("1.08"))
    assert rate.pair == "EURUSD"
    with pytest.raises(ValidationError):
        FxQuote(base="USD", quote="usd", day=date(2026, 5, 4), rate=Decimal(1))


def test_dataset_indexes_by_instrument_source_and_day():
    dataset = MarketDataset.from_records(
        [quote(5, "11", "b"), quote(4, "10", "a"), quote(5, "12", "a")],
        [FxQuote(base="EUR", quote="USD", day=date(2026, 5, 4), rate=Decimal("1.1"), source="fx")],
    )
    assert dataset.instruments == ("X",)
    assert dataset.pairs == ("EURUSD",)
    assert dataset.sources == ("a", "b", "fx")
    assert len(dataset) == 4
    assert [item.close for item in dataset.for_instrument("X", source="a")] == [Decimal("10"), Decimal("12")]
    assert dataset.close_series("X", source="b").days == (date(2026, 5, 5),)
    assert dataset.close_series("X")[date(2026, 5, 5)] == Decimal("12")  # first record per day: source "a"
    assert dataset.fx_series("eurusd")[date(2026, 5, 4)] == Decimal("1.1")
    assert dataset.currency_of("X") == "USD"
    assert dataset.currency_of("Y") is None
    assert dataset.days() == (date(2026, 5, 4), date(2026, 5, 5))


def test_restrict_keeps_fx_and_the_named_instruments():
    dataset = MarketDataset.from_records(
        [quote(4, "10"), Quote(instrument_id="Y", day=date(2026, 5, 4), close=Decimal(1), currency="USD")],
        [FxQuote(base="EUR", quote="USD", day=date(2026, 5, 4), rate=Decimal("1.1"))],
    )
    restricted = dataset.restrict(["Y"])
    assert restricted.instruments == ("Y",)
    assert restricted.pairs == ("EURUSD",)
