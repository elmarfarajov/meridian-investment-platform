"""Risk for the demonstration account: the model applied to the book, and validated."""

from __future__ import annotations

import math

import numpy as np
import pytest

from meridian.risk.comparison import summarise
from meridian.risk.validation import kupiec, summarise_bias
from meridian.services.demo_risk import BASIS_SUFFIX, BOOK_WARM_UP, build_demo_risk


@pytest.fixture(scope="module")
def risk():
    return build_demo_risk()


def test_the_universe_replays_the_book_market_to_the_last_day(risk):
    assert risk.estimated.days[-1] == risk.valuation_days[-1]
    assert 0.15 < float(risk.estimated.r_squared.mean()) < 0.35
    assert len(risk.universe.stocks) == 500


def test_weights_cover_every_holding_and_add_up(risk):
    weights = risk.portfolio_weights(risk.last)
    equity_and_cash = sum(value for key, value in weights.items() if not key.endswith(BASIS_SUFFIX))
    assert equity_and_cash == pytest.approx(1.0, abs=1e-9)
    assert set(weights) <= set(risk.coverage)
    assert sum(risk.benchmark_weights(risk.last).values()) == pytest.approx(1.0)
    assert any(key.endswith(BASIS_SUFFIX) for key in weights)  # funds carry their basis


def test_the_decompositions_add_up(risk):
    for decomposition in (risk.portfolio, risk.benchmark, risk.active):
        assert sum(decomposition.by_group().values()) == pytest.approx(decomposition.volatility, rel=1e-9)
        assert sum(decomposition.by_asset().values()) == pytest.approx(decomposition.volatility, rel=1e-9)
    assert 0.08 < risk.portfolio.volatility < 0.18 and 0.02 < risk.active.volatility < 0.09
    assert risk.active.by_group()["Specific"] > risk.active.by_group()["World"]  # stock picking dominates


def test_the_book_backtest_is_close_to_what_the_truth_would_score(risk):
    forecasts = risk.book_forecasts
    assert len(forecasts) == len(risk.valuation_days) - BOOK_WARM_UP
    total = summarise_bias("total", np.array([item.realised / item.volatility for item in forecasts]))
    truth = summarise_bias("truth", risk.market_truth_z)
    assert abs(total.bias - truth.bias) < 0.05  # the model scores what the true volatility scores
    active = summarise_bias("active", np.array([item.active / item.tracking_error for item in forecasts]))
    assert 0.95 < active.bias < 1.12
    rejected = risk.with_shrinkage()
    shrunk = summarise_bias("shrunk", np.array([item.active / item.tracking_error for item in rejected.book_forecasts]))
    assert shrunk.mrad > active.mrad  # the rejected variant is measurably worse
    exceptions = sum(item.exception for item in forecasts)
    assert exceptions <= 6 and kupiec(exceptions, len(forecasts)).statistic >= 0


def test_var_estimates_and_stress_tests(risk):
    methods = {estimate.method: estimate for estimate in risk.var_estimates}
    assert len(methods) == 4
    for estimate in methods.values():
        assert 0.005 < estimate.var < 0.05 and estimate.es >= estimate.var
    crash = next(item for item in risk.stress if item.scenario.name.startswith("February-March 2020"))
    assert crash.portfolio < -0.15 and crash.benchmark < -0.15
    equities = next(item for item in risk.stress if item.scenario.name == "Equities -20%")
    assert equities.portfolio == pytest.approx(-0.20 * risk.portfolio.exposure("World"))


def test_validation_on_the_universe(risk):
    tracks = risk.universe_tracks
    market = tracks["Cap-weighted market"]
    ewma = summarise_bias("ewma", market.standardised("ewma"))
    sample = summarise_bias("sample", market.standardised("sample"))
    truth = summarise_bias("truth", market.standardised("truth"))
    assert abs(truth.bias - 1) < 0.03 and ewma.mrad < sample.mrad and truth.mrad < ewma.mrad
    factor_bias = {name: float(np.std(values, ddof=1)) for name, values in risk.factor_z.items()}
    assert all(0.9 < value < 1.12 for value in factor_bias.values())


def test_a_factor_model_delivers_what_it_promises(risk):
    rows = {row.estimator: row for row in summarise(risk.minimum_variance)}
    assert rows["Sample"].promised == 0.0 and rows["Sample"].delivered > 0.08
    model = rows["Factor model"]
    assert 0.8 < model.ratio < 1.25 and model.delivered < rows["Ledoit-Wolf (identity)"].delivered


def test_garch_is_closest_to_the_truth(risk):
    forecasts = risk.world_volatility
    scored = ~np.isnan(forecasts["GARCH(1,1)"])
    truth = forecasts["Truth"][scored]
    errors = {
        name: float(np.abs(np.log(values[scored] / truth)).mean())
        for name, values in forecasts.items()
        if name != "Truth"
    }
    assert errors["GARCH(1,1)"] < errors["EWMA (42-day half-life)"] < errors["Equal-weighted 252 days"]
    assert all(math.isfinite(fit.long_run_volatility) for fit in risk.garch_fits)
