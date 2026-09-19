from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from meridian.core import CurrencyMismatchError, Money, ValidationError, money_sum
from meridian.core.currency import JPY, USD


def test_amounts_are_exact_decimals_not_floats():
    total = Money("0.1", "USD") + Money("0.2", "USD")
    assert total.amount == Decimal("0.3")
    assert total == Money("0.30", "USD")


def test_float_inputs_do_not_inherit_binary_noise():
    assert Money(0.1, "USD").amount == Decimal("0.1")


def test_currencies_never_mix_silently():
    with pytest.raises(CurrencyMismatchError) as error:
        Money(100, "USD") + Money(100, "EUR")
    assert error.value.operation == "add"
    with pytest.raises(CurrencyMismatchError):
        _ = Money(100, "USD") > Money(100, "EUR")


def test_arithmetic():
    assert Money(100, "USD") * 3 == Money(300, "USD")
    assert 3 * Money(100, "USD") == Money(300, "USD")
    assert Money(100, "USD") / 4 == Money(25, "USD")
    assert Money(150, "USD") / Money(100, "USD") == Decimal("1.5")
    assert -Money(100, "USD") == Money(-100, "USD")
    assert abs(Money(-100, "USD")) == Money(100, "USD")
    assert Money(100, "USD") - Money(40, "USD") == Money(60, "USD")


def test_arithmetic_rejects_nonsense():
    with pytest.raises(ValidationError):
        Money(100, "USD") * Money(2, "USD")
    with pytest.raises(ValidationError):
        Money(100, "USD") / 0
    with pytest.raises(ValidationError):
        Money(100, "USD") / Money(0, "USD")


def test_rounding_uses_minor_units_of_the_currency():
    assert Money("10.005", "USD").rounded().amount == Decimal("10.00")  # banker's rounding
    assert Money("10.015", "USD").rounded().amount == Decimal("10.02")
    assert Money("1250.7", "JPY").rounded().amount == Decimal("1251")
    assert USD.precision == Decimal("0.01")
    assert JPY.precision == Decimal("1")


def test_comparison_and_hashing():
    assert Money(10, "USD") < Money(20, "USD")
    assert Money(10, "USD") <= Money(10, "USD")
    assert Money(30, "USD") >= Money(20, "USD")
    assert len({Money(10, "USD"), Money("10.0", "USD"), Money(10, "EUR")}) == 2
    assert Money(10, "USD") != "10 USD"


def test_allocation_conserves_the_total():
    parts = Money("100.00", "USD").allocate([1, 1, 1])
    assert [part.amount for part in parts] == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    assert money_sum(parts) == Money("100.00", "USD")


def test_allocation_follows_weights_and_handles_zero_weights():
    parts = Money("1000.00", "USD").allocate([70, 30, 0])
    assert [part.amount for part in parts] == [Decimal("700.00"), Decimal("300.00"), Decimal("0.00")]


def test_allocation_of_negative_amounts_still_conserves():
    parts = Money("-10.00", "USD").allocate([1, 1, 1])
    assert money_sum(parts) == Money("-10.00", "USD")


def test_allocation_rejects_bad_weights():
    with pytest.raises(ValidationError):
        Money(100, "USD").allocate([])
    with pytest.raises(ValidationError):
        Money(100, "USD").allocate([1, -1])
    with pytest.raises(ValidationError):
        Money(100, "USD").allocate([0, 0])


def test_money_sum_needs_a_currency_when_empty():
    assert money_sum([], "USD") == Money(0, "USD")
    with pytest.raises(ValidationError):
        money_sum([])


def test_display():
    assert str(Money("1234567.891", "USD")) == "1,234,567.89 USD"
    assert repr(Money(5, "EUR")) == "Money(5, 'EUR')"


@given(
    amount=st.decimals(min_value=Decimal("-1e6"), max_value=Decimal("1e6"), places=2),
    weights=st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=12).filter(lambda w: sum(w) > 0),
)
def test_allocation_always_conserves_the_total(amount: Decimal, weights: list[int]):
    original = Money(amount, "USD")
    parts = original.allocate(weights)
    assert money_sum(parts) == original
    assert len(parts) == len(weights)
