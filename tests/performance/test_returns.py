"""Time-weighted, money-weighted and Modified Dietz returns."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.accounting.bridge import ValueBridge
from meridian.core import ValidationError
from meridian.performance.returns import (
    DailyReturn,
    ReturnSeries,
    annualise,
    daily_returns,
    flows_of,
    link,
    modified_dietz,
    money_weighted_return,
    standard_periods,
    xirr,
)

D = date


def series(rates: list[float], start: date | None = None) -> ReturnSeries:
    start = start or D(2025, 1, 1)
    days = tuple(date.fromordinal(start.toordinal() + index + 1) for index in range(len(rates)))
    return ReturnSeries(days, tuple(rates))


def test_linking_is_geometric():
    assert link([0.10, -0.10]) == pytest.approx(-0.01)
    assert link([]) == 0.0
    assert link([0.05] * 2) == pytest.approx(0.1025)


def test_annualise_only_periods_of_a_year_or_more():
    assert annualise(0.05, D(2025, 1, 1), D(2025, 7, 1)) == 0.05
    assert annualise(0.21, D(2023, 1, 1), D(2025, 1, 1)) == pytest.approx(0.1, abs=5e-4)


def test_a_daily_return_uses_the_capital_at_risk_including_the_days_flows():
    day = DailyReturn(D(2025, 3, 3), opening=1000.0, flows=500.0, closing=1530.0, result=30.0)
    assert day.capital == 1500.0
    assert day.rate == pytest.approx(0.02)
    assert DailyReturn(D(2025, 3, 3), 0.0, 0.0, 0.0, 0.0).rate == 0.0


def test_daily_returns_come_from_the_value_bridge():
    bridge = ValueBridge(
        D(2025, 3, 3),
        D(2025, 3, 4),
        Decimal(1000),
        Decimal(1540),
        Decimal(500),
        Decimal(45),
        Decimal(0),
        Decimal(0),
        Decimal(-5),
    )
    (item,) = daily_returns([bridge])
    assert item.rate == pytest.approx(40 / 1500)
    assert flows_of([bridge]) == [(D(2025, 3, 4), 500.0)]


def test_series_arithmetic():
    s = series([0.01, -0.02, 0.03, 0.01])
    assert s.total() == pytest.approx(link([0.01, -0.02, 0.03, 0.01]))
    assert s.between(D(2025, 1, 2), D(2025, 1, 4)).rates == (-0.02, 0.03)
    assert s.index(100)[0] == (D(2025, 1, 1), 100)
    assert s.index(100)[-1][1] == pytest.approx(100 * (1 + s.total()))
    assert min(value for _, value in s.drawdowns()) == pytest.approx(-0.02)
    assert len(s) == 4 and s.start == D(2025, 1, 1)
    with pytest.raises(ValidationError, match="one rate per day"):
        ReturnSeries((D(2025, 1, 2),), ())
    with pytest.raises(ValidationError, match="strictly increasing"):
        ReturnSeries((D(2025, 1, 2), D(2025, 1, 2)), (0.0, 0.0))


def test_monthly_yearly_and_standard_periods():
    s = series([0.001] * 400, start=D(2024, 12, 31))
    months = s.monthly()
    assert months[0][0] == D(2025, 1, 31) and months[0][1] == pytest.approx(1.001**31 - 1)
    assert [year for year, _ in s.yearly()] == [2025, 2026]
    periods = {item.label: item for item in standard_periods(s)}
    assert set(periods) == {"MTD", "QTD", "YTD", "1 year", "Since inception"}
    assert periods["Since inception"].total == pytest.approx(s.total())
    assert periods["Since inception"].is_annualised
    assert periods["MTD"].annualised == periods["MTD"].total


def test_modified_dietz_on_one_day_is_the_daily_return():
    assert modified_dietz(1000, 1530, [(D(2025, 3, 4), 500)], D(2025, 3, 3), D(2025, 3, 4)) == pytest.approx(30 / 1500)


def test_modified_dietz_weights_a_flow_by_the_time_it_was_invested():
    # 1,000 at the start, 1,000 more half way through a 30-day month, 2,100 at the end
    result = modified_dietz(1000, 2100, [(D(2025, 4, 16), 1000)], D(2025, 3, 31), D(2025, 4, 30))
    assert result == pytest.approx(100 / (1000 + 1000 * 15 / 30))
    with pytest.raises(ValidationError, match="end after start"):
        modified_dietz(1, 1, [], D(2025, 1, 2), D(2025, 1, 2))
    with pytest.raises(ValidationError, match="denominator"):
        modified_dietz(0, 1, [], D(2025, 1, 1), D(2025, 1, 2))


def test_xirr_known_answers():
    assert xirr([(D(2024, 1, 1), -100), (D(2025, 1, 1), 110)]) == pytest.approx(0.0997, abs=5e-4)
    two_years = xirr([(D(2024, 1, 1), -100), (D(2026, 1, 1), 121)])
    assert two_years == pytest.approx(0.10, abs=1e-3)
    with pytest.raises(ValidationError, match="both signs"):
        xirr([(D(2024, 1, 1), 100), (D(2025, 1, 1), 110)])
    with pytest.raises(ValidationError, match="at least two"):
        xirr([(D(2024, 1, 1), -100)])


def test_money_weighted_return_penalises_money_added_before_a_fall():
    """Twice as much money is at risk in the losing year, so the IRR is below the time-weighted return."""
    start, middle, end = D(2024, 1, 1), D(2025, 1, 1), D(2026, 1, 1)
    # year one: 100 grows 20% to 120; 120 is added; year two: 240 falls 10% to 216
    mwr = money_weighted_return(100, 216, [(middle, 120)], start, end)
    twr = link([0.20, -0.10])
    assert twr == pytest.approx(0.08)
    assert mwr.period < twr
    # 100 x^2 + 120 x = 216 with x = 1 + r: r = -1.255%
    assert mwr.annual == pytest.approx(-0.01255, abs=1e-4)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.floats(min_value=-0.05, max_value=0.05), min_size=2, max_size=60))
def test_without_flows_every_method_agrees(rates):
    s = series(rates)
    closing = 1000 * (1 + s.total())
    assert modified_dietz(1000, closing, [], s.start, s.days[-1]) == pytest.approx(s.total(), abs=1e-12)
