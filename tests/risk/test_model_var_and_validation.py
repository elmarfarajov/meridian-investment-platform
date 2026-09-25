"""The risk model's decomposition, VaR, stress tests and the validation statistics."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from scipy import stats

from meridian.core import ValidationError
from meridian.risk.estimation import estimate
from meridian.risk.factors import FactorSet
from meridian.risk.forecast import RollingForecaster
from meridian.risk.model import FactorRiskModel
from meridian.risk.stress import Scenario, apply, historical_scenario, hypothetical_scenarios
from meridian.risk.universe import FactorUniverse
from meridian.risk.validation import (
    bias_statistic,
    christoffersen,
    conditional_coverage,
    confidence_band,
    exceptions,
    kupiec,
    rolling_bias,
    summarise_bias,
    traffic_light,
)
from meridian.risk.var import cornish_fisher, historical, monte_carlo, parametric, scale_horizon

FACTORS = FactorSet(("World", "Size"))


def small_model() -> FactorRiskModel:
    covariance = np.array([[1.0e-4, 1.0e-5], [1.0e-5, 4.0e-5]])
    exposures = {"A": np.array([1.0, 0.5]), "B": np.array([1.0, -1.0]), "C": np.array([0.0, 0.0])}
    specific = {"A": 4e-5, "B": 9e-5, "C": 1e-5}
    return FactorRiskModel(date(2026, 9, 18), FACTORS, covariance, exposures, specific)


def test_the_euler_decomposition_adds_up():
    model = small_model()
    weights = {"A": 0.5, "B": 0.3, "C": 0.2}
    risk = model.decompose(weights)
    covariance = model.covariance(("A", "B", "C"))
    w = np.array([0.5, 0.3, 0.2])
    assert risk.variance == pytest.approx(float(w @ covariance @ w))
    assert float(risk.asset_contributions.sum()) == pytest.approx(risk.daily)
    groups = risk.by_group()
    assert sum(groups.values()) == pytest.approx(risk.volatility)
    assert risk.factor_share == pytest.approx(risk.factor_variance / risk.variance)
    assert sum(risk.by_asset().values()) == pytest.approx(risk.volatility)
    assert risk.exposure("Size") == pytest.approx(0.5 * 0.5 - 0.3)


def test_active_risk_of_a_copy_is_zero_and_errors_are_explained():
    model = small_model()
    assert model.decompose({"A": 0.0}).variance == 0.0
    with pytest.raises(ValidationError, match="does not cover"):
        model.decompose({"Z": 1.0})
    with pytest.raises(ValidationError, match="K x K"):
        FactorRiskModel(date(2026, 1, 2), FACTORS, np.eye(3), {}, {})
    with pytest.raises(ValidationError, match="both exposures"):
        FactorRiskModel(date(2026, 1, 2), FACTORS, np.eye(2), {"A": np.zeros(2)}, {})


def test_parametric_var_and_es_are_the_normal_quantities():
    estimate = parametric(0.01, 0.99)
    assert estimate.var == pytest.approx(0.023263, abs=1e-6)
    assert estimate.es == pytest.approx(0.026652, abs=1e-6)
    assert cornish_fisher(0.01, 0.0, 0.0).var == pytest.approx(estimate.var)
    assert cornish_fisher(0.01, -0.5, 3.0).var > estimate.var  # fat left tail: a larger loss
    assert scale_horizon(estimate, 10).var == pytest.approx(estimate.var * 10**0.5)
    with pytest.raises(ValidationError, match="negative"):
        parametric(-0.1)


def test_historical_and_monte_carlo_var():
    rng = np.random.default_rng(1)
    returns = rng.normal(0, 0.01, 200_000)
    estimate = historical(returns)
    assert estimate.var == pytest.approx(0.02326, rel=0.02) and estimate.es > estimate.var
    with pytest.raises(ValidationError, match="twenty"):
        historical(returns[:5])
    exposures = np.array([[1.0], [1.0]])
    simulated, draws = monte_carlo(
        exposures, np.array([[1e-4]]), np.array([0.0, 0.0]), np.array([0.5, 0.5]), draws=200_000
    )
    assert float(np.std(draws)) == pytest.approx(0.01, rel=0.02)
    assert simulated.var == pytest.approx(0.01 * stats.t.ppf(0.99, 5) * (3 / 5) ** 0.5, rel=0.03)  # unit-variance t(5)
    assert simulated.var > parametric(0.01).var and simulated.es > parametric(0.01).es


def test_bias_statistics_and_their_band():
    rng = np.random.default_rng(2)
    z = rng.standard_normal(2000)
    low, high = confidence_band(2000)
    assert low < bias_statistic(z) < high
    assert bias_statistic(1.3 * z) > high
    summary = summarise_bias("normal", z)
    assert summary.verdict == "unbiased" and 0.8 < summary.within_band <= 1.0
    assert summarise_bias("under", 1.3 * z).verdict == "under-forecasts"
    rolling = rolling_bias(z, 100)
    assert np.isnan(rolling[98]) and np.isfinite(rolling[99])
    with pytest.raises(ValidationError, match="two outcomes"):
        bias_statistic(np.array([1.0]))


def test_var_backtests():
    assert kupiec(3, 250).p_value > 0.05 and kupiec(12, 250).rejected
    statistic = kupiec(10, 500).statistic
    expected = -2 * (10 * np.log(0.01) + 490 * np.log(0.99) - 10 * np.log(0.02) - 490 * np.log(0.98))
    assert statistic == pytest.approx(expected)
    assert kupiec(10, 500).p_value == pytest.approx(stats.chi2.sf(expected, 1))
    clustered = np.zeros(500, dtype=int)
    clustered[[100, 101, 102, 300, 301]] = 1
    spread = np.zeros(500, dtype=int)
    spread[[50, 150, 250, 350, 450]] = 1
    assert christoffersen(clustered).rejected and not christoffersen(spread).rejected
    # five exceptions in 500 days is exactly 1%: the count is right, the clustering is not
    combined, independence = conditional_coverage(clustered), christoffersen(clustered)
    assert combined.statistic == pytest.approx(independence.statistic) and combined.p_value > independence.p_value
    assert [traffic_light(n).zone for n in (4, 5, 9, 10)] == ["green", "yellow", "yellow", "red"]
    assert traffic_light(7).multiplier == pytest.approx(3.65)
    assert list(exceptions(np.array([-0.03, 0.01, -0.01]), np.array([0.02, 0.02, 0.02]))) == [1, 0, 0]
    with pytest.raises(ValidationError, match="between zero"):
        kupiec(5, 3)


def test_stress_scenarios_apply_linearly():
    factors = FactorSet(("World", "Value"))
    scenario = Scenario("down", "hypothetical", {"World": -0.2, "Value": 0.05})
    result = apply(scenario, factors, np.array([0.9, 0.5]), np.array([1.0, 0.0]))
    assert result.portfolio == pytest.approx(-0.155) and result.benchmark == pytest.approx(-0.2)
    assert result.active == pytest.approx(0.045) and result.by_group["Style"] == pytest.approx(0.025)
    assert {item.name for item in hypothetical_scenarios()} >= {"Equities -20%", "Dollar rally"}


@pytest.fixture(scope="module")
def forecast_setup():
    history = FactorUniverse(90, seed=9).generate(date(2018, 1, 1), date(2021, 12, 31))
    return history, estimate(history)


def test_estimation_and_rolling_forecasts_on_a_small_universe(forecast_setup):
    history, estimated = forecast_setup
    assert estimated.returns.shape == (len(estimated.days), 21) and 0.05 < float(estimated.r_squared.mean()) < 0.6
    forecaster = RollingForecaster(history, estimated)
    rules = {"equal": lambda grid: np.full(90, 1 / 90)}
    tracks = forecaster.run(rules, methods=("ewma", "truth"))
    ewma = summarise_bias("ewma", tracks["equal"].standardised("ewma"))
    truth = summarise_bias("truth", tracks["equal"].standardised("truth"))
    assert abs(truth.bias - 1.0) < 0.08 and abs(ewma.bias - 1.0) < 0.15
    model = RollingForecaster(history, estimated).model(300)
    assert len(model.assets) == 90 and model.factor_volatility("World") > 0.05
    with pytest.raises(ValueError, match="forward"):
        forecaster.model(10)
    crash = historical_scenario(estimated, "crash", date(2020, 2, 20), date(2020, 3, 23))
    assert crash.shocks["World"] < -0.2 and crash.start == date(2020, 2, 20)
    with pytest.raises(ValidationError, match="no factor returns"):
        historical_scenario(estimated, "none", date(2030, 1, 1), date(2030, 2, 1))
