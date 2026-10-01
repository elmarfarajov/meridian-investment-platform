"""Nelson-Siegel-Svensson against the Federal Reserve's own curve, and PCA against Litterman-Scheinkman."""

from datetime import date
from itertools import pairwise

import numpy as np
import pytest

from meridian.analytics.curve_pca import curve_pca, rolling_explained
from meridian.analytics.curves import bootstrap_par_curve
from meridian.analytics.parametric import NelsonSiegelSvensson, fit_par_curve
from meridian.core.exceptions import ValidationError
from meridian.marketdata.rates_history import GSW_TENORS, TENOR_YEARS, gsw_curve, par_curve_on, treasury_matrix


def test_the_formula_reproduces_every_published_gsw_yield():
    parameters, published = gsw_curve()
    worst = 0.0
    for item, row in zip(parameters, published, strict=True):
        model = NelsonSiegelSvensson.from_gsw(item.beta0, item.beta1, item.beta2, item.beta3, item.tau1, item.tau2)
        fitted = model.zero_rates(GSW_TENORS) * 100
        finite = np.isfinite(row)
        if finite.any():  # Good Friday 2008: parameters published, yields not
            worst = max(worst, float(np.max(np.abs(fitted[finite] - row[finite]))))
    assert len(parameters) > 9_000
    assert worst < 0.001  # percent: a tenth of a basis point, on every day since 1990


def test_the_short_end_is_level_plus_slope_and_the_long_end_is_level():
    model = NelsonSiegelSvensson(0.045, -0.02, 0.01, 0.005, 1.5, 12.0)
    assert model.zero_rate(1e-9) == pytest.approx(0.025, abs=1e-9)
    assert model.forwards([1e-9])[0] == pytest.approx(0.025, abs=1e-9)
    assert model.zero_rate(2_000.0) == pytest.approx(0.045, abs=1e-4)


def test_the_forward_is_the_derivative_of_the_integral():
    model = NelsonSiegelSvensson(0.04, -0.01, 0.02, -0.01, 2.0, 9.0)
    for time in (0.5, 3.0, 12.0, 25.0):
        step = 1e-5
        up, down = time + step, time - step
        slope = (model.zero_rate(up) * up - model.zero_rate(down) * down) / (2 * step)
        assert model.forwards([time])[0] == pytest.approx(slope, abs=1e-9)


def test_a_known_curve_is_recovered_from_its_own_par_yields():
    truth = NelsonSiegelSvensson(0.042, -0.015, 0.02, -0.01, 1.8, 11.0)
    tenors = [0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30]
    fit = fit_par_curve(tenors, truth.par_yields(tenors))
    assert fit.rmse_bp < 0.01
    assert np.max(np.abs(fit.model.zero_rates([1, 5, 10, 30]) - truth.zero_rates([1, 5, 10, 30]))) < 1e-5


@pytest.mark.parametrize("day", [date(2008, 9, 15), date(2019, 8, 28), date(2026, 9, 25)])
def test_svensson_fits_the_real_treasury_curve_to_a_few_basis_points(day):
    curve = par_curve_on(day)
    zeros = bootstrap_par_curve(day, curve.tenors, curve.yields, interpolation="monotone_convex")
    starting = [zeros.zero_rate(t) for t in curve.tenors]
    svensson = fit_par_curve(curve.tenors, curve.yields, starting_zeros=starting)
    nelson_siegel = fit_par_curve(curve.tenors, curve.yields, svensson=False, starting_zeros=starting)
    assert svensson.rmse_bp < 5
    assert svensson.rmse_bp <= nelson_siegel.rmse_bp + 1e-9  # the second hump can only help
    assert nelson_siegel.model.is_nelson_siegel and not svensson.model.is_nelson_siegel


