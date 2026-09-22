"""Back-adjustment, tested against the synthetic market's known economic value."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from meridian.core.exceptions import ValidationError
from meridian.domain.corporate_actions import AdjustmentMode, dividend, split
from meridian.marketdata.adjustments import (
    adjust_history,
    adjust_quantity,
    adjusted_history,
    adjustment_factors,
    cumulative_factor,
)
from meridian.marketdata.providers import InstrumentSpec, SyntheticMarket
from meridian.marketdata.series import TimeSeries


@pytest.fixture
def raw() -> TimeSeries:
    return TimeSeries(
        [
            (date(2026, 1, 5), "400.00"),
            (date(2026, 1, 6), "404.00"),
            (date(2026, 1, 7), "101.50"),  # 4-for-1 split
            (date(2026, 1, 8), "102.00"),
            (date(2026, 1, 9), "100.00"),  # 2.00 dividend goes ex
            (date(2026, 1, 12), "101.00"),
        ],
        name="X",
    )


@pytest.fixture
def events():
    return [split("S", "X", date(2026, 1, 7), 4), dividend("D", "X", date(2026, 1, 9), "2.00", "USD")]


def test_factors_use_the_last_close_before_the_ex_date(raw, events):
    factors = adjustment_factors(raw, events)
    assert [item.action_id for item in factors] == ["S", "D"]
    assert factors[0].factor == Decimal("0.25")
    assert factors[1].cum_price == Decimal("102.00")
    assert factors[1].factor == Decimal("100") / Decimal("102")
    assert factors[1].implied_move == pytest.approx(-2 / 102)


def test_capital_mode_takes_out_the_split_but_not_the_dividend(raw, events):
    adjusted = adjust_history(raw, events, AdjustmentMode.CAPITAL)
    assert adjusted[date(2026, 1, 6)] == Decimal("101.00000000")
    assert adjusted[date(2026, 1, 8)] == Decimal("102.00000000")  # after the split, nothing to do
    assert adjusted.last.value == raw.last.value


def test_total_return_mode_takes_out_both(raw, events):
    adjusted = adjust_history(raw, events, AdjustmentMode.TOTAL_RETURN)
    returns = dict(adjusted.returns())
    assert returns[date(2026, 1, 7)] == pytest.approx(101.5 / 101 - 1)  # no -75% day
    assert returns[date(2026, 1, 9)] == pytest.approx(100 / 100 - 1, abs=1e-9)  # the dividend is not a loss
    assert adjusted.last.value == raw.last.value


def test_cumulative_factor_is_the_product_of_later_events(raw, events):
    factors = adjustment_factors(raw, events)
    assert cumulative_factor(factors, date(2026, 1, 5)) == pytest.approx(Decimal("0.25") * factors[1].factor)
    assert cumulative_factor(factors, date(2026, 1, 8)) == factors[1].factor
    assert cumulative_factor(factors, date(2026, 1, 12)) == Decimal(1)


def test_events_outside_the_series_or_for_other_instruments_are_ignored(raw):
    others = [split("Y", "OTHER", date(2026, 1, 7), 2), split("OLD", "X", date(2025, 1, 2), 2)]
    assert adjustment_factors(raw, others) == []
    assert adjust_history(raw, others).values == raw.values


def test_a_dividend_that_cannot_be_sized_raises():
    series = TimeSeries([(date(2026, 1, 9), "10")], name="X")
    with pytest.raises(ValidationError):
        adjustment_factors(series, [dividend("D", "X", date(2026, 1, 12), "12", "USD")])


def test_quantity_follows_splits_between_two_dates(events):
    assert adjust_quantity(Decimal(10), events, held_from=date(2026, 1, 5), to=date(2026, 1, 12)) == Decimal(40)
    assert adjust_quantity(Decimal(10), events, held_from=date(2026, 1, 7), to=date(2026, 1, 12)) == Decimal(10)
    with pytest.raises(ValidationError):
        adjust_quantity(Decimal(10), events, held_from=date(2026, 1, 12), to=date(2026, 1, 5))


def test_the_three_views_together(raw, events):
    views = adjusted_history(raw, events)
    assert views.raw_return() == pytest.approx(101 / 400 - 1)
    assert views.dividend_contribution() > 0
    assert views.total_return_index()[-1][1] > views.price_return_index()[-1][1]
    assert len(views.factors) == 2


def test_total_return_adjustment_recovers_the_economic_value_of_a_synthetic_share():
    """The strongest test available: the generator knows the true value of one original share."""
    spec = InstrumentSpec(
        "S",
        initial_price=480.0,
        annual_vol=0.35,
        splits=((date(2025, 6, 10), 4, 1), (date(2026, 2, 2), 3, 2)),
        dividends=((date(2024, 12, 12), 1.10), (date(2025, 9, 11), 0.30), (date(2026, 3, 12), 0.25)),
    )
    history = SyntheticMarket([spec, InstrumentSpec("B")], seed=12).generate(date(2024, 6, 3), date(2026, 6, 30))
    adjusted = adjust_history(history.raw_series("S"), history.corporate_actions, instrument_id="S")
    truth = history.economic_value["S"]
    left, right = adjusted.align(truth)
    ours = np.array(left.floats()) / float(left.last.value)
    theirs = np.array(right.floats()) / float(right.last.value)
    assert float(np.max(np.abs(ours / theirs - 1))) < 5e-4  # within rounding of two-decimal prices
    raw_moves = np.abs(np.diff(np.log(history.raw_series("S").floats())))
    assert float(raw_moves.max()) > 1.0  # the raw series really does contain the split
