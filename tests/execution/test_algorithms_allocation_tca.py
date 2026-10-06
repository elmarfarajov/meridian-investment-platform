"""Algorithms working orders, blocks allocated to accounts, and the shortfall decomposed."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.core import ValidationError
from meridian.execution.algorithms import ALGORITHMS, AlgoParams, execute, schedule
from meridian.execution.allocation import AccountOrder, aggregate, allocate
from meridian.execution.market import MarketDay, StockProfile
from meridian.execution.orders import Fill, OrderStatus, Side
from meridian.execution.tca import analyse, calibrate, pre_trade_estimate_bps

DAY = date(2026, 9, 21)
PROFILE = StockProfile("XYZ", 100.0, 0.02, 2_000_000.0, 4.0)


def parent(quantity: float, side: Side = Side.BUY):  # type: ignore[no-untyped-def]
    from meridian.execution.orders import Order

    return Order("P-1", "XYZ", side, quantity, DAY, decision_price=100.0)


@pytest.mark.parametrize("name", ALGORITHMS)
def test_every_algorithm_respects_its_plan_cap_and_invariants(name):
    market = MarketDay.simulate(PROFILE, seed=11)
    result = execute(parent(20_000.0), market, AlgoParams(name))
    assert result.parent.cumulative == pytest.approx(sum(record.quantity for record in result.records))
    assert sum(child.cumulative for child in result.children) == pytest.approx(result.parent.cumulative)
    for record in result.records:
        # a quarter of all the minute's volume, ours included: q / (q + V) <= 25%
        assert record.quantity / (record.quantity + market.volumes[record.minute]) <= 0.25 + 1e-9
    assert result.parent.status in (OrderStatus.FILLED, OrderStatus.EXPIRED)
    assert all(child.status in (OrderStatus.FILLED, OrderStatus.CANCELLED) for child in result.children)
    plan = schedule(AlgoParams(name), 20_000.0, market)
    assert plan[-1] == pytest.approx(1.0) and np.all(np.diff(plan) >= -1e-12)


def test_schedules_differ_as_designed():
    twap, vwap, urgent = (schedule(AlgoParams(name, urgency=4.0), 10_000.0) for name in ("twap", "vwap", "is"))
    assert twap[194] == pytest.approx(0.5, abs=0.01)
    assert urgent[100] > twap[100]  # IS front-loads
    close = schedule(AlgoParams("close"), 10_000.0)
    assert close[-11] == 0.0 and close[-1] == pytest.approx(1.0)
    assert vwap[29] > twap[29]  # the open is heavier than an even share
    with pytest.raises(ValidationError):
        AlgoParams("iceberg")
    with pytest.raises(ValidationError):
        AlgoParams(start=300, end=200)


def test_a_large_order_through_the_close_cannot_finish():
    result = execute(parent(200_000.0), MarketDay.simulate(PROFILE, seed=2), AlgoParams("close"))
    assert result.parent.status is OrderStatus.EXPIRED and result.parent.fill_rate < 0.6


def test_a_limit_price_leaves_shares_undone():
    market = MarketDay.simulate(PROFILE, seed=5)
    result = execute(parent(50_000.0), market, AlgoParams("vwap", limit_price=market.open_price * 0.995))
    assert all(record.price <= market.open_price * 0.995 for record in result.records)
    assert result.parent.fill_rate < 1.0


# ---------------------------------------------------------------------- the shortfall
@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
def test_the_shortfall_decomposes_exactly(side):
    market = MarketDay.simulate(PROFILE, seed=7)
    result = execute(parent(150_000.0, side), market, AlgoParams("pov", participation=0.1))
    cost = analyse(result)
    direct = side.sign * sum(record.quantity * (record.price - 100.0) for record in result.records)
    direct += side.sign * (cost.quantity - cost.filled) * (cost.close - 100.0) + cost.fees
    assert cost.shortfall == pytest.approx(direct)
    assert cost.spread > 0 and cost.temporary > 0 and cost.permanent > 0
    assert cost.bps(cost.shortfall) == pytest.approx(cost.shortfall_bps)
    assert cost.filled == cost.quantity and cost.opportunity == 0.0  # at 10% of volume, 7.5% of a day finishes
    assert set(cost.components()) >= {"delay", "timing", "fees"}


def test_bigger_orders_cost_more_and_the_pre_trade_model_knows_it():
    small = [
        analyse(execute(parent(2_000.0), MarketDay.simulate(PROFILE, seed=seed), AlgoParams("vwap")))
        for seed in range(10)
    ]
    large = [
        analyse(execute(parent(200_000.0), MarketDay.simulate(PROFILE, seed=seed), AlgoParams("vwap")))
        for seed in range(10)
    ]
    small_impact = np.mean([cost.bps(cost.impact) for cost in small])
    large_impact = np.mean([cost.bps(cost.impact) for cost in large])
    assert large_impact > 3 * small_impact
    assert pre_trade_estimate_bps(0.1, 0.02, 4.0, 0.35, 0.25) > pre_trade_estimate_bps(0.001, 0.02, 4.0, 0.35, 0.25)


def test_calibration_recovers_the_true_coefficient_from_measured_impact():
    rng = np.random.default_rng(0)
    costs = []
    for seed in range(60):
        size = float(np.exp(rng.uniform(np.log(0.002), np.log(0.2))))
        costs.append(
            analyse(
                execute(parent(round(size * 2_000_000.0)), MarketDay.simulate(PROFILE, seed=seed), AlgoParams("vwap"))
            )
        )
    fit = calibrate(costs, observed=False)
    assert fit.coefficient == pytest.approx(0.35, abs=0.02)
    low, high = fit.interval()
    assert low < fit.coefficient < high
    noisy = calibrate(costs, observed=True)
    assert noisy.standard_error > 10 * fit.standard_error
    with pytest.raises(ValidationError):
        calibrate(costs[:2])


# ---------------------------------------------------------------------- allocation
def account_orders() -> list[AccountOrder]:
    return [
        AccountOrder("A", "XYZ", Side.BUY, 1_000.0, 100.0),
        AccountOrder("B", "XYZ", Side.BUY, 450.0, 101.0),
        AccountOrder("C", "XYZ", Side.BUY, 2_400.0, 100.0),
        AccountOrder("A", "QQQ", Side.SELL, 300.0, 50.0),
    ]


def test_orders_aggregate_into_one_block_per_stock_and_side():
    blocks = aggregate(account_orders(), DAY)
    assert len(blocks) == 2
    xyz = next(block for block in blocks if block.order.instrument_id == "XYZ")
    assert xyz.order.quantity == 3_850.0 and xyz.requested == 3_850.0
    assert xyz.order.decision_price == pytest.approx((100_000 + 45_450 + 240_000) / 3_850)


def fill_block(block, quantity: float, prices=(100.0, 100.4)):  # type: ignore[no-untyped-def]
    block.order.release()
    half = float(int(quantity / 2))
    if half >= 1:
        block.order.fill(Fill("F1", block.order.order_id, 1, half, prices[0]))
    block.order.fill(Fill("F2", block.order.order_id, 2, quantity - half, prices[1]))


def test_a_filled_block_gives_everyone_what_they_asked_at_one_price():
    block = next(block for block in aggregate(account_orders(), DAY) if block.order.instrument_id == "XYZ")
    fill_block(block, 3_850.0)
    allocations = allocate(block)
    assert [item.quantity for item in allocations] == [1_000.0, 450.0, 2_400.0]
    assert len({item.price for item in allocations}) == 1
    assert allocations[0].price == pytest.approx(block.order.average_price)


@settings(max_examples=80, deadline=None)
@given(st.floats(min_value=1.0, max_value=3_849.0))
def test_a_partial_block_is_shared_pro_rata_in_whole_shares(filled):
    block = next(block for block in aggregate(account_orders(), DAY) if block.order.instrument_id == "XYZ")
    fill_block(block, float(int(filled)) or 1.0)
    allocations = allocate(block)
    assert sum(item.quantity for item in allocations) == pytest.approx(block.order.cumulative)
    assert all(item.quantity == int(item.quantity) and item.quantity <= item.requested for item in allocations)
    rates = [item.fill_rate for item in allocations if item.quantity > 0]
    assert max(rates) - min(rates) < 0.02 + 2 / min(item.requested for item in allocations)


def test_a_pov_order_is_its_target_share_of_all_the_volume_it_trades_in():
    market = MarketDay.simulate(PROFILE, seed=5)
    result = execute(parent(2_000_000.0), market, AlgoParams("pov", participation=0.10))
    assert result.parent.status is OrderStatus.EXPIRED  # too big to finish: it traded every minute at its rate
    assert result.participation == pytest.approx(0.10, abs=0.002)  # Day 8 traded 10% of the others' volume: 9.1%


def test_the_arrival_price_is_the_price_before_the_order_can_trade():
    market = MarketDay.simulate(PROFILE, seed=3)
    cost = analyse(execute(parent(5_000.0), market, AlgoParams("twap", start=120)))
    assert cost.arrival == pytest.approx(market.unimpacted[119])  # the end of minute 119, not of minute 120
    assert market.arrival(0) == market.open_price
