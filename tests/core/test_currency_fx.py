from datetime import date
from decimal import Decimal

import pytest

from meridian.core import (
    FxRate,
    FxTable,
    Money,
    RateNotFoundError,
    UnknownCurrencyError,
    ValidationError,
    all_currencies,
    get_currency,
)
from meridian.core.currency import Currency, register_currency


def test_currency_lookup_is_case_insensitive():
    assert get_currency("usd").code == "USD"
    assert get_currency(get_currency("EUR")).code == "EUR"
    with pytest.raises(UnknownCurrencyError):
        get_currency("XYZ")


def test_minor_units_drive_precision():
    assert get_currency("USD").precision == Decimal("0.01")
    assert get_currency("JPY").precision == Decimal("1")
    assert get_currency("KWD").precision == Decimal("0.001")


def test_registry_is_sane():
    codes = [currency.code for currency in all_currencies()]
    assert codes == sorted(codes)
    assert "AZN" in codes
    assert len(codes) >= 20


def test_registering_a_currency():
    ghost = register_currency(Currency("PLN", "Zloty", 2, "985"))
    assert get_currency("PLN") is ghost


def test_malformed_currency_definitions_are_rejected():
    with pytest.raises(UnknownCurrencyError):
        Currency("usd", "US Dollar", 2, "840")
    with pytest.raises(UnknownCurrencyError):
        Currency("USDX", "Too long", 2, "840")
    with pytest.raises(UnknownCurrencyError):
        Currency("USD", "US Dollar", 9, "840")


def test_rate_converts_and_inverts():
    rate = FxRate("EUR", "USD", "1.0850", date(2026, 9, 18))
    assert rate.pair == "EURUSD"
    assert rate.convert(Money(1000, "EUR")) == Money(Decimal("1085.000"), "USD")
    inverse = rate.inverse()
    assert inverse.pair == "USDEUR"
    assert inverse.rate == pytest.approx(Decimal(1) / Decimal("1.0850"))


def test_rate_rejects_the_wrong_direction_and_bad_values():
    with pytest.raises(ValidationError):
        FxRate("EUR", "USD", "1.08").convert(Money(100, "USD"))
    with pytest.raises(ValidationError):
        FxRate("EUR", "USD", "-1")
    with pytest.raises(ValidationError):
        FxRate("EUR", "USD", 0)


def test_table_finds_direct_inverse_and_cross_rates():
    table = FxTable(
        [FxRate("EUR", "USD", "1.0850"), FxRate("GBP", "USD", "1.2700"), FxRate("USD", "JPY", "147.50")],
        pivot="USD",
    )
    assert table.rate("EUR", "USD").rate == Decimal("1.0850")  # direct
    assert table.rate("USD", "EUR").rate == pytest.approx(Decimal(1) / Decimal("1.0850"))  # inverse
    cross = table.rate("EUR", "GBP").rate  # cross through USD
    assert cross == pytest.approx(Decimal("1.0850") / Decimal("1.2700"))
    assert table.rate("EUR", "JPY").rate == pytest.approx(Decimal("1.0850") * Decimal("147.50"))


def test_identical_currencies_convert_at_one():
    table = FxTable([FxRate("EUR", "USD", "1.0850")])
    assert table.rate("USD", "USD").rate == Decimal(1)
    assert table.convert(Money(100, "USD"), "USD") == Money(100, "USD")


def test_missing_pairs_raise():
    table = FxTable([FxRate("EUR", "USD", "1.0850")], pivot="USD")
    with pytest.raises(RateNotFoundError):
        table.rate("SEK", "NOK")


def test_table_converts_money_and_reports_pairs():
    table = FxTable([FxRate("EUR", "USD", "1.0850"), FxRate("GBP", "USD", "1.2700")])
    converted = table.convert(Money(1000, "GBP"), "EUR")
    assert converted.currency.code == "EUR"
    assert converted.amount == pytest.approx(Decimal(1000) * Decimal("1.2700") / Decimal("1.0850"))
    assert table.pairs() == ("EURUSD", "GBPUSD")
    assert len(table) == 2
    assert ("EUR", "USD") in table


def test_round_trip_conversion_returns_the_original_amount():
    table = FxTable([FxRate("EUR", "USD", "1.0850")])
    original = Money("1234.56", "EUR")
    round_trip = table.convert(table.convert(original, "USD"), "EUR")
    assert round_trip.amount == pytest.approx(original.amount)
