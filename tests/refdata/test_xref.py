"""Identifier cross-reference: every lookup carries a date, and ambiguity is refused."""

from __future__ import annotations

from datetime import date

import pytest

from meridian.core.exceptions import ValidationError
from meridian.domain.corporate_actions import SymbolChange
from meridian.refdata import (
    OPEN_END,
    CrossReference,
    IdentifierScheme,
    XrefConflict,
    XrefEntry,
    demo_cross_reference,
    xref_from_instruments,
)
from meridian.seed import demo_instruments


def ticker(value: str, instrument: str, start: date, end: date = OPEN_END) -> XrefEntry:
    return XrefEntry(IdentifierScheme.TICKER, value, instrument, start, end)


def test_a_renamed_ticker_resolves_by_date():
    reference = demo_cross_reference()
    assert reference.resolve("ticker", "FB", date(2021, 6, 1)) == "US-META"
    assert reference.resolve("ticker", "FB", date(2022, 6, 8)) == "US-META"
    assert reference.resolve("ticker", "FB", date(2022, 6, 9)) is None
    assert reference.resolve("ticker", "META", date(2022, 6, 9)) == "US-META"
    assert reference.resolve("ticker", "META", date(2022, 6, 8)) is None


def test_a_reused_ticker_points_at_different_companies_in_different_years():
    reference = demo_cross_reference()
    assert reference.resolve("ticker", "MRDN", date(2018, 1, 2)) == "DEMO-OLDCO"
    assert reference.resolve("ticker", "MRDN", date(2022, 1, 3)) is None  # nobody held it
    assert reference.resolve("ticker", "MRDN", date(2024, 1, 2)) == "DEMO-NEWCO"
    assert reference.reused() == {(IdentifierScheme.TICKER, "MRDN"): ("DEMO-OLDCO", "DEMO-NEWCO")}


def test_an_isin_change_on_redomicile_keeps_one_instrument():
    reference = demo_cross_reference()
    before = reference.identifiers("DEMO-NEWCO", date(2024, 1, 2))
    after = reference.identifiers("DEMO-NEWCO", date(2026, 1, 2))
    assert before[IdentifierScheme.ISIN].startswith("US")
    assert after[IdentifierScheme.ISIN].startswith("IE")
    assert before[IdentifierScheme.TICKER] == after[IdentifierScheme.TICKER] == "MRDN"


def test_one_identifier_cannot_mean_two_instruments_at_once():
    reference = CrossReference([ticker("ABC", "ONE", date(2020, 1, 1))])
    with pytest.raises(XrefConflict, match="already identifies ONE"):
        reference.add(ticker("ABC", "TWO", date(2024, 1, 1)))


def test_one_instrument_cannot_hold_two_isins_at_once():
    reference = CrossReference([XrefEntry(IdentifierScheme.ISIN, "US0378331005", "AAPL", date(2020, 1, 1))])
    with pytest.raises(XrefConflict, match="already has isin"):
        reference.add(XrefEntry(IdentifierScheme.ISIN, "US5949181045", "AAPL", date(2021, 1, 1)))


def test_closing_then_reusing_is_allowed():
    reference = CrossReference([ticker("ABC", "ONE", date(2020, 1, 1))])
    reference.close(IdentifierScheme.TICKER, "ABC", "ONE", date(2022, 1, 1))
    reference.add(ticker("ABC", "TWO", date(2023, 1, 1)))
    assert [entry.instrument_id for entry in reference.history("ticker", "abc")] == ["ONE", "TWO"]
    with pytest.raises(ValidationError, match="no open"):
        reference.close(IdentifierScheme.TICKER, "ABC", "ONE", date(2025, 1, 1))


def test_rename_applies_a_symbol_change():
    reference = CrossReference([ticker("OLD", "X", date(2020, 1, 1))])
    change = SymbolChange(
        action_id="N", instrument_id="X", ex_date=date(2024, 3, 4), old_symbol="OLD", new_symbol="NEW"
    )
    reference.rename(change)
    assert reference.resolve("ticker", "OLD", date(2024, 3, 1)) == "X"
    assert reference.resolve("ticker", "NEW", date(2024, 3, 4)) == "X"


def test_check_digit_schemes_are_validated_on_entry():
    with pytest.raises(ValidationError, match="not a valid ISIN"):
        XrefEntry(IdentifierScheme.ISIN, "US0378331006", "AAPL", date(2020, 1, 1))
    with pytest.raises(ValidationError, match="must end after"):
        ticker("X", "Y", date(2020, 1, 2), date(2020, 1, 1))
    with pytest.raises(ValidationError):
        ticker("  ", "Y", date(2020, 1, 2))


def test_resolve_any_tries_every_scheme():
    reference = demo_cross_reference()
    assert reference.resolve_any("037833100", date(2025, 1, 2)) == [(IdentifierScheme.CUSIP, "US-AAPL")]
    assert reference.resolve_any("UNKNOWN", date(2025, 1, 2)) == []


def test_describe_and_open_intervals():
    entry = ticker("ABC", "ONE", date(2020, 1, 1), date(2021, 1, 1))
    assert entry.describe() == "ticker:ABC -> ONE [2020-01-01 .. 2020-12-31]"
    assert ticker("ABC", "ONE", date(2020, 1, 1)).is_open


def test_seeding_from_the_book_uses_ticker_symbols_without_venues():
    reference = xref_from_instruments(demo_instruments(), valid_from=date(2024, 1, 2))
    assert reference.resolve("ticker", "AAPL", date(2025, 1, 2)) == "US-AAPL"
    assert reference.resolve("isin", "GB0002634946", date(2025, 1, 2)) == "GB-BAE"
    assert reference.resolve("sedol", "0263494", date(2025, 1, 2)) == "GB-BAE"
    assert reference.resolve("ticker", "AAPL", date(2023, 12, 29)) is None
    assert len(reference) == len(reference.entries())
