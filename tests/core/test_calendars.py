from datetime import date

import pytest

from meridian.core import BusinessDayConvention, CalendarError, available_calendars, easter_sunday, get_calendar
from meridian.core.calendars import MONDAY, THURSDAY, nth_weekday

NYSE = get_calendar("XNYS")
LSE = get_calendar("XLON")
TARGET = get_calendar("TARGET")


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2027, date(2027, 3, 28)),
        (2030, date(2030, 4, 21)),
    ],
)
def test_easter_matches_the_published_dates(year, expected):
    assert easter_sunday(year) == expected


def test_nth_weekday():
    assert nth_weekday(2026, 1, MONDAY, 3) == date(2026, 1, 19)  # Martin Luther King Jr. Day
    assert nth_weekday(2026, 11, THURSDAY, 4) == date(2026, 11, 26)  # Thanksgiving
    assert nth_weekday(2026, 5, MONDAY, -1) == date(2026, 5, 25)  # Memorial Day


@pytest.mark.parametrize(
    "holiday",
    [
        date(2026, 1, 1),  # New Year's Day
        date(2026, 1, 19),  # Martin Luther King Jr. Day
        date(2026, 2, 16),  # Washington's Birthday
        date(2026, 4, 3),  # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 6, 19),  # Juneteenth
        date(2026, 7, 3),  # Independence Day observed on the Friday
        date(2026, 9, 7),  # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas Day
    ],
)
def test_nyse_holidays_2026(holiday):
    assert NYSE.is_holiday(holiday)
    assert not NYSE.is_business_day(holiday)


def test_nyse_has_ten_holidays_in_2026():
    assert len(NYSE.holidays(2026)) == 10


def test_juneteenth_only_applies_from_2022():
    assert not NYSE.is_holiday(date(2021, 6, 18))
    assert NYSE.is_holiday(date(2022, 6, 20))  # 19 June 2022 was a Sunday, observed on the Monday


@pytest.mark.parametrize(
    "holiday",
    [
        date(2026, 1, 1),
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 6),  # Easter Monday
        date(2026, 5, 4),  # Early May bank holiday
        date(2026, 5, 25),  # Spring bank holiday
        date(2026, 8, 31),  # Summer bank holiday
        date(2026, 12, 25),
        date(2026, 12, 28),  # Boxing Day substitute, 26 December being a Saturday
    ],
)
def test_lse_holidays_2026(holiday):
    assert LSE.is_holiday(holiday)


def test_target_is_a_settlement_calendar_not_an_exchange_one():
    assert TARGET.is_holiday(date(2026, 5, 1))  # Labour Day closes euro settlement
    assert not NYSE.is_holiday(date(2026, 5, 1))  # but not the NYSE
    assert TARGET.is_holiday(date(2026, 12, 26)) or TARGET.is_weekend(date(2026, 12, 26))


def test_weekends_are_never_business_days():
    assert not NYSE.is_business_day(date(2026, 9, 19))  # Saturday
    assert not NYSE.is_business_day(date(2026, 9, 20))  # Sunday
    assert NYSE.is_business_day(date(2026, 9, 18))  # Friday


def test_settlement_arithmetic():
    # T+1 US equity settlement from a Wednesday lands on the Thursday
    assert NYSE.add_business_days(date(2026, 9, 16), 1) == date(2026, 9, 17)
    # T+2 across a weekend
    assert NYSE.add_business_days(date(2026, 9, 17), 2) == date(2026, 9, 21)
    # and across Thanksgiving
    assert NYSE.add_business_days(date(2026, 11, 25), 2) == date(2026, 11, 30)
    assert NYSE.add_business_days(date(2026, 9, 21), -1) == date(2026, 9, 18)


def test_business_day_conventions():
    christmas = date(2026, 12, 25)  # Friday, a holiday
    assert NYSE.adjust(christmas, BusinessDayConvention.UNADJUSTED) == christmas
    assert NYSE.adjust(christmas, BusinessDayConvention.FOLLOWING) == date(2026, 12, 28)
    assert NYSE.adjust(christmas, BusinessDayConvention.PRECEDING) == date(2026, 12, 24)
    # Modified following stays inside the month, so a month-end holiday rolls backwards
    month_end = date(2026, 5, 31)  # Sunday
    assert NYSE.adjust(month_end, BusinessDayConvention.FOLLOWING) == date(2026, 6, 1)
    assert NYSE.adjust(month_end, BusinessDayConvention.MODIFIED_FOLLOWING) == date(2026, 5, 29)
    month_start = date(2026, 8, 1)  # Saturday
    assert NYSE.adjust(month_start, BusinessDayConvention.MODIFIED_PRECEDING) == date(2026, 8, 3)


def test_business_day_counts_and_ranges():
    days = list(NYSE.business_days(date(2026, 11, 23), date(2026, 11, 27)))
    assert days == [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27)]
    assert NYSE.business_days_between(date(2026, 11, 23), date(2026, 11, 28)) == 4
    assert NYSE.business_days_between(date(2026, 11, 28), date(2026, 11, 23)) == -4
    assert NYSE.business_days_between(date(2026, 11, 23), date(2026, 11, 23)) == 0


def test_trading_days_in_a_year_are_plausible():
    trading_days = sum(1 for _ in NYSE.business_days(date(2026, 1, 1), date(2026, 12, 31)))
    assert 249 <= trading_days <= 254  # the NYSE trades roughly 252 days a year


def test_holidays_between_and_registry():
    holidays = NYSE.holidays_between(date(2026, 1, 1), date(2026, 3, 31))
    assert holidays == (date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16))
    assert "XNYS" in available_calendars()
    assert get_calendar("nyse") is NYSE
    assert get_calendar(NYSE) is NYSE
    with pytest.raises(CalendarError):
        get_calendar("XMAD")


def test_business_days_rejects_a_reversed_range():
    with pytest.raises(CalendarError):
        list(NYSE.business_days(date(2026, 2, 1), date(2026, 1, 1)))
