"""The calendars added beyond the original three, and calendar composition."""

from __future__ import annotations

from datetime import date

import pytest

from meridian.core.calendars import (
    JointCalendar,
    autumnal_equinox,
    available_calendars,
    get_calendar,
    settlement_date,
    vernal_equinox,
)
from meridian.core.exceptions import CalendarError


def test_every_registered_calendar_is_reachable():
    assert {"XNYS", "SIFMA", "XLON", "TARGET", "XETR", "XSWX", "XTKS", "WEEKEND"} <= set(available_calendars())


@pytest.mark.parametrize(
    ("alias", "expected"),
    [("NYSE", "XNYS"), ("JPY", "XTKS"), ("CHF", "XSWX"), ("bond", "SIFMA"), ("t2", "TARGET"), ("DE", "XETR")],
)
def test_aliases_resolve(alias: str, expected: str):
    assert get_calendar(alias).name == expected


def test_holidays_carry_their_names():
    calendar = get_calendar("XNYS")
    assert calendar.holiday_name(date(2026, 7, 3)) == "Independence Day"
    assert calendar.holiday_name(date(2026, 11, 26)) == "Thanksgiving Day"
    assert calendar.holiday_name(date(2026, 7, 6)) is None


def test_the_bond_market_keeps_two_holidays_the_equity_market_does_not():
    equities = get_calendar("XNYS")
    bonds = get_calendar("SIFMA")
    columbus = date(2026, 10, 12)
    veterans = date(2026, 11, 11)
    assert equities.is_business_day(columbus) and not bonds.is_business_day(columbus)
    assert equities.is_business_day(veterans) and not bonds.is_business_day(veterans)
    assert bonds.holiday_name(columbus) == "Columbus Day"
    # Good Friday closes both
    assert not equities.is_business_day(date(2026, 4, 3))
    assert not bonds.is_business_day(date(2026, 4, 3))


def test_xetra_and_six_close_around_christmas_when_new_york_does_not():
    xetra = get_calendar("XETR")
    six = get_calendar("XSWX")
    assert not xetra.is_business_day(date(2026, 12, 24))
    assert not xetra.is_business_day(date(2026, 12, 31))
    assert not six.is_business_day(date(2026, 1, 2))  # Berchtold's Day
    assert get_calendar("XNYS").is_business_day(date(2026, 12, 24))


def test_whit_monday_is_fifty_days_after_easter():
    # Easter Sunday 2026 is 5 April, so Whit Monday is 25 May
    assert get_calendar("XETR").holiday_name(date(2026, 5, 25)) == "Whit Monday"
    assert get_calendar("XSWX").holiday_name(date(2026, 5, 14)) == "Ascension Day"


@pytest.mark.parametrize(
    ("year", "vernal", "autumnal"),
    [(2024, date(2024, 3, 20), date(2024, 9, 22)), (2026, date(2026, 3, 20), date(2026, 9, 23))],
)
def test_the_japanese_equinoxes_are_computed(year: int, vernal: date, autumnal: date):
    assert vernal_equinox(year) == vernal
    assert autumnal_equinox(year) == autumnal
    tokyo = get_calendar("XTKS")
    assert tokyo.holiday_name(vernal) == "Vernal Equinox Day"
    assert tokyo.holiday_name(autumnal) == "Autumnal Equinox Day"


def test_a_sunday_holiday_in_tokyo_moves_to_the_next_free_weekday():
    tokyo = get_calendar("XTKS")
    # Constitution Memorial Day 2026 falls on a Sunday; 4 and 5 May are already holidays,
    # so the substitute lands on the 6th
    assert tokyo.holiday_name(date(2026, 5, 3)) == "Constitution Memorial Day"
    assert tokyo.holiday_name(date(2026, 5, 6)) == "Constitution Memorial Day (observed)"
    assert not tokyo.is_business_day(date(2026, 5, 6))


def test_tokyo_closes_for_the_new_year_period():
    tokyo = get_calendar("XTKS")
    for day in (date(2026, 1, 1), date(2026, 1, 2), date(2026, 12, 31)):
        assert tokyo.is_holiday(day), day


def test_a_joint_calendar_is_closed_when_any_member_is_closed():
    joint = JointCalendar(["XNYS", "XLON"])
    independence = date(2026, 7, 3)  # US only
    summer_bank = date(2026, 8, 31)  # UK only
    assert not joint.is_business_day(independence)
    assert not joint.is_business_day(summer_bank)
    assert joint.is_business_day(date(2026, 7, 6))
    assert joint.name == "XNYS+XLON"


def test_a_joint_holiday_name_says_which_market_closed():
    joint = JointCalendar(["XNYS", "XLON"])
    assert "XNYS" in (joint.holiday_name(date(2026, 7, 3)) or "")
    assert "XLON" in (joint.holiday_name(date(2026, 8, 31)) or "")


def test_intersection_mode_keeps_only_shared_holidays():
    shared = JointCalendar(["XNYS", "XLON"], mode="intersection")
    assert shared.is_holiday(date(2026, 1, 1))  # both closed
    assert not shared.is_holiday(date(2026, 7, 3))  # US only


def test_calendars_compose_through_the_plus_syntax():
    assert get_calendar("XNYS+XTKS").name == "XNYS+XTKS"
    assert not get_calendar("XNYS+XTKS").is_business_day(date(2026, 1, 2))  # Tokyo new year


def test_a_joint_calendar_needs_members_and_a_known_mode():
    with pytest.raises(CalendarError):
        JointCalendar([])
    with pytest.raises(CalendarError):
        JointCalendar(["XNYS"], mode="nonsense")


def test_settlement_across_two_markets_is_never_earlier_than_either_alone():
    trade = date(2026, 12, 23)
    both = settlement_date(trade, 2, ["XNYS", "XLON"])
    assert both >= get_calendar("XNYS").add_business_days(trade, 2)
    assert both >= get_calendar("XLON").add_business_days(trade, 2)
    assert both == date(2026, 12, 29)


def test_holiday_counts_are_stable_for_2026():
    counts = {name: len(get_calendar(name).holidays(2026)) for name in ("XNYS", "SIFMA", "XLON", "TARGET", "XETR")}
    assert counts == {"XNYS": 10, "SIFMA": 12, "XLON": 8, "TARGET": 6, "XETR": 9}
