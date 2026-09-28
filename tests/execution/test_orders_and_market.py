"""The order state machine, the simulated day, and Almgren-Chriss."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.core import ValidationError
from meridian.execution.almgren_chriss import ExecutionProblem, linear_eta
from meridian.execution.market import SESSION_MINUTES, ImpactModel, MarketDay, StockProfile, volume_profile
from meridian.execution.orders import Fill, Order, OrderStatus, Side

DAY = date(2026, 9, 21)
PROFILE = StockProfile("XYZ", 100.0, 0.02, 2_000_000.0, 4.0)


def order(quantity: float = 1_000.0, **kwargs: object) -> Order:
    return Order("O-1", "XYZ", Side.BUY, quantity, DAY, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- orders
def test_an_order_moves_through_its_fix_states():
    item = order()
    assert item.status is OrderStatus.PENDING_NEW
    item.release(0, "vwap")
    item.fill(Fill("F1", "O-1", 5, 400.0, 100.0))
    assert item.status is OrderStatus.PARTIALLY_FILLED and item.leaves == 600.0
    item.fill(Fill("F2", "O-1", 9, 600.0, 101.0))
    assert item.status is OrderStatus.FILLED and item.leaves == 0.0
    assert item.average_price == pytest.approx(100.6)
    assert [event.status for event in item.events] == [
        OrderStatus.PENDING_NEW,
        OrderStatus.NEW,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
    ]
    item.check()


def test_illegal_events_are_refused():
    item = order()
    with pytest.raises(ValidationError, match="before the order was released"):
        item.fill(Fill("F1", "O-1", 1, 10.0, 100.0))
    item.release()
    with pytest.raises(ValidationError, match="overfills"):
        item.fill(Fill("F1", "O-1", 1, 2_000.0, 100.0))
    item.cancel(3)
    with pytest.raises(ValidationError):
        item.fill(Fill("F2", "O-1", 4, 10.0, 100.0))
    with pytest.raises(ValidationError):
        item.release()
    limited = order(limit_price=100.0)
    limited.release()
    with pytest.raises(ValidationError, match="through its limit"):
        limited.fill(Fill("F3", "O-1", 1, 10.0, 100.5))
    with pytest.raises(ValidationError):
        Order("O-2", "XYZ", Side.SELL, 0.0, DAY)


def test_an_order_left_unfinished_expires_with_its_leaves():
    item = order()
    item.release()
    item.fill(Fill("F1", "O-1", 5, 250.0, 100.0))
    item.expire(389)
    assert item.status is OrderStatus.EXPIRED and item.leaves == 0.0 and item.fill_rate == 0.25
    item.expire(389)  # a done order stays done
    assert Side.SELL.sign == -1


@settings(max_examples=60, deadline=None)
@given(st.lists(st.floats(min_value=1.0, max_value=500.0), min_size=1, max_size=12))
def test_the_average_price_is_the_fill_weighted_mean(prices):
    item = order(quantity=float(len(prices)) * 10)
    item.release()
    for number, price in enumerate(prices):
        item.fill(Fill(f"F{number}", "O-1", number, 10.0, price))
    assert item.average_price == pytest.approx(float(np.mean(prices)))
    assert item.status is OrderStatus.FILLED
    item.check()


# ---------------------------------------------------------------------- the market
def test_the_volume_curve_is_a_u_that_sums_to_one():
    profile = volume_profile()
    assert profile.sum() == pytest.approx(1.0)
    assert profile[0] > profile[SESSION_MINUTES // 2] < profile[-1]
    assert profile[-1] > profile[0]  # the close is heavier than the open


def test_a_day_is_reproducible_and_scaled_to_the_stock():
    first, second = MarketDay.simulate(PROFILE, seed=3), MarketDay.simulate(PROFILE, seed=3)
    np.testing.assert_allclose(first.unimpacted, second.unimpacted)
    assert first.volumes.sum() == pytest.approx(PROFILE.average_volume, rel=0.8)
    days = [MarketDay.simulate(PROFILE, seed=seed) for seed in range(300)]
    moves = np.log([day.unimpacted[-1] / day.open_price for day in days])
    assert np.std(moves) == pytest.approx(PROFILE.daily_volatility, rel=0.15)


def test_a_trade_pays_spread_and_impact_and_moves_the_price_for_the_rest_of_the_day():
    market = MarketDay.simulate(PROFILE, seed=1)
    before = market.mid(200)
    record = market.trade(100, 20_000.0, +1)
    assert record is not None and record.price > record.mid
    assert record.price / record.mid - 1 == pytest.approx(record.half_spread + record.temporary)
    assert market.mid(200) > before  # permanent impact
    assert market.mid(100) == pytest.approx(record.mid)  # but not in the bar it traded in
    assert market.trade(101, 20_000.0, +1, limit=record.mid * 0.9) is None  # the limit refuses the fill
    assert ImpactModel().temporary_cost(0.02, 0.0, 100.0) == 0.0
    with pytest.raises(ValidationError):
        StockProfile("BAD", 0.0, 0.02, 1.0, 1.0)


# ---------------------------------------------------------------------- Almgren-Chriss
def problem() -> ExecutionProblem:
    return ExecutionProblem(
        shares=100_000.0, horizon=390.0, intervals=39, sigma=0.05, eta=2e-4, gamma=1e-6, epsilon=0.02
    )


def test_the_risk_neutral_trader_trades_evenly_and_urgency_front_loads():
    base = problem()
    even = base.trades(0.0)
    assert np.allclose(even, even[0])
    urgent = base.trades(1e-5)
    assert urgent[0] > urgent[-1]
    assert base.holdings(1e-5)[0] == pytest.approx(100_000.0) and base.holdings(1e-5)[-1] == pytest.approx(0.0)
    assert base.half_life(1e-5) < base.half_life(0.0)


def test_the_frontier_trades_expected_cost_for_variance():
    frontier = problem().frontier(np.array([0.0, 1e-7, 1e-6, 1e-5, 1e-4]))
    costs = [point[1] for point in frontier]
    risks = [point[2] for point in frontier]
    assert costs == sorted(costs) and risks == sorted(risks, reverse=True)


def test_linear_eta_matches_the_square_root_law_at_the_order_rate():
    eta = linear_eta(0.35, 0.02, 100.0, 50.0, 5_000.0)
    assert eta * 50.0 == pytest.approx(100.0 * 0.35 * 0.02 * np.sqrt(50.0 / 5_000.0))
    with pytest.raises(ValidationError):
        ExecutionProblem(1.0, 10.0, 10, 0.1, eta=1e-9, gamma=1.0)
