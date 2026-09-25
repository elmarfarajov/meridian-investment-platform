"""GARCH(1,1) through the arch package, against EWMA and the equal-weighted window."""

from __future__ import annotations

import math

import numpy as np
import pytest

from meridian.core import ValidationError
from meridian.risk.garch import ewma_forecasts, fit_garch, garch_forecasts, rolling_forecasts


def garch_path(steps: int, omega: float, alpha: float, beta: float, seed: int = 4) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    returns, variance = np.empty(steps), np.empty(steps)
    current = omega / (1 - alpha - beta)
    for day in range(steps):
        variance[day] = current
        returns[day] = math.sqrt(current) * rng.standard_normal()
        current = omega + alpha * returns[day] ** 2 + beta * current
    return returns, variance


def test_a_garch_fit_recovers_its_parameters():
    returns, _ = garch_path(4000, 2e-6, 0.08, 0.90)
    fit = fit_garch(returns)
    assert fit.alpha == pytest.approx(0.08, abs=0.03) and fit.beta == pytest.approx(0.90, abs=0.04)
    assert fit.long_run_volatility == pytest.approx(math.sqrt(2e-6 / 0.02 * 252), rel=0.25)
    with pytest.raises(ValidationError, match="a year"):
        fit_garch(returns[:100])


def test_garch_forecasts_track_the_true_variance_better_than_a_window():
    returns, variance = garch_path(2600, 2e-6, 0.08, 0.90, seed=9)
    garch, fits = garch_forecasts(returns, start=1000, refit_every=250)
    rolling = rolling_forecasts(returns)
    scored = ~np.isnan(garch)
    truth = np.sqrt(variance[scored])
    garch_error = np.abs(np.log(garch[scored] / truth)).mean()
    rolling_error = np.abs(np.log(rolling[scored] / truth)).mean()
    assert garch_error < rolling_error and len(fits) == 7
    assert np.isnan(ewma_forecasts(returns, 30)[0]) and np.all(ewma_forecasts(returns, 30)[1:] > 0)
