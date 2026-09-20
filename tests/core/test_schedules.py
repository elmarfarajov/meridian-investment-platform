"""Schedule generation: the rolls, the stubs and the end-of-month rule."""

from __future__ import annotations

from datetime import date

import pytest

from meridian.core.calendars import BusinessDayConvention
from meridian.core.enums import Frequency
from meridian.core.exceptions import ValidationError
from meridian.core.schedules import (
    RollConvention,
    StubConvention,
    accrual_fractions,
    add_months,
    generate_schedule,
    imm_date,
    imm_dates,
    is_end_of_month,
)


def test_a_whole_number_of_periods_produces_regular_periods():
    schedule = generate_schedule(date(2024, 5, 15), date(2032, 5, 15), Frequency.SEMI_ANNUAL)
    assert len(schedule) == 16
    assert not schedule.has_stub
    assert schedule.start == date(2024, 5, 15)
    assert schedule.end == date(2032, 5, 15)
    assert schedule.accrual_dates[1] == date(2024, 11, 15)


def test_quarterly_and_annual_frequencies():
    assert len(generate_schedule(date(2026, 1, 15), date(2031, 1, 15), Frequency.QUARTERLY)) == 20
    assert len(generate_schedule(date(2026, 1, 15), date(2031, 1, 15), Frequency.ANNUAL)) == 5
    assert len(generate_schedule(date(2026, 1, 15), date(2027, 1, 15), Frequency.MONTHLY)) == 12


def test_a_month_end_schedule_stays_on_month_ends():
    schedule = generate_schedule(date(2025, 1, 31), date(2026, 1, 31), Frequency.QUARTERLY)
    assert schedule.roll is RollConvention.END_OF_MONTH
    assert [period.end for period in schedule] == [
        date(2025, 4, 30),
        date(2025, 7, 31),
        date(2025, 10, 31),
        date(2026, 1, 31),
    ]


def test_a_mid_month_schedule_does_not_snap_to_month_ends():
    schedule = generate_schedule(date(2025, 1, 30), date(2026, 1, 30), Frequency.QUARTERLY)
    assert schedule.roll is RollConvention.DAY_OF_MONTH
    assert schedule[0].end == date(2025, 4, 30)
    assert schedule[1].end == date(2025, 7, 30)


def test_a_short_front_stub_lands_at_the_start():
    schedule = generate_schedule(date(2025, 2, 10), date(2026, 5, 15), Frequency.SEMI_ANNUAL)
    assert schedule.has_stub
    assert schedule[0].is_stub
    assert schedule[0].start == date(2025, 2, 10)
    assert schedule[0].end == date(2025, 5, 15)
    assert not schedule[-1].is_stub


def test_a_short_back_stub_lands_at_the_end():
    schedule = generate_schedule(
        date(2025, 2, 10), date(2026, 5, 15), Frequency.SEMI_ANNUAL, stub=StubConvention.SHORT_BACK
    )
    assert schedule[0].start == date(2025, 2, 10)
    assert schedule[0].end == date(2025, 8, 10)
    assert schedule[-1].end == date(2026, 5, 15)
    assert schedule[-1].is_stub


def test_a_long_front_stub_merges_the_odd_period_into_the_next_one():
    schedule = generate_schedule(
        date(2025, 2, 10), date(2026, 5, 15), Frequency.SEMI_ANNUAL, stub=StubConvention.LONG_FRONT
    )
    assert schedule[0].start == date(2025, 2, 10)
    assert schedule[0].end == date(2025, 11, 15)  # nine months, a long first period
    assert len(schedule) == 2


def test_refusing_a_stub_raises_when_the_term_is_not_a_whole_number_of_periods():
    with pytest.raises(ValidationError, match="whole number"):
        generate_schedule(date(2025, 2, 10), date(2026, 5, 15), Frequency.SEMI_ANNUAL, stub=StubConvention.NONE)


