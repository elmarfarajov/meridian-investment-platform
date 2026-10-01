"""Monotone convex interpolation: the five properties Hagan and West ask of a curve builder."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.core.daycount import DayCountConvention, year_fraction
from meridian.core.exceptions import ValidationError
from meridian.core.interpolation import make_interpolator
from meridian.core.monotone_convex import MonotoneConvex

NODES = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0)


def _from_discrete(times, forwards):
    """Zero rates whose discrete forwards on each interval are the given values."""
    total, previous, rates = 0.0, 0.0, []
    for time, forward in zip(times, forwards, strict=True):
        total += forward * (time - previous)
        previous = time
        rates.append(total / time)
    return rates


positive_forwards = st.lists(st.floats(0.0005, 0.09), min_size=len(NODES), max_size=len(NODES))


@settings(max_examples=150, deadline=None)
@given(positive_forwards)
def test_every_input_reprices_exactly(forwards):
    rates = _from_discrete(NODES, forwards)
    curve = MonotoneConvex(NODES, rates)
    for time, rate in zip(NODES, rates, strict=True):
        assert curve.integral(time) == pytest.approx(time * rate, abs=1e-14)


@settings(max_examples=150, deadline=None)
@given(positive_forwards)
def test_the_forward_curve_is_continuous_at_the_nodes(forwards):
    curve = MonotoneConvex(NODES, _from_discrete(NODES, forwards))
    for time in NODES[:-1]:
        assert curve.forward(time - 1e-10) == pytest.approx(curve.forward(time + 1e-10), abs=1e-7)


@settings(max_examples=150, deadline=None)
@given(positive_forwards)
def test_positive_discrete_forwards_give_positive_forwards_everywhere(forwards):
    curve = MonotoneConvex(NODES, _from_discrete(NODES, forwards))
    assert min(curve.forward(step / 40) for step in range(1, 40 * 30)) >= 0


def test_without_the_collar_positivity_can_fail():
    forwards = [0.001, 0.08, 0.001, 0.08, 0.001, 0.08, 0.001, 0.08, 0.001, 0.08]
    raw = MonotoneConvex(NODES, _from_discrete(NODES, forwards), positive=False)
    assert min(raw.forward(step / 40) for step in range(1, 40 * 30)) < 0


def test_a_bump_moves_the_forwards_only_nearby():
    forwards = [0.04, 0.041, 0.042, 0.043, 0.044, 0.045, 0.046, 0.047, 0.048, 0.049]
    base = MonotoneConvex(NODES, _from_discrete(NODES, forwards))
    bumped_forwards = list(forwards)
    bumped_forwards[5] += 0.0001  # the discrete forward from 3y to 5y
    bumped = MonotoneConvex(NODES, _from_discrete(NODES, bumped_forwards))
    # forwards beyond the neighbouring intervals (from 10y on) do not move at all
    for time in (12.0, 15.0, 25.0):
        assert bumped.forward(time) == pytest.approx(base.forward(time), abs=1e-15)
    assert bumped.forward(4.0) != base.forward(4.0)


def test_a_flat_curve_stays_flat():
    curve = MonotoneConvex(NODES, [0.035] * len(NODES))
    for time in (0.1, 1.5, 6.0, 25.0, 40.0):
        assert curve.forward(time) == pytest.approx(0.035, abs=1e-15)
        assert curve.zero_rate(time) == pytest.approx(0.035, abs=1e-15)


def test_one_node_is_a_flat_forward():
    curve = MonotoneConvex([2.0], [0.03])
    assert curve.forward(0.5) == pytest.approx(0.03)
    assert curve.integral(4.0) == pytest.approx(0.12)


def test_nodes_must_be_positive_and_increasing():
    with pytest.raises(ValidationError):
        MonotoneConvex([1.0, 1.0], [0.03, 0.03])
    with pytest.raises(ValidationError):
        MonotoneConvex([0.0, 1.0], [0.03, 0.03])
    with pytest.raises(ValidationError):
        MonotoneConvex([], [])


def test_the_generic_factory_refuses_a_curve_only_method():
    with pytest.raises(ValidationError, match="interpolates forwards"):
        make_interpolator([1, 2], [3, 4], "monotone_convex")


@pytest.mark.parametrize(
    ("start", "end", "us", "bond_basis"),
    [
        (date(2025, 2, 28), date(2025, 8, 31), 180, 183),  # the February start counts as the 30th
        (date(2024, 2, 29), date(2025, 2, 28), 360, 359),  # both ends are February month ends
        (date(2025, 2, 28), date(2030, 5, 29), 1889, 1891),
        (date(2025, 1, 31), date(2025, 3, 31), 60, 60),  # the 31st rules agree
        (date(2025, 3, 15), date(2025, 9, 15), 180, 180),
    ],
)
def test_30_360_us_has_the_february_rules_that_bond_basis_lacks(start, end, us, bond_basis):
    assert year_fraction(start, end, DayCountConvention.THIRTY_360_US) == Decimal(us) / 360
    assert year_fraction(start, end, DayCountConvention.THIRTY_360_BOND_BASIS) == Decimal(bond_basis) / 360
