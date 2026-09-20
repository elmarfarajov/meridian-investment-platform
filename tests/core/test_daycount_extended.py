"""The day-count conventions that need context beyond two dates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from meridian.core.daycount import DayCountConvention, compare_conventions, year_fraction
from meridian.core.exceptions import ValidationError


def test_act_365_25_sits_between_act_360_and_act_365():
    start, end = date(2026, 1, 15), date(2026, 7, 15)
    act_360 = year_fraction(start, end, DayCountConvention.ACT_360)
    act_365 = year_fraction(start, end, DayCountConvention.ACT_365F)
    act_36525 = year_fraction(start, end, DayCountConvention.ACT_365_25)
    assert act_365 > act_36525
    assert act_360 > act_365


def test_act_act_icma_divides_by_the_coupon_period():
    """Half a year between coupon dates is exactly 0.5 under ICMA, whatever the actual days."""
    start, end = date(2026, 1, 15), date(2026, 7, 15)
    fraction = year_fraction(
        start, end, DayCountConvention.ACT_ACT_ICMA, period_start=start, period_end=end, frequency=2
    )
    assert fraction == Decimal("0.5")

    # A February-to-August period has a different day count but the same year fraction
    other = year_fraction(
        date(2026, 2, 15),
        date(2026, 8, 15),
        DayCountConvention.ACT_ACT_ICMA,
        period_start=date(2026, 2, 15),
        period_end=date(2026, 8, 15),
        frequency=2,
    )
    assert other == Decimal("0.5")
    assert year_fraction(date(2026, 1, 15), date(2026, 7, 15), DayCountConvention.ACT_365F) != Decimal("0.5")


def test_act_act_icma_handles_a_partial_period():
    fraction = year_fraction(
        date(2026, 1, 15),
        date(2026, 4, 15),
        DayCountConvention.ACT_ACT_ICMA,
        period_start=date(2026, 1, 15),
        period_end=date(2026, 7, 15),
        frequency=2,
    )
    assert fraction == pytest.approx(Decimal(90) / Decimal(181 * 2), abs=Decimal("1e-9"))


def test_act_act_icma_without_its_context_is_refused():
    with pytest.raises(ValidationError, match="ACT/ACT ICMA needs"):
        year_fraction(date(2026, 1, 15), date(2026, 7, 15), DayCountConvention.ACT_ACT_ICMA)
    with pytest.raises(ValidationError, match="positive"):
        year_fraction(
            date(2026, 1, 15),
            date(2026, 7, 15),
            DayCountConvention.ACT_ACT_ICMA,
            period_start=date(2026, 1, 15),
            period_end=date(2026, 7, 15),
            frequency=0,
        )


def test_bus_252_counts_business_days():
    fraction = year_fraction(date(2026, 1, 15), date(2026, 7, 15), DayCountConvention.BUS_252, calendar="XNYS")
    assert fraction == Decimal(123) / Decimal(252)
    # A full year of business days is close to, but not exactly, one
    full = year_fraction(date(2026, 1, 1), date(2027, 1, 1), DayCountConvention.BUS_252, calendar="XNYS")
    assert Decimal("0.98") < full < Decimal("1.01")


def test_bus_252_needs_a_calendar():
    with pytest.raises(ValidationError, match="needs a trading calendar"):
        year_fraction(date(2026, 1, 15), date(2026, 7, 15), DayCountConvention.BUS_252)


def test_thirty_e_360_isda_treats_february_at_maturity_differently():
    start, end = date(2026, 8, 31), date(2027, 2, 28)
    ordinary = year_fraction(start, end, DayCountConvention.THIRTY_E_360_ISDA)
    at_maturity = year_fraction(start, end, DayCountConvention.THIRTY_E_360_ISDA, end_is_maturity=True)
    assert ordinary == Decimal("0.5")  # February's end becomes the 30th
    assert at_maturity < ordinary  # unless it is the maturity date, when it does not


def test_thirty_day_conventions_agree_on_an_ordinary_period():
    start, end = date(2026, 3, 15), date(2026, 9, 15)
    for convention in (
        DayCountConvention.THIRTY_360_US,
        DayCountConvention.THIRTY_E_360,
        DayCountConvention.THIRTY_E_360_ISDA,
    ):
        assert year_fraction(start, end, convention) == Decimal("0.5")


def test_the_comparison_covers_every_convention_and_spreads_real_money():
    results = compare_conventions(date(2026, 1, 15), date(2026, 7, 15), notional=10_000_000, annual_rate="0.05")
    assert set(results) == set(DayCountConvention)
    accrued = [value for _, value in results.values()]
    spread = max(accrued) - min(accrued)
    assert spread > Decimal(5_000)  # over five thousand on ten million, for one period


def test_conventions_describe_their_denominators():
    assert DayCountConvention.ACT_360.denominator_label == "360"
    assert DayCountConvention.BUS_252.needs_schedule
    assert DayCountConvention.ACT_ACT_ICMA.needs_schedule
    assert not DayCountConvention.ACT_360.needs_schedule


def test_reversed_dates_negate_the_fraction_for_context_hungry_conventions():
    forward = year_fraction(date(2026, 1, 15), date(2026, 7, 15), DayCountConvention.BUS_252, calendar="XNYS")
    backward = year_fraction(date(2026, 7, 15), date(2026, 1, 15), DayCountConvention.BUS_252, calendar="XNYS")
    assert backward == -forward
