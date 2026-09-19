from datetime import date
from decimal import Decimal

import pytest

from meridian.core import AccrualPeriod, DayCountConvention, year_fraction


@pytest.mark.parametrize(
    ("convention", "expected"),
    [
        (DayCountConvention.ACT_360, Decimal(181) / Decimal(360)),
        (DayCountConvention.ACT_365F, Decimal(181) / Decimal(365)),
        (DayCountConvention.THIRTY_360_US, Decimal("0.5")),
        (DayCountConvention.THIRTY_E_360, Decimal("0.5")),
    ],
)
def test_half_year_under_each_convention(convention, expected):
    assert year_fraction(date(2026, 1, 1), date(2026, 7, 1), convention) == pytest.approx(expected)


def test_act_360_exceeds_act_365_because_the_year_is_shorter():
    start, end = date(2026, 1, 1), date(2026, 12, 31)
    assert year_fraction(start, end, DayCountConvention.ACT_360) > year_fraction(
        start, end, DayCountConvention.ACT_365F
    )


def test_thirty_360_treats_month_ends_as_thirty_days():
    # 31 January to 28 February is 28 actual days but 28 thirty-day days too
    assert year_fraction(date(2026, 1, 31), date(2026, 2, 28), DayCountConvention.THIRTY_360_US) == pytest.approx(
        Decimal(28) / Decimal(360)
    )
    # 30 January to 31 March: the US convention caps the second day at 30
    assert year_fraction(date(2026, 1, 30), date(2026, 3, 31), DayCountConvention.THIRTY_360_US) == pytest.approx(
        Decimal(60) / Decimal(360)
    )
    assert year_fraction(date(2026, 1, 31), date(2026, 3, 31), DayCountConvention.THIRTY_E_360) == pytest.approx(
        Decimal(60) / Decimal(360)
    )


def test_act_act_isda_splits_at_the_year_end():
    # 2024 is a leap year, so the two halves are weighted by different year lengths
    value = year_fraction(date(2024, 12, 1), date(2025, 2, 1), DayCountConvention.ACT_ACT_ISDA)
    expected = Decimal(31) / Decimal(366) + Decimal(31) / Decimal(365)
    assert value == pytest.approx(expected)


def test_a_full_calendar_year_is_one_under_act_act():
    assert year_fraction(date(2025, 1, 1), date(2026, 1, 1), DayCountConvention.ACT_ACT_ISDA) == pytest.approx(
        Decimal(1)
    )
    assert year_fraction(date(2024, 1, 1), date(2025, 1, 1), DayCountConvention.ACT_ACT_ISDA) == pytest.approx(
        Decimal(1)
    )


def test_reversed_dates_give_a_negative_fraction():
    assert year_fraction(date(2026, 7, 1), date(2026, 1, 1), DayCountConvention.ACT_365F) < 0
    assert year_fraction(date(2026, 1, 1), date(2026, 1, 1)) == 0


def test_conventions_accept_their_string_names():
    assert year_fraction(date(2026, 1, 1), date(2026, 7, 1), "ACT/360") == year_fraction(
        date(2026, 1, 1), date(2026, 7, 1), DayCountConvention.ACT_360
    )


def test_accrual_period_computes_interest():
    period = AccrualPeriod(date(2026, 1, 1), date(2026, 7, 1), DayCountConvention.ACT_360)
    assert period.days == 181
    interest = period.accrue(Decimal("1000000"), Decimal("0.0525"))
    assert interest == pytest.approx(Decimal("1000000") * Decimal("0.0525") * Decimal(181) / Decimal(360))
