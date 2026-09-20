"""Compounding conventions and the time value of money."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.core.compounding import (
    Compounding,
    annuity_factor,
    compounding_comparison,
    convert_rate,
    discount_factor,
    effective_annual_rate,
    forward_rate,
    future_value,
    present_value,
    zero_rate,
)
from meridian.core.exceptions import ValidationError


def test_discount_factors_match_the_textbook_formulas():
    assert discount_factor(0.05, 1, Compounding.ANNUAL) == pytest.approx(1 / 1.05)
    assert discount_factor(0.05, 1, Compounding.SEMI_ANNUAL) == pytest.approx(1 / 1.025**2)
    assert discount_factor(0.05, 1, Compounding.CONTINUOUS) == pytest.approx(math.exp(-0.05))
    assert discount_factor(0.05, 1, Compounding.SIMPLE) == pytest.approx(1 / 1.05)
    assert discount_factor(0.05, 0) == 1.0


def test_more_frequent_compounding_discounts_harder():
    factors = [
        discount_factor(0.05, 10, convention)
        for convention in (
            Compounding.SIMPLE,
            Compounding.ANNUAL,
            Compounding.SEMI_ANNUAL,
            Compounding.QUARTERLY,
            Compounding.MONTHLY,
            Compounding.CONTINUOUS,
        )
    ]
    assert factors == sorted(factors, reverse=True)


@pytest.mark.parametrize(
    "convention",
    [Compounding.ANNUAL, Compounding.SEMI_ANNUAL, Compounding.QUARTERLY, Compounding.MONTHLY, Compounding.CONTINUOUS],
)
def test_zero_rate_inverts_the_discount_factor(convention: Compounding):
    assert zero_rate(discount_factor(0.037, 7.5, convention), 7.5, convention) == pytest.approx(0.037)


def test_converting_between_conventions_leaves_the_money_unchanged():
    annual = 0.05
    continuous = convert_rate(annual, 1.0, Compounding.ANNUAL, Compounding.CONTINUOUS)
    assert continuous == pytest.approx(math.log(1.05))
    assert discount_factor(continuous, 1.0, Compounding.CONTINUOUS) == pytest.approx(
        discount_factor(annual, 1.0, Compounding.ANNUAL)
    )
    assert convert_rate(annual, 3.0, Compounding.ANNUAL, Compounding.ANNUAL) == annual


def test_effective_annual_rate_ranks_the_conventions():
    assert effective_annual_rate(0.05, Compounding.ANNUAL) == pytest.approx(0.05)
    assert effective_annual_rate(0.05, Compounding.SEMI_ANNUAL) == pytest.approx(0.050625)
    assert effective_annual_rate(0.05, Compounding.CONTINUOUS) > effective_annual_rate(0.05, Compounding.MONTHLY)


def test_forward_rates_chain_back_to_the_spot_rate():
    near = discount_factor(0.04, 1.0)
    far = discount_factor(0.05, 2.0)
    implied = forward_rate(near, far, 1.0, 2.0)
    assert implied == pytest.approx(0.06, abs=1e-12)
    assert near * math.exp(-implied * 1.0) == pytest.approx(far)


def test_present_and_future_value_are_inverses():
    assert future_value(present_value(1_000, 0.06, 4, Compounding.QUARTERLY), 0.06, 4, Compounding.QUARTERLY) == (
        pytest.approx(1_000)
    )


def test_annuity_factor_matches_the_closed_form_and_handles_a_zero_rate():
    assert annuity_factor(0.05, 10) == pytest.approx((1 - 1.05**-10) / 0.05)
    assert annuity_factor(0.0, 10) == 10.0


def test_the_comparison_table_covers_every_convention():
    table = compounding_comparison(0.05, 10)
    assert set(table) == set(Compounding)
    simple, _ = table[Compounding.SIMPLE]
    continuous, _ = table[Compounding.CONTINUOUS]
    assert simple - continuous > 0.05  # more than five cents in the unit


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValidationError):
        zero_rate(0.0, 1.0)
    with pytest.raises(ValidationError):
        zero_rate(0.9, 0.0)
    with pytest.raises(ValidationError):
        forward_rate(0.9, 0.8, 2.0, 1.0)
    with pytest.raises(ValidationError):
        annuity_factor(0.05, 0)
    with pytest.raises(ValidationError):
        Compounding.from_frequency(5)


def test_compounding_from_frequency():
    assert Compounding.from_frequency(2) is Compounding.SEMI_ANNUAL
    assert Compounding.SEMI_ANNUAL.periods_per_year == 2
    assert Compounding.CONTINUOUS.periods_per_year is None


@settings(max_examples=150, deadline=None)
@given(
    rate=st.floats(min_value=-0.02, max_value=0.25, allow_nan=False),
    years=st.floats(min_value=0.05, max_value=40.0, allow_nan=False),
)
def test_rate_conversion_round_trips_for_any_rate_and_horizon(rate: float, years: float):
    """Whatever the rate, restating it and restating it back must return it."""
    continuous = convert_rate(rate, years, Compounding.SEMI_ANNUAL, Compounding.CONTINUOUS)
    back = convert_rate(continuous, years, Compounding.CONTINUOUS, Compounding.SEMI_ANNUAL)
    assert back == pytest.approx(rate, abs=1e-10)
