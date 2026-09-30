"""Calendars as history: rules with start dates, special closures and openings, and computed equinoxes."""

from datetime import date, datetime, timedelta, timezone

import pytest

from meridian.core.astronomy import equinox, equinox_day
from meridian.core.calendars import get_calendar


@pytest.mark.parametrize(
    ("year", "season", "published"),
    [
        (1990, "march", datetime(1990, 3, 20, 21, 19, tzinfo=timezone.utc)),
        (2012, "september", datetime(2012, 9, 22, 14, 49, tzinfo=timezone.utc)),
        (2024, "march", datetime(2024, 3, 20, 3, 6, tzinfo=timezone.utc)),
        (2025, "september", datetime(2025, 9, 22, 18, 19, tzinfo=timezone.utc)),
    ],
)
def test_the_equinox_lands_within_two_minutes_of_the_published_instant(year, season, published):
    assert abs(equinox(year, season) - published) < timedelta(minutes=2)


@pytest.mark.parametrize(
    ("year", "season", "day"),
    [
        (1990, "march", date(1990, 3, 21)),  # 21:19 UTC on the 20th is the morning of the 21st in Tokyo
        (1993, "march", date(1993, 3, 20)),
        (2023, "march", date(2023, 3, 21)),
        (2025, "september", date(2025, 9, 23)),  # 18:19 UTC on the 22nd, the 23rd in Tokyo
        (2027, "march", date(2027, 3, 21)),
    ],
)
def test_japan_observes_the_equinox_on_the_tokyo_date(year, season, day):
    assert equinox_day(year, season) == day


def test_the_equinox_algorithm_refuses_years_outside_its_table():
    with pytest.raises(ValueError, match="1000 to 3000"):
        equinox(900, "march")


def test_martin_luther_king_day_closes_the_nyse_only_from_1998():
    nyse = get_calendar("XNYS")
    assert nyse.is_business_day(date(1997, 1, 20))
    assert nyse.holiday_name(date(1998, 1, 19)) == "Martin Luther King Jr. Day"
    # the bond market observed it from 1983
    assert not get_calendar("SIFMA").is_business_day(date(1997, 1, 20))


@pytest.mark.parametrize(
    ("day", "name"),
    [
        (date(2001, 9, 11), "September 11 attacks"),
        (date(2001, 9, 14), "September 11 attacks"),
        (date(2012, 10, 29), "Hurricane Sandy"),
        (date(2018, 12, 5), "National Day of Mourning for President George H. W. Bush"),
        (date(2025, 1, 9), "National Day of Mourning for President Carter"),
    ],
)
def test_the_nyse_records_closures_no_rule_predicts(day, name):
    assert get_calendar("XNYS").holiday_name(day) == name


def test_a_special_closure_is_actual_but_not_scheduled():
    nyse = get_calendar("XNYS")
    carter = date(2025, 1, 9)
    assert not nyse.is_business_day(carter)
    assert nyse.scheduled().is_business_day(carter)
    assert nyse.scheduled().scheduled() is nyse.scheduled()


def test_sifma_opens_on_good_friday_when_the_employment_report_is_published():
    bonds = get_calendar("SIFMA")
    assert bonds.is_business_day(date(2026, 4, 3))  # decided: early close, not a holiday
    assert not bonds.scheduled().is_business_day(date(2026, 4, 3))
    assert not bonds.is_business_day(date(2025, 4, 18))  # no report that day
    assert bonds.is_business_day(date(2034, 4, 7))  # projected: the first Friday of the month
    assert not bonds.is_business_day(date(2027, 3, 26))


def test_sifma_does_not_move_a_saturday_veterans_day():
    bonds = get_calendar("SIFMA")
    assert bonds.is_business_day(date(2023, 11, 10))
    assert not bonds.is_business_day(date(2024, 11, 11))


@pytest.mark.parametrize(
    "day",
    [
        date(1995, 5, 8),  # VE Day 50th: the early May bank holiday moved
        date(2002, 6, 3),
        date(2002, 6, 4),
        date(2011, 4, 29),
        date(2012, 6, 5),
        date(2020, 5, 8),
        date(2022, 6, 2),
        date(2022, 6, 3),
        date(2022, 9, 19),
        date(2023, 5, 8),
    ],
)
def test_london_closes_for_national_occasions(day):
    assert not get_calendar("XLON").is_business_day(day)


def test_the_moved_bank_holidays_leave_their_usual_days_open():
    london = get_calendar("XLON")
    assert london.is_business_day(date(2020, 5, 4))
    assert london.is_business_day(date(2022, 5, 30))


def test_target_added_its_easter_and_labour_day_closures_in_2000():
    target = get_calendar("TARGET")
    assert target.is_business_day(date(1999, 4, 2))  # Good Friday 1999
    assert not target.is_business_day(date(2000, 4, 21))  # Good Friday 2000
    assert not target.is_business_day(date(1999, 12, 31))
    assert not target.is_business_day(date(2001, 12, 31))


@pytest.mark.parametrize(
    ("day", "name"),
    [
        (date(1999, 1, 15), "Coming of Age Day"),  # before the Happy Monday reform
        (date(2000, 1, 10), "Coming of Age Day"),
        (date(1999, 10, 11), "Sports Day (substitute holiday)"),  # 10 October 1999 was a Sunday
        (date(2002, 9, 16), "Respect for the Aged Day (substitute holiday)"),
        (date(2003, 9, 15), "Respect for the Aged Day"),
        (date(2020, 7, 23), "Marine Day"),  # the Olympic moves
        (date(2020, 7, 24), "Sports Day"),
        (date(2020, 8, 10), "Mountain Day"),
        (date(2021, 8, 9), "Mountain Day (substitute holiday)"),
        (date(2015, 9, 22), "Citizens' Holiday"),  # the Silver Week
        (date(2026, 9, 22), "Citizens' Holiday"),
        (date(2019, 4, 30), "Citizens' Holiday"),  # around the accession
        (date(2019, 5, 1), "Accession of Emperor Naruhito"),
        (date(2019, 5, 2), "Citizens' Holiday"),
        (date(2019, 10, 22), "Enthronement Ceremony of Emperor Naruhito"),
    ],
)
def test_tokyo_follows_the_holiday_law_as_it_stood(day, name):
    assert get_calendar("XTKS").holiday_name(day) == name


def test_before_2007_a_sunday_holiday_was_substituted_only_by_the_monday():
    tokyo = get_calendar("XTKS")
    # 3 May 1998 was a Sunday: 4 May was the substitute, 5 May Children's Day, 6 May open
    assert tokyo.holiday_name(date(1998, 5, 4)) == "Constitution Memorial Day (substitute holiday)"
    assert tokyo.is_business_day(date(1998, 5, 6))
    # from 2007 the substitute moves on to the next free day
    assert not tokyo.is_business_day(date(2026, 5, 6))


def test_the_emperor_s_birthday_moved_with_the_accession():
    tokyo = get_calendar("XTKS")
    assert tokyo.holiday_name(date(2018, 12, 24)) == "The Emperor's Birthday (substitute holiday)"
    assert tokyo.is_business_day(date(2019, 12, 23))
    assert tokyo.holiday_name(date(2026, 2, 23)) == "The Emperor's Birthday"


def test_a_joint_calendar_has_a_scheduled_view_too():
    joint = get_calendar("XNYS+XLON")
    carter = date(2025, 1, 9)
    assert not joint.is_business_day(carter)
    assert joint.scheduled().is_business_day(carter)
