"""Allocation property-tested: for any block and any fill, the rules every allocation must keep."""

from __future__ import annotations

import math
from datetime import date

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from meridian.execution.allocation import AccountOrder, aggregate, allocate
from meridian.execution.orders import Fill, Side

DAY = date(2026, 9, 21)


def block_with_fill(requests: list[float], filled: float):
    orders = [
        AccountOrder(f"P{index:02d}", "XYZ", Side.BUY, quantity, 100.0) for index, quantity in enumerate(requests)
    ]
    block = aggregate(orders, DAY)[0]
    if filled > 0:
        block.order.release(0, "vwap")
        block.order.fill(Fill("F1", block.order.order_id, 1, filled, 101.25))
    return block


requests = st.lists(
    st.one_of(st.integers(1, 5_000).map(float), st.integers(2, 10_000).map(lambda half: half / 2)),
    min_size=1,
    max_size=10,
)


@settings(max_examples=1_500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(requests, st.floats(0.0, 1.0))
def test_every_filled_share_goes_to_someone_who_asked_for_it_at_one_price(asked, share):
    filled = math.floor(sum(asked) * share)
    block = block_with_fill(asked, float(filled))
    allocations = allocate(block)  # raises if a rule is broken
    allocated = sum(item.quantity for item in allocations)
    assert allocated <= filled + 1e-9  # nothing invented
    assert filled - allocated < 1.0  # and less than a share left over, for the error account
    if all(quantity == int(quantity) for quantity in asked):
        assert allocated == pytest.approx(filled, abs=1e-9)  # whole shares: nothing left over at all
    assert all(item.quantity <= item.requested + 1e-9 for item in allocations)
    assert len({item.price for item in allocations if item.quantity > 0}) <= 1


@settings(max_examples=1_500, deadline=None)
@given(st.lists(st.integers(1, 5_000), min_size=2, max_size=10), st.floats(0.05, 0.95))
def test_whole_share_requests_get_their_pro_rata_share_within_one_share(asked, share):
    filled = math.floor(sum(asked) * share)
    allocations = allocate(block_with_fill([float(q) for q in asked], float(filled)))
    booked = [item for item in allocations if item.quantity > 0]
    base = sum(item.requested for item in booked)
    for item in booked:  # among the accounts large enough to book, each is within a share of its exact part
        assert abs(item.quantity - filled * item.requested / base) < 1.0 + 1e-9
        assert item.quantity == int(item.quantity)


def test_the_case_day_8_could_not_allocate():
    """Fractional requests: the odd share by largest remainder took an account past its request, and the block failed.

    The one-share account's part is 0.9997 of a share, below the minimum, so it is
    not booked; the others take everything up to their requests, and the half
    share nobody can take goes to the error account.
    """
    allocations = allocate(block_with_fill([1, 592.5, 211, 592.5, 592, 1.5], 1990.0))
    by_account = {item.portfolio_id: item.quantity for item in allocations}
    assert by_account["P00"] == 0.0
    assert sum(by_account.values()) == pytest.approx(1989.5)
    assert all(item.quantity == item.requested for item in allocations if item.portfolio_id != "P00")
