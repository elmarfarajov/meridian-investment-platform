"""The holding period by the calendar: IRS Publication 550's examples, across leap days."""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given
from hypothesis import strategies as st

from meridian.domain.positions import is_long_term, long_term_from, one_year_after
from meridian.optimisation.assets import LotState


def test_publication_550_a_leap_year_makes_366_days_short_term():
    bought = date(2024, 2, 5)
    assert (date(2025, 2, 5) - bought).days == 366  # what a count of 365 days called long-term
    assert not is_long_term(bought, date(2025, 2, 5))
    assert is_long_term(bought, date(2025, 2, 6))
    assert long_term_from(bought) == date(2025, 2, 6)


def test_a_lot_bought_on_a_leap_day_has_its_anniversary_on_28_february():
    assert one_year_after(date(2024, 2, 29)) == date(2025, 2, 28)
    assert not is_long_term(date(2024, 2, 29), date(2025, 2, 28))
    assert is_long_term(date(2024, 2, 29), date(2025, 3, 1))


def test_the_optimiser_and_the_book_of_record_use_the_same_rule():
    lot = LotState("L1", "A", 1.0, 100.0, holding_start=date(2024, 2, 5), opened=date(2024, 2, 5))
    assert not lot.is_long_term(date(2025, 2, 5)) and lot.is_long_term(date(2025, 2, 6))
    assert lot.days_to_long_term(date(2025, 2, 5)) == 1 and lot.days_to_long_term(date(2025, 3, 1)) == 0


@given(st.dates(min_value=date(1900, 1, 1), max_value=date(2200, 1, 1)))
def test_long_term_means_more_than_one_calendar_year(start: date):
    first = long_term_from(start)
    assert 366 <= (first - start).days <= 367
    assert is_long_term(start, first) and not is_long_term(start, first - timedelta(days=1))
