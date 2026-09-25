"""The estimation universe and the exposures a model computes from what it can observe."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from meridian.core import ValidationError
from meridian.marketdata.providers.synthetic import demo_market
from meridian.risk.exposures import (
    ewma_weights,
    historical_beta,
    standardise,
    standardise_against,
    vasicek_shrink,
)
from meridian.risk.factors import CURRENCIES, INDUSTRIES, STYLES, WORLD, FactorSet, group_of
from meridian.risk.universe import FactorUniverse, Overlay
from meridian.services.demo_market import DEMO_END, DEMO_START


@pytest.fixture(scope="module")
def small():
    return FactorUniverse(100, seed=5).generate(date(2019, 6, 3), date(2021, 6, 30))


def test_the_factor_set_is_ordered_and_grouped():
    factors = FactorSet.standard()
    assert factors.names[0] == WORLD and len(factors) == 1 + len(INDUSTRIES) + len(STYLES) + len(CURRENCIES)
    assert [group_of(name) for name in factors.names].count("Currency") == 4
    assert factors.local[-1] == "Quality" and factors.indices("Style") == [12, 13, 14, 15, 16]


def test_the_universe_is_deterministic_and_shaped(small):
    again = FactorUniverse(100, seed=5).generate(date(2019, 6, 3), date(2021, 6, 30))
    assert np.array_equal(small.local_returns, again.local_returns)
    steps, count = small.local_returns.shape
    assert count == 100 and steps == len(small.days) and small.caps.shape == (steps, count)
    assert small.true_style_exposures.shape == (len(small.month_starts), count, len(STYLES))
    assert {stock.currency for stock in small.stocks} == {"USD", "EUR", "GBP", "CHF", "JPY"}
    with pytest.raises(ValidationError, match="at least sixty"):
        FactorUniverse(20)


def test_a_crisis_window_compounds_to_its_target(small):
    first, last = small.days.index(date(2020, 2, 20)), small.days.index(date(2020, 3, 23))
    world = float(np.expm1(small.true_factor_returns[WORLD][first : last + 1].sum()))
    assert world == pytest.approx(-0.32, abs=1e-12)
    crash_vol = np.sqrt(small.true_factor_variance[WORLD][first : last + 1]).mean()
    calm_vol = np.sqrt(small.true_factor_variance[WORLD][:first]).mean()
    assert crash_vol > 3 * calm_vol


def test_true_variance_is_the_sum_of_its_parts(small):
    weights = np.full(100, 0.01)
    day = 300
    total = small.true_variance(day, weights)
    batch = small.true_variances(day, np.column_stack([weights, 2 * weights]))
    assert batch[0] == pytest.approx(total) and batch[1] == pytest.approx(4 * total)
    assert total > float(weights**2 @ small.true_specific_variance[day])


def test_the_overlay_replays_the_day_two_market():
    draws = demo_market(7).factor_draws(DEMO_START, DEMO_END)
    assert np.allclose(draws.market, [value for _, value in demo_market(7).generate(DEMO_START, DEMO_END).market_factor])
    overlay = Overlay(draws.days, draws.market, draws.market_variance, {"Information Technology": draws.sectors["Information Technology"]}, 0.07)
    history = FactorUniverse(80, seed=3).generate(date(2023, 1, 2), DEMO_END, overlay)
    start = history.overlay_start
    assert start is not None and history.days[start] == DEMO_START
    assert np.array_equal(history.true_factor_returns[WORLD][start:], draws.market)
    # no style premia in the Day 2 market: silenced over the overlay, except beta's ride on the world
    assert np.allclose(history.true_factor_returns["Value"][start:], 0.0)
    with pytest.raises(ValidationError, match="weekday of the universe"):
        FactorUniverse(80).generate(date(2025, 1, 6), DEMO_END, overlay)


def test_standardise_centres_on_the_cap_weighted_market():
    rng = np.random.default_rng(1)
    values, caps = rng.normal(0, 3, 400), rng.lognormal(0, 1, 400)
    scores = standardise(values, caps)
    assert float(caps / caps.sum() @ scores) == pytest.approx(0.0, abs=1e-12)
    assert float(scores.std()) == pytest.approx(1.0) and np.abs(scores).max() < 4.0
    assert np.all(standardise(np.ones(10), np.ones(10)) == 0.0)
    outside = standardise_against(np.array([values.mean() + 10 * values.std()]), values, caps)
    assert outside[0] == 3.0


def test_historical_beta_recovers_a_known_slope_and_shrinks_the_uncertain():
    rng = np.random.default_rng(7)
    market = rng.normal(0, 0.01, 252)
    returns = np.column_stack([0.5 * market + rng.normal(0, 0.002, 252), 1.5 * market + rng.normal(0, 0.03, 252)])
    beta, error = historical_beta(returns, market)
    assert beta[0] == pytest.approx(0.5, abs=0.05) and error[1] > 5 * error[0]
    shrunk = vasicek_shrink(beta, error, np.ones(2))
    assert abs(shrunk[1] - beta[1]) > abs(shrunk[0] - beta[0])
    weights = ewma_weights(100, 10)
    assert weights.sum() == pytest.approx(1.0) and weights[-1] == pytest.approx(2 * weights[-11], rel=1e-9)