def test_our_fit_and_the_fed_s_agree_to_within_the_differences_in_their_data():
    day = date(2019, 8, 28)
    curve = par_curve_on(day)
    ours = fit_par_curve(curve.tenors, curve.yields).model
    parameters, _ = gsw_curve()
    item = next(p for p in reversed(parameters) if p.day <= day)
    theirs = NelsonSiegelSvensson.from_gsw(item.beta0, item.beta1, item.beta2, item.beta3, item.tau1, item.tau2)
    # the Fed fits off-the-run coupon bonds and leaves out bills; a few basis points apart is agreement
    assert np.max(np.abs(ours.zero_rates([2, 5, 10]) - theirs.zero_rates([2, 5, 10]))) * 1e4 < 10


def test_a_fit_needs_enough_tenors():
    with pytest.raises(ValidationError):
        fit_par_curve([1, 2, 5], [0.03, 0.031, 0.032])


LABELS = ["3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]


@pytest.fixture(scope="module")
def history():
    days, yields = treasury_matrix(LABELS)
    return days, yields, [TENOR_YEARS[label] for label in LABELS]


def test_three_components_explain_nearly_all_of_36_years_of_curve_moves(history):
    days, yields, tenors = history
    result = curve_pca(days, yields, LABELS, tenors)
    assert len(days) > 9_000
    assert result.explained[0] > 0.75
    assert result.cumulative[2] > 0.95


def test_the_components_read_as_level_slope_and_curvature(history):
    days, yields, tenors = history
    loadings = curve_pca(days, yields, LABELS, tenors).loadings
    assert np.all(loadings[:, 0] > 0)  # level: every tenor moves the same way
    assert loadings[0, 1] < 0 < loadings[-1, 1]  # slope: the ends move against each other
    middle = LABELS.index("2Y")
    assert loadings[middle, 2] > max(loadings[0, 2], loadings[-1, 2])  # curvature: the belly against the wings


def test_pca_recovers_factors_it_was_given():
    rng = np.random.default_rng(3)
    tenors = np.array([0.25, 1, 2, 5, 10, 30])
    level = np.ones(6) / np.sqrt(6)
    slope = (tenors - tenors.mean()) / np.linalg.norm(tenors - tenors.mean())
    shocks = rng.normal(size=(4_000, 2)) * [8.0, 3.0]
    changes = shocks[:, :1] * level + shocks[:, 1:] * slope + rng.normal(scale=0.05, size=(4_000, 6))
    yields = np.cumsum(changes, axis=0) / 10_000
    result = curve_pca(list(range(4_000)), yields, [str(t) for t in tenors], tenors, components=2)
    assert abs(result.loadings[:, 0] @ level) > 0.99


def test_the_share_explained_is_measured_in_rolling_windows(history):
    days, yields, tenors = history
    ends, shares = rolling_explained(days[-1_500:], yields[-1_500:], LABELS, tenors, window=504, step=63)
    assert len(ends) == len(shares) > 10
    assert np.all(shares.sum(axis=1) > 0.85)


def test_pca_needs_a_matrix_with_enough_days():
    with pytest.raises(ValidationError):
        curve_pca([date(2026, 1, 1)], np.zeros((1, 3)), ["a", "b", "c"], [1, 2, 3])
    with pytest.raises(ValidationError):
        curve_pca([date(2026, 1, 1)] * 20, np.zeros((20, 3)), ["a", "b"], [1, 2])


def test_par_yields_between_coupon_dates_are_smooth_not_a_sawtooth():
    from meridian.gallery import reference_curve

    curve = reference_curve()
    model = NelsonSiegelSvensson(0.042, -0.015, 0.02, -0.01, 1.8, 11.0)
    grid = [0.55 + step / 100 for step in range(0, 950)]
    curve_jumps = max(abs(curve.par_rate(b) - curve.par_rate(a)) for a, b in pairwise(grid))
    model_yields = model.par_yields(grid)
    # a hundredth of a year apart, the par yield moves by a fraction of a basis point; the sawtooth moved it by tens
    assert curve_jumps * 1e4 < 1.0
    assert np.max(np.abs(np.diff(model_yields))) * 1e4 < 1.0
