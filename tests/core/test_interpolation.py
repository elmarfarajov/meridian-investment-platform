"""Interpolation, including the shape-preserving property that motivates it."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.core.exceptions import ValidationError
from meridian.core.interpolation import (
    InterpolationMethod,
    LinearInterpolator,
    LogLinearInterpolator,
    MonotoneCubicInterpolator,
    PreviousInterpolator,
    interpolate,
    make_interpolator,
)

XS = (1.0, 2.0, 5.0, 10.0)
YS = (0.030, 0.034, 0.038, 0.041)


@pytest.mark.parametrize(
    "method",
    [
        InterpolationMethod.LINEAR,
        InterpolationMethod.LOG_LINEAR,
        InterpolationMethod.MONOTONE_CUBIC,
        InterpolationMethod.PREVIOUS,
    ],
)
def test_every_method_reproduces_the_knots(method: InterpolationMethod):
    curve = make_interpolator(XS, YS, method)
    for x, y in zip(XS, YS, strict=True):
        assert curve(x) == pytest.approx(y)


@pytest.mark.parametrize(
    "method",
    [InterpolationMethod.LINEAR, InterpolationMethod.LOG_LINEAR, InterpolationMethod.MONOTONE_CUBIC],
)
def test_extrapolation_is_flat_at_both_ends(method: InterpolationMethod):
    curve = make_interpolator(XS, YS, method)
    assert curve(0.1) == pytest.approx(YS[0])
    assert curve(40.0) == pytest.approx(YS[-1])


def test_linear_interpolation_is_the_midpoint_at_the_midpoint():
    curve = LinearInterpolator((0.0, 10.0), (1.0, 2.0))
    assert curve(5.0) == pytest.approx(1.5)


def test_log_linear_interpolation_is_geometric():
    curve = LogLinearInterpolator((0.0, 2.0), (1.0, 0.25))
    assert curve(1.0) == pytest.approx(0.5)  # the geometric mean, not 0.625
    assert curve(1.0) != pytest.approx(0.625)


def test_log_linear_needs_positive_values():
    with pytest.raises(ValidationError, match="positive"):
        LogLinearInterpolator((0.0, 1.0), (1.0, -0.5))


def test_previous_interpolation_is_a_step_function():
    curve = PreviousInterpolator((0.0, 1.0, 2.0), (10.0, 20.0, 30.0))
    assert curve(0.99) == 10.0
    assert curve(1.0) == 20.0
    assert curve(1.5) == 20.0
    assert curve(5.0) == 30.0


def test_monotone_cubic_does_not_overshoot_where_a_spline_would():
    """A step-like set of points: the interpolant must stay inside the data range."""
    xs = (0.0, 1.0, 2.0, 3.0, 4.0)
    ys = (0.0, 0.0, 1.0, 1.0, 1.0)
    curve = MonotoneCubicInterpolator(xs, ys)
    samples = [curve(x / 100) for x in range(0, 401)]
    assert min(samples) >= -1e-12
    assert max(samples) <= 1 + 1e-12


def test_monotone_cubic_is_smoother_than_linear_between_pillars():
    linear = LinearInterpolator(XS, YS)
    cubic = MonotoneCubicInterpolator(XS, YS)
    # They agree at the knots and differ in between
    assert cubic(3.5) != pytest.approx(linear(3.5))
    assert min(YS) <= cubic(3.5) <= max(YS)


def test_interpolation_validates_its_inputs():
    with pytest.raises(ValidationError, match="same number"):
        LinearInterpolator((1.0, 2.0), (1.0,))
    with pytest.raises(ValidationError, match="at least two"):
        LinearInterpolator((1.0,), (1.0,))
    with pytest.raises(ValidationError, match="increasing"):
        LinearInterpolator((2.0, 1.0), (1.0, 2.0))


def test_the_convenience_function_matches_the_class():
    assert interpolate(XS, YS, 3.0, "linear") == pytest.approx(LinearInterpolator(XS, YS)(3.0))
    assert make_interpolator(XS, YS, "flat_forward").method is InterpolationMethod.LOG_LINEAR
    assert repr(make_interpolator(XS, YS)).startswith("<LinearInterpolator")


@settings(max_examples=120, deadline=None)
@given(
    values=st.lists(st.floats(min_value=0.001, max_value=0.2), min_size=3, max_size=8),
    position=st.floats(min_value=0.0, max_value=1.0),
)
def test_monotone_cubic_preserves_monotone_data(values: list[float], position: float):
    """Given increasing data, the interpolant must itself be increasing - that is the whole point."""
    ys = sorted(values)
    xs = [float(index) for index in range(len(ys))]
    curve = MonotoneCubicInterpolator(xs, ys)
    x = position * (len(ys) - 1)
    step = 1e-4
    low = curve(max(x - step, xs[0]))
    high = curve(min(x + step, xs[-1]))
    assert high >= low - 1e-9
    assert math.isfinite(curve(x))
