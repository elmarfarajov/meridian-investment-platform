"""The faults found in the second reading of Day 5, each pinned down."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from scipy import stats

from meridian.core import ValidationError
from meridian.risk.covariance import minimum_variance_weights
from meridian.risk.estimation import estimate
from meridian.risk.exposures import standardise, standardise_against
from meridian.risk.forecast import RollingForecaster
from meridian.risk.universe import FactorUniverse
from meridian.risk.validation import cumulative_probability, traffic_light
from meridian.risk.var import cornish_fisher, monte_carlo, parametric

#: Basel Committee on Banking Supervision (1996), "Supervisory framework for the use of backtesting in
#: conjunction with the internal models approach to market risk capital requirements", Table 2:
#: exceptions in 250 days -> (zone, plus factor, cumulative probability in per cent).
BASEL_TABLE = {
    0: ("green", 0.00, 8.11), 1: ("green", 0.00, 28.58), 2: ("green", 0.00, 54.32), 3: ("green", 0.00, 75.81),
    4: ("green", 0.00, 89.22), 5: ("yellow", 0.40, 95.88), 6: ("yellow", 0.50, 98.63), 7: ("yellow", 0.65, 99.60),
    8: ("yellow", 0.75, 99.89), 9: ("yellow", 0.85, 99.97), 10: ("red", 1.00, 99.99),
}  # fmt: skip


def test_the_traffic_light_reproduces_the_basel_committee_s_table():
    for exceptions, (zone, plus, cumulative) in BASEL_TABLE.items():
        light = traffic_light(exceptions)
        assert light.zone == zone and light.multiplier == pytest.approx(3.0 + plus)
        assert round(cumulative_probability(exceptions) * 100, 2) == cumulative


def test_the_zones_follow_the_same_rule_for_any_window():
    # 500 days: the green zone ends where five exceptions did in 250
    zones = {count: traffic_light(count, 500).zone for count in range(25)}
    assert max(count for count, zone in zones.items() if zone == "green") == 8
    assert min(count for count, zone in zones.items() if zone == "red") == 15
    # a hundred days: four exceptions is already yellow, not green as the 250-day table would say
    assert traffic_light(4, 100).zone == "yellow" and traffic_light(4).zone == "green"
    with pytest.raises(ValidationError, match="between zero"):
        traffic_light(11, 10)


def test_monte_carlo_specific_risk_diversifies():
    # fifty equal holdings, no factor risk: fifty independent t(5) shocks summed are nearly normal
    count = 50
    estimate_, simulated = monte_carlo(
        np.zeros((count, 1)), np.zeros((1, 1)), np.full(count, 1e-4), np.full(count, 1 / count), draws=200_000
    )
    assert simulated.std() == pytest.approx(np.sqrt(1e-4 / count), rel=0.02)
    assert stats.kurtosis(simulated) < 0.5  # one t(5) draw for the whole book would give about 6
    normal = parametric(float(np.sqrt(1e-4 / count)))
    assert estimate_.var == pytest.approx(normal.var, rel=0.05)


def test_cornish_fisher_refuses_outside_its_domain():
    assert cornish_fisher(0.01, 0.0, 0.0).var == pytest.approx(parametric(0.01).var)
    assert cornish_fisher(0.01, -0.5, 3.0).var > parametric(0.01).var  # fat left tail: a larger loss
    with pytest.raises(ValidationError, match="domain where the Cornish-Fisher expansion is monotone"):
        cornish_fisher(0.01, 3.0, 0.0)


def test_minimum_variance_weights_survive_a_singular_matrix():
    data = np.random.default_rng(1).standard_normal((5, 10))
    singular = np.cov(data, rowvar=False)  # rank four, ten assets
    weights = minimum_variance_weights(singular)
    assert weights.sum() == pytest.approx(1.0) and np.all(np.isfinite(weights))


def test_an_asset_outside_the_universe_is_standardised_exactly_as_one_inside():
    rng = np.random.default_rng(4)
    values, caps = rng.lognormal(0, 1, 300), rng.lognormal(3, 1, 300)
    values[:5] = [40.0, 55.0, -30.0, 70.0, 0.1]  # outliers, so winsorising and re-centring both matter
    inside = standardise(values, caps)
    outside = standardise_against(values[:20], values, caps)
    assert outside == pytest.approx(inside[:20], abs=1e-12)


@pytest.fixture(scope="module")
def small_universe():
    history = FactorUniverse(60, seed=5).generate(date(2019, 1, 1), date(2021, 6, 30))
    return history, estimate(history)


def test_the_forecaster_uses_its_own_half_lives(small_universe):
    history, estimated = small_universe
    fast = RollingForecaster(history, estimated, vol_half_life=10, correlation_half_life=30, specific_half_life=20)
    default = RollingForecaster(history, estimated)
    assert "vol half-life 10d" in fast.model(200).description
    fast_z = fast.factor_z_scores()["World"]
    default_z = default.factor_z_scores()["World"]
    assert not np.allclose(fast_z, default_z)  # until the revisit both used the default half-lives
