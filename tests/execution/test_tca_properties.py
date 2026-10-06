"""The shortfall decomposition property-tested: any order, algorithm, start and side, with or without a limit."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.execution.algorithms import ALGORITHMS, AlgoParams, execute
from meridian.execution.market import MarketDay, StockProfile
from meridian.execution.orders import Order, OrderStatus, Side
from meridian.execution.tca import analyse

PROFILE = StockProfile("XYZ", 100.0, 0.02, 2_000_000.0, 4.0)


@settings(max_examples=200, deadline=None)
@given(
    st.sampled_from(ALGORITHMS),
    st.sampled_from([Side.BUY, Side.SELL]),
    st.integers(100, 400_000),
    st.integers(0, 300),
    st.integers(30, 390),
    st.one_of(st.none(), st.floats(0.97, 1.03)),
    st.integers(0, 10_000),
)
def test_the_components_add_up_to_the_shortfall_from_the_fills(algorithm, side, quantity, start, length, limit, seed):
    market = MarketDay.simulate(PROFILE, seed=seed)
    end = min(start + length, 390)
    limit_price = None if limit is None else 100.0 * limit
    order = Order("P-1", "XYZ", side, float(quantity), date(2026, 9, 21), decision_price=100.0, limit_price=limit_price)
    result = execute(order, market, AlgoParams(algorithm, start=start, end=end))
    cost = analyse(result)  # checks that the seven components add up to the shortfall from the fills
    sign = side.sign
    direct = sign * sum(r.quantity * (r.price - 100.0) for r in result.records)
    direct += sign * (quantity - cost.filled) * (market.close - 100.0) + cost.fees
    assert cost.shortfall == pytest.approx(direct, rel=1e-9, abs=1e-6)
    assert cost.spread >= 0 and cost.temporary >= 0 and cost.permanent >= -1e-9  # our own trades never help us
    assert cost.arrival == market.arrival(start)
    assert result.parent.status in (OrderStatus.FILLED, OrderStatus.EXPIRED)
