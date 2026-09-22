"""The time series container: ordering, exactness, staleness and returns."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from meridian.core.exceptions import ValidationError
from meridian.marketdata.series import FillMethod, TimeSeries, merge_series


@pytest.fixture
def series() -> TimeSeries:
    return TimeSeries(
        [
            (date(2026, 1, 6), "101.00"),
            (date(2026, 1, 2), "100.00"),
            (date(2026, 1, 7), "99.00"),
            (date(2026, 1, 9), "102.96"),
        ],
        name="XYZ",
    )


def test_points_are_sorted_and_exact(series: TimeSeries):
    assert series.days == (date(2026, 1, 2), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 9))
    assert series[date(2026, 1, 6)] == Decimal("101.00")
    assert all(isinstance(value, Decimal) for value in series.values)
    assert series.first.value == Decimal("100.00")
    assert series.last.day == date(2026, 1, 9)


def test_a_duplicate_date_is_a_load_error_not_something_to_average():
    with pytest.raises(ValidationError, match="duplicate"):
        TimeSeries([(date(2026, 1, 2), 1), (date(2026, 1, 2), 2)])


def test_membership_lookup_and_missing_keys(series: TimeSeries):
    assert date(2026, 1, 7) in series
    assert date(2026, 1, 8) not in series
    assert "2026-01-07" not in series
    assert series.get(date(2026, 1, 8)) is None
    with pytest.raises(KeyError):
        series[date(2026, 1, 8)]


def test_as_of_carries_forward_and_reports_the_age(series: TimeSeries):
    found = series.as_of(date(2026, 1, 8))
    assert found is not None
    assert found.day == date(2026, 1, 7)
    assert found.value == Decimal("99.00")
    assert found.age_days == 1
    assert not found.is_exact
    exact = series.as_of(date(2026, 1, 9))
    assert exact is not None and exact.is_exact


def test_as_of_refuses_a_value_older_than_the_limit(series: TimeSeries):
    assert series.as_of(date(2026, 1, 20), max_age_days=5) is None
    assert series.as_of(date(2026, 1, 12), max_age_days=5) is not None


def test_as_of_before_the_first_observation_is_none(series: TimeSeries):
    assert series.as_of(date(2025, 12, 31)) is None


def test_between_is_inclusive(series: TimeSeries):
    part = series.between(date(2026, 1, 6), date(2026, 1, 7))
    assert part.days == (date(2026, 1, 6), date(2026, 1, 7))
    assert series.between().days == series.days


def test_returns_are_between_observations_so_a_gap_is_one_multi_day_return(series: TimeSeries):
    returns = dict(series.returns())
    assert returns[date(2026, 1, 6)] == pytest.approx(0.01)
    assert returns[date(2026, 1, 9)] == pytest.approx(102.96 / 99 - 1)
    assert len(returns) == 3


def test_log_returns_sum_to_the_total_log_return(series: TimeSeries):
    total = sum(value for _, value in series.returns(log=True))
    assert total == pytest.approx(math.log(102.96 / 100))


def test_non_positive_values_have_no_return():
    broken = TimeSeries([(date(2026, 1, 2), 10), (date(2026, 1, 5), 0), (date(2026, 1, 6), 11)])
    assert broken.returns() == []


def test_reindex_without_fill_drops_missing_dates(series: TimeSeries):
    days = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)]
    assert series.reindex(days).days == (date(2026, 1, 2), date(2026, 1, 6))


def test_reindex_carries_forward_up_to_a_limit(series: TimeSeries):
    days = [date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)]
    filled = series.reindex(days, fill=FillMethod.PREVIOUS)
    assert filled[date(2026, 1, 8)] == Decimal("99.00")

    long_gap = TimeSeries([(date(2026, 1, 2), 1), (date(2026, 1, 12), 2)])
    targets = [date(2026, 1, day) for day in range(2, 13)]
    limited = long_gap.reindex(targets, fill=FillMethod.PREVIOUS, limit=2)
    assert date(2026, 1, 4) in limited
    assert date(2026, 1, 5) not in limited  # the third consecutive fill is refused


def test_linear_fill_interpolates_in_calendar_time():
    two = TimeSeries([(date(2026, 1, 1), "100"), (date(2026, 1, 11), "110")])
    filled = two.reindex([date(2026, 1, 1), date(2026, 1, 4), date(2026, 1, 11)], fill=FillMethod.LINEAR)
    assert filled[date(2026, 1, 4)] == Decimal("103")


def test_linear_fill_does_not_extrapolate():
    two = TimeSeries([(date(2026, 1, 2), "100"), (date(2026, 1, 5), "103")])
    filled = two.reindex([date(2026, 1, 1), date(2026, 1, 6)], fill=FillMethod.LINEAR)
    assert len(filled) == 0


def test_align_keeps_only_shared_dates(series: TimeSeries):
    other = TimeSeries([(date(2026, 1, 6), 1), (date(2026, 1, 9), 2), (date(2026, 1, 12), 3)], name="other")
    left, right = series.align(other)
    assert left.days == right.days == (date(2026, 1, 6), date(2026, 1, 9))
    assert right.name == "other"


def test_scale_replace_drop_and_map(series: TimeSeries):
    assert series.scale("0.5")[date(2026, 1, 2)] == Decimal("50.000")
    replaced = series.replace({date(2026, 1, 7): "98", date(2026, 1, 8): "97"})
    assert replaced[date(2026, 1, 7)] == Decimal("98")
    assert len(replaced) == 5
    assert date(2026, 1, 6) not in series.drop([date(2026, 1, 6)])
    assert series.map(lambda _day, value: value + 1)[date(2026, 1, 2)] == Decimal("101.00")


def test_cumulative_index_and_drawdown(series: TimeSeries):
    index = dict(series.cumulative_index())
    assert index[date(2026, 1, 2)] == pytest.approx(100.0)
    assert index[date(2026, 1, 7)] == pytest.approx(99.0)
    drawdown, peak, trough = series.max_drawdown()
    assert drawdown == pytest.approx(99 / 101 - 1)
    assert (peak, trough) == (date(2026, 1, 6), date(2026, 1, 7))


def test_from_floats_rounds_back_into_decimal():
    built = TimeSeries.from_floats([date(2026, 1, 2)], [0.1 + 0.2], places=4)
    assert built[date(2026, 1, 2)] == Decimal("0.3000")
    with pytest.raises(ValidationError):
        TimeSeries.from_floats([date(2026, 1, 2)], [1.0, 2.0])


def test_merge_prefers_the_requested_series_on_overlap():
    first = TimeSeries([(date(2026, 1, 2), 1), (date(2026, 1, 5), 2)], name="a")
    second = TimeSeries([(date(2026, 1, 5), 20), (date(2026, 1, 6), 30)], name="b")
    assert merge_series([first, second])[date(2026, 1, 5)] == Decimal(2)
    assert merge_series([first, second], prefer="last")[date(2026, 1, 5)] == Decimal(20)
    with pytest.raises(ValidationError):
        merge_series([first], prefer="middle")


def test_empty_series_behaves():
    empty = TimeSeries()
    assert not empty
    assert empty.returns() == []
    assert empty.cumulative_index() == []
    assert "empty" in repr(empty)
    with pytest.raises(ValidationError):
        _ = empty.first


def test_equality_and_hash(series: TimeSeries):
    copy = TimeSeries(zip(series.days, series.values, strict=True), name="another name")
    assert copy == series
    assert hash(copy) == hash(series)


@given(
    st.lists(
        st.tuples(
            st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31)),
            st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2),
        ),
        min_size=1,
        max_size=40,
        unique_by=lambda item: item[0],
    )
)
def test_as_of_never_returns_a_future_value(points):
    built = TimeSeries(points)
    for day, _ in points:
        found = built.as_of(day)
        assert found is not None
        assert found.day <= day
        assert found.value == built[found.day]