def test_payments_move_onto_business_days_while_accruals_stay_put():
    # 15 November 2026 is a Sunday, so the payment moves to Monday the 16th
    schedule = generate_schedule(date(2026, 5, 15), date(2027, 5, 15), Frequency.SEMI_ANNUAL, calendar="XNYS")
    first = schedule[0]
    assert first.end == date(2026, 11, 15)
    assert first.payment_date == date(2026, 11, 16)


def test_adjusted_accrual_moves_the_period_with_the_payment():
    schedule = generate_schedule(
        date(2026, 5, 15), date(2027, 5, 15), Frequency.SEMI_ANNUAL, calendar="XNYS", adjust_accrual=True
    )
    assert schedule[0].end == date(2026, 11, 16)
    assert schedule.metadata["adjust_accrual"] == "True"


def test_modified_following_does_not_cross_a_month_end():
    # 31 May 2026 is a Sunday; following would land in June, so the payment is pulled back
    schedule = generate_schedule(
        date(2025, 11, 30),
        date(2026, 5, 31),
        Frequency.SEMI_ANNUAL,
        calendar="XNYS",
        convention=BusinessDayConvention.MODIFIED_FOLLOWING,
    )
    assert schedule[-1].payment_date.month == 5


def test_a_payment_lag_pushes_every_payment_out():
    schedule = generate_schedule(date(2026, 1, 15), date(2027, 1, 15), Frequency.SEMI_ANNUAL, payment_lag=2)
    for period in schedule:
        assert period.payment_date > period.end


def test_period_lookup_and_remaining_periods():
    schedule = generate_schedule(date(2024, 5, 15), date(2027, 5, 15), Frequency.SEMI_ANNUAL)
    period = schedule.period_containing(date(2026, 3, 1))
    assert period is not None and period.start == date(2025, 11, 15)
    assert schedule.period_containing(date(2020, 1, 1)) is None
    assert len(schedule.remaining(date(2026, 3, 1))) == 3
    following = schedule.next_payment_after(date(2026, 3, 1))
    assert following is not None and following.payment_date == date(2026, 5, 15)


def test_accrual_fractions_sum_to_the_term_on_a_thirty_360_basis():
    schedule = generate_schedule(date(2024, 5, 15), date(2029, 5, 15), Frequency.SEMI_ANNUAL)
    fractions = accrual_fractions(schedule)
    assert len(fractions) == 10
    assert sum(fractions) == 5  # exactly five years on 30/360


def test_add_months_clamps_and_sticks_to_month_ends():
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_months(date(2025, 1, 31), 1, end_of_month=True) == date(2025, 2, 28)
    assert add_months(date(2025, 2, 28), 1, end_of_month=True) == date(2025, 3, 31)
    assert add_months(date(2025, 2, 28), 1) == date(2025, 3, 28)
    assert add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert is_end_of_month(date(2024, 2, 29))
    assert not is_end_of_month(date(2024, 2, 28))


def test_imm_dates_are_the_third_wednesday():
    assert imm_date(2026, 3) == date(2026, 3, 18)
    assert [day.weekday() for day in imm_dates(2026)] == [2, 2, 2, 2]
    assert len(imm_dates(2026)) == 4


def test_a_schedule_needs_a_positive_term_and_a_supported_frequency():
    with pytest.raises(ValidationError):
        generate_schedule(date(2026, 5, 15), date(2026, 5, 15), Frequency.ANNUAL)
    with pytest.raises(ValidationError, match="not supported"):
        generate_schedule(date(2026, 1, 1), date(2027, 1, 1), Frequency.DAILY)


def test_schedule_describes_itself():
    schedule = generate_schedule(date(2024, 5, 15), date(2027, 5, 15), Frequency.SEMI_ANNUAL)
    text = schedule.describe()
    assert "semi_annual" in text and "2027-05-15" in text
    assert str(schedule[0]).startswith("2024-05-15 ->")
