"""Yield curves: bootstrapping, discounting and scenarios.

The decisive test is the round trip. A curve bootstrapped from par yields must,
when asked for those same par yields, return them - otherwise the bootstrap and
the pricer disagree, and everything built on the curve is quietly wrong.
"""

from __future__ import annotations

from datetime import date

import pytest

from meridian.analytics.curves import (
    YieldCurve,
    bootstrap_par_curve,
    flat_curve,
    tenor_label,
)
from meridian.core.compounding import Compounding
from meridian.core.exceptions import CurveError
from meridian.core.interpolation import InterpolationMethod

VALUATION = date(2026, 9, 18)
TENORS = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
PARS = [0.0425, 0.0432, 0.0418, 0.0395, 0.0388, 0.0390, 0.0402, 0.0415, 0.0448, 0.0455]


@pytest.fixture
def curve() -> YieldCurve:
    return bootstrap_par_curve(VALUATION, TENORS, PARS, name="test curve")


def test_bootstrapping_reproduces_every_quoted_par_rate(curve: YieldCurve):
    for tenor, quoted in zip(TENORS, PARS, strict=True):
        assert curve.par_rate(tenor) == pytest.approx(quoted, abs=1e-10), tenor


def test_discount_factors_start_at_one_and_decrease(curve: YieldCurve):
    assert curve.discount_factor(0) == 1.0
    factors = [curve.discount_factor(tenor) for tenor in TENORS]
    assert factors == sorted(factors, reverse=True)
    assert all(0 < factor < 1 for factor in factors)


def test_a_date_and_a_year_fraction_give_the_same_answer(curve: YieldCurve):
    one_year = date(2027, 9, 18)
    assert curve.discount_factor(one_year) == pytest.approx(curve.discount_factor(1.0), rel=1e-3)


def test_an_upward_sloping_curve_puts_zero_above_par_and_forward_above_zero(curve: YieldCurve):
    """At the long end, where the curve rises, the ordering is par < zero < forward."""
    assert curve.par_rate(30) < curve.zero_rate(30)
    assert curve.zero_rate(20) < curve.forward_rate(20, 30)


def test_forward_rates_compound_back_to_the_discount_factors(curve: YieldCurve):
    near, far = 2.0, 5.0
    forward = curve.forward_rate(near, far, Compounding.CONTINUOUS)
    implied = curve.discount_factor(near) * pow(2.718281828459045, -forward * (far - near))
    assert implied == pytest.approx(curve.discount_factor(far), rel=1e-12)


def test_a_flat_curve_prices_a_par_bond_at_its_own_rate():
    flat = flat_curve(VALUATION, 0.04, compounding=Compounding.SEMI_ANNUAL)
    assert flat.par_rate(10, 2) == pytest.approx(0.04, abs=1e-6)
    assert flat.zero_rate(7) == pytest.approx(0.04, abs=1e-9)


def test_a_parallel_shift_moves_every_rate_by_the_same_amount(curve: YieldCurve):
    shifted = curve.shifted(25)
    for tenor in TENORS:
        assert shifted.zero_rate(tenor) - curve.zero_rate(tenor) == pytest.approx(0.0025, abs=1e-9)
    assert shifted.discount_factor(10) < curve.discount_factor(10)
    assert "+25bp" in shifted.name


def test_a_key_rate_bump_moves_one_pillar_and_leaves_the_far_ends_alone(curve: YieldCurve):
    bumped = curve.key_rate_shifted(4, 50)  # the 3y pillar
    assert bumped.rates[4] - curve.rates[4] == pytest.approx(0.005)
    assert bumped.rates[0] == curve.rates[0]
    assert bumped.rates[-1] == curve.rates[-1]


def test_key_rate_bumps_are_bounds_checked(curve: YieldCurve):
    with pytest.raises(CurveError):
        curve.key_rate_shifted(99, 10)


def test_sampling_produces_plottable_series(curve: YieldCurve):
    times, rates = curve.sample(50)
    assert len(times) == len(rates) == 50
    par_times, par_rates = curve.par_curve(2, 20)
    assert len(par_times) == 20 and all(rate > 0 for rate in par_rates)
    fwd_times, fwd_rates = curve.forward_curve(0.25, 30)
    assert len(fwd_times) == 30 and all(rate > 0 for rate in fwd_rates)


def test_the_short_end_is_quoted_as_a_money_market_rate(curve: YieldCurve):
    """Inside the first coupon period there is no coupon, so the par quote is simple interest."""
    factor = curve.discount_factor(0.25)
    assert curve.par_rate(0.25) == pytest.approx((1 / factor - 1) / 0.25, abs=1e-12)


@pytest.mark.parametrize(
    "method",
    [InterpolationMethod.LINEAR, InterpolationMethod.LOG_LINEAR, InterpolationMethod.MONOTONE_CUBIC],
)
def test_every_interpolation_method_honours_the_pillars(method: InterpolationMethod):
    built = YieldCurve(VALUATION, TENORS, PARS, interpolation=method)
    for tenor, rate in zip(TENORS, PARS, strict=True):
        assert built.zero_rate(tenor) == pytest.approx(rate, abs=1e-9), (method, tenor)


def test_interpolation_methods_disagree_between_the_pillars():
    log_linear = YieldCurve(VALUATION, TENORS, PARS, interpolation=InterpolationMethod.LOG_LINEAR)
    cubic = YieldCurve(VALUATION, TENORS, PARS, interpolation=InterpolationMethod.MONOTONE_CUBIC)
    assert log_linear.zero_rate(15) != pytest.approx(cubic.zero_rate(15), abs=1e-6)


def test_curves_validate_their_inputs():
    with pytest.raises(CurveError, match="one rate per pillar"):
        YieldCurve(VALUATION, [1.0, 2.0], [0.04])
    with pytest.raises(CurveError, match="at least one pillar"):
        YieldCurve(VALUATION, [], [])
    with pytest.raises(CurveError, match="positive"):
        YieldCurve(VALUATION, [0.0, 1.0], [0.04, 0.04])
    with pytest.raises(CurveError, match="increasing"):
        YieldCurve(VALUATION, [2.0, 1.0], [0.04, 0.04])
    with pytest.raises(CurveError, match="far date"):
        YieldCurve(VALUATION, [1.0, 2.0], [0.04, 0.04]).forward_rate(2.0, 1.0)


def test_bootstrapping_validates_its_inputs():
    with pytest.raises(CurveError, match="one par rate per tenor"):
        bootstrap_par_curve(VALUATION, [1.0, 2.0], [0.04])
    with pytest.raises(CurveError, match="at least one"):
        bootstrap_par_curve(VALUATION, [], [])
    with pytest.raises(CurveError, match="increasing maturity"):
        bootstrap_par_curve(VALUATION, [2.0, 1.0], [0.04, 0.04])


def test_tenor_labels_read_the_way_a_trader_says_them():
    assert tenor_label(0.25) == "3M"
    assert tenor_label(1) == "1Y"
    assert tenor_label(10) == "10Y"
    assert tenor_label(1.5) == "1.50Y"


def test_the_curve_describes_itself(curve: YieldCurve):
    assert "10 pillars" in repr(curve)
    assert str(curve.points()[0]).startswith("3M:")
