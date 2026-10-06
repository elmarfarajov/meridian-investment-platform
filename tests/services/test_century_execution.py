"""Almgren-Chriss liquidation on a century of real daily prices: does the promised spread of cost hold?"""

from __future__ import annotations

import math

import numpy as np
import pytest

from meridian.execution.almgren_chriss import ExecutionProblem
from meridian.services import century_execution as century

PAPER = "the paper's"


def test_correlated_moves_make_a_held_position_riskier():
    problem = ExecutionProblem(1e6, 5.0, 5, 0.95, 2.5e-6, 2.5e-7, 0.0625)
    x = problem.holdings(1e-6)[1:]
    base = problem.sigma**2 * problem.tau * float(x @ x)
    assert problem.variance(1e-6) == pytest.approx(base)
    assert problem.variance(1e-6, 0.3) == pytest.approx(base + 2 * 0.3 * problem.sigma**2 * float(x[:-1] @ x[1:]))
    assert problem.variance(1e-6, -0.3) < base < problem.variance(1e-6, 0.3)


def test_on_a_random_walk_with_known_volatility_the_bound_holds_one_week_in_twenty():
    """The test itself, on data where the model is true: the coverage must come out at 5%."""
    rng = np.random.default_rng(7)
    returns = 0.012 * rng.standard_normal(60_000)
    years = np.full(len(returns), 2000)
    known = century.weeks("random walk", returns, years, known=0.012)
    for schedule in century.SCHEDULES:
        assert century.coverage(known.z[schedule]).p_value > 0.05
    # forecast by EWMA instead, the forecaster's own error alone breaks the bound a little more often
    forecast = century.coverage(century.weeks("random walk", returns, years).z[PAPER]).rate
    assert 0.053 < forecast < 0.062


@pytest.fixture(scope="module")
def weeks():
    return century.century("ewma")


def test_the_bound_broke_more_often_than_promised_over_the_century(weeks):
    market = weeks[0]
    assert market.name == "Market" and len(market.starts) > 5_000
    sold = century.coverage(market.z[PAPER])
    assert 0.065 < sold.rate < 0.075 and sold.p_value < 0.001  # 5% promised
    assert np.std(market.z[PAPER]) > 1.1  # the random walk understates the spread by more than a tenth


def test_the_1970s_were_the_worst_decade_because_daily_returns_moved_together(weeks):
    decades = century.by_decade(weeks[0], PAPER)
    assert max(decades, key=lambda d: decades[d].rate) == 1970 and decades[1970].rate > 0.10
    returns = century.french_daily().market
    years = np.array([day.year for day in century.french_daily().days])
    assert century.variance_ratio(returns[(years >= 1970) & (years < 1980)]) > 1.4
    assert century.variance_ratio(returns[years >= 2000]) < 1.0


def test_restating_the_variance_for_autocorrelation_brings_coverage_most_of_the_way_back(weeks):
    raw = century.coverage(century.pooled(weeks, PAPER)).rate
    corrected = century.coverage(century.pooled_corrected(weeks, PAPER)).rate
    assert raw > 0.06 and 0.05 < corrected < 0.056  # what is left is fat tails and forecast error
    seventies = century.by_decade(weeks[0], PAPER, corrected=True)[1970].rate
    assert seventies < 0.08


def test_buyers_broke_the_bound_more_than_sellers_because_the_market_rose(weeks):
    pooled = century.pooled(weeks, PAPER)
    assert century.coverage(pooled, "buy").rate > century.coverage(pooled, "sell").rate
    assert np.mean(weeks[0].z[PAPER]) < 0  # a seller's cost came in under its mean: prices drifted up
    assert math.isclose(len(pooled), 13 * len(weeks[0].starts), rel_tol=0.01)
