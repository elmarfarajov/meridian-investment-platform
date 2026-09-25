"""The cross-sectional regression and the covariance estimators."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.covariance import LedoitWolf

from meridian.core import ValidationError
from meridian.risk.covariance import (
    EwmaState,
    condition_number,
    decay,
    ewma_covariance,
    factor_minimum_variance_weights,
    ledoit_wolf,
    ledoit_wolf_constant_correlation,
    marchenko_pastur_bounds,
    marchenko_pastur_density,
    minimum_variance_weights,
    riskless_portfolio,
    sample_covariance,
)
from meridian.risk.regression import constraint_matrix, regress


def cross_section(rng: np.random.Generator, count: int = 200):
    industries = np.zeros((count, 4))
    industries[np.arange(count), rng.integers(0, 4, count)] = 1.0
    styles = rng.standard_normal((count, 2))
    caps = rng.lognormal(0, 1, count)
    return np.ones(count), industries, styles, caps


def test_the_constraint_makes_cap_weighted_industries_sum_to_zero():
    caps = np.array([5.0, 1.0, 3.0, 0.5])
    matrix, dependent = constraint_matrix(caps)
    assert dependent == 0 and matrix.shape == (4, 3)
    assert np.allclose(caps @ matrix, 0.0)
    with pytest.raises(ValidationError, match="at least one industry"):
        constraint_matrix(np.zeros(3))


def test_the_regression_recovers_factor_returns_exactly_without_noise():
    rng = np.random.default_rng(3)
    world, industries, styles, caps = cross_section(rng)
    industry_caps = industries.T @ caps
    truth_industries = rng.normal(0, 0.01, 4)
    truth_industries -= (industry_caps @ truth_industries) / industry_caps.sum()  # satisfy the constraint
    truth = np.concatenate([[0.004], truth_industries, [0.002, -0.001]])
    returns = np.column_stack([world, industries, styles]) @ truth
    section = regress(returns, world, industries, styles, caps)
    assert np.allclose(section.factor_returns, truth, atol=1e-12)
    assert section.r_squared == pytest.approx(1.0) and np.abs(section.residuals).max() < 1e-12


def test_residuals_are_orthogonal_to_the_exposures_under_the_weights():
    rng = np.random.default_rng(4)
    world, industries, styles, caps = cross_section(rng)
    returns = rng.normal(0, 0.02, len(caps))
    section = regress(returns, world, industries, styles, caps)
    weights = np.sqrt(caps)
    assert np.allclose(styles.T @ (weights * section.residuals), 0.0, atol=1e-12)
    assert float(industries.T @ caps @ section.factor_returns[1:5]) == pytest.approx(0.0, abs=1e-12)
    assert 0.0 <= section.r_squared < 1.0 and np.all(np.isfinite(section.t_stats))
    with pytest.raises(ValidationError, match="not identified"):
        regress(returns[:5], world[:5], industries[:5], styles[:5], caps[:5])


def test_ledoit_wolf_matches_scikit_learn():
    rng = np.random.default_rng(1)
    data = rng.standard_normal((120, 40)) @ rng.standard_normal((40, 40)) * 0.01
    ours, theirs = ledoit_wolf(data), LedoitWolf().fit(data)
    assert np.allclose(ours.covariance, theirs.covariance_, atol=1e-16)
    assert ours.intensity == pytest.approx(theirs.shrinkage_, rel=1e-10)


def test_constant_correlation_shrinkage_is_a_convex_combination_with_the_right_target():
    rng = np.random.default_rng(2)
    common = rng.standard_normal((250, 1))
    data = 0.6 * common + 0.8 * rng.standard_normal((250, 30))
    shrunk = ledoit_wolf_constant_correlation(data)
    assert 0.0 <= shrunk.intensity <= 1.0
    target = shrunk.target
    vols = np.sqrt(np.diag(target))
    correlation = target / np.outer(vols, vols)
    off = correlation[~np.eye(30, dtype=bool)]
    assert np.allclose(off, off[0]) and off[0] == pytest.approx(0.36, abs=0.08)


def test_ewma_recursion_equals_the_weighted_sum():
    rng = np.random.default_rng(5)
    data = rng.normal(0, 0.01, (400, 3))
    batch = ewma_covariance(data, vol_half_life=20, correlation_half_life=20)
    lam = decay(20)
    weights = lam ** np.arange(399, -1, -1)
    direct = (data * weights[:, None]).T @ data / weights.sum()
    assert np.allclose(batch, direct, rtol=1e-10)
    with pytest.raises(ValidationError, match="at least one"):
        EwmaState.start(2).covariance()
    with pytest.raises(ValidationError, match="two observations"):
        sample_covariance(data[:1])


def test_a_singular_sample_covariance_offers_a_riskless_portfolio():
    rng = np.random.default_rng(6)
    data = rng.standard_normal((50, 80)) * 0.01
    sample = sample_covariance(data)
    riskless = riskless_portfolio(sample)
    assert riskless is not None and riskless.sum() == pytest.approx(1.0)
    assert float(riskless @ sample @ riskless) == pytest.approx(0.0, abs=1e-18)
    assert condition_number(sample) == float("inf")
    assert riskless_portfolio(ledoit_wolf(data).covariance) is None


def test_woodbury_minimum_variance_matches_the_direct_inverse():
    rng = np.random.default_rng(8)
    exposures = rng.standard_normal((60, 5))
    factor = np.cov(rng.standard_normal((200, 5)), rowvar=False) * 1e-4
    specific = rng.uniform(1e-5, 4e-5, 60)
    direct = minimum_variance_weights(exposures @ factor @ exposures.T + np.diag(specific))
    assert np.allclose(factor_minimum_variance_weights(exposures, factor, specific), direct, atol=1e-10)


def test_marchenko_pastur_density_integrates_to_one():
    low, high = marchenko_pastur_bounds(0.25)
    assert (low, high) == pytest.approx((0.25, 2.25))
    grid = np.linspace(low, high, 20_001)
    assert float(np.trapezoid(marchenko_pastur_density(grid, 0.25), grid)) == pytest.approx(1.0, abs=1e-3)
