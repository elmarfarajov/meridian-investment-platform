"""Almgren-Chriss against the paper's own example and against a direct numerical minimisation."""

from __future__ import annotations

import math

import cvxpy as cp
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.execution.almgren_chriss import ExecutionProblem

#: Almgren and Chriss (2000), Table 1: $50m of a $50 stock sold over five days, one trade a day
PAPER = ExecutionProblem(shares=1e6, horizon=5.0, intervals=5, sigma=0.95, eta=2.5e-6, gamma=2.5e-7, epsilon=0.0625)
PAPER_LAMBDA = 1e-6


def test_the_papers_example_has_kappa_of_about_six_tenths_a_day():
    # "For these parameters, we have from (19) that for the optimal strategy, kappa ~ 0.6/day, so kappa T ~ 3."
    kappa = PAPER.kappa(PAPER_LAMBDA)
    assert kappa == pytest.approx(0.607, abs=0.001)
    assert kappa * PAPER.horizon == pytest.approx(3.0, abs=0.05)
    # "the fluctuations in value would have standard deviation sqrt(V) = $2.12M" for the position held unsold
    assert PAPER.sigma * math.sqrt(PAPER.horizon) * PAPER.shares == pytest.approx(
        2.12e6, abs=0.005e6
    )  # to the paper's 3 figures


def test_the_risk_neutral_trader_sells_evenly_and_the_risk_averse_one_front_loads():
    assert PAPER.trades(0.0) == pytest.approx(np.full(5, 2e5))
    urgent = PAPER.trades(PAPER_LAMBDA)
    assert urgent[0] > 0.45e6 and np.all(np.diff(urgent) < 0)
    # E rises and V falls along the frontier
    assert PAPER.expected_cost(PAPER_LAMBDA) > PAPER.expected_cost(0.0)
    assert PAPER.variance(PAPER_LAMBDA) < PAPER.variance(0.0)


def minimise_directly(problem: ExecutionProblem, risk_aversion: float) -> np.ndarray:
    """E + lambda V minimised over the holdings by a conic solver, knowing nothing of sinh.

    Solved for the fraction of the order still held, with the objective in units
    of the even schedule's impact cost, so the solver sees a well-scaled problem
    whatever the order's size.
    """
    inner = cp.Variable(problem.intervals - 1)
    held = cp.hstack([1.0, inner, 0.0])
    trades = held[:-1] - held[1:]
    impact = problem.eta_tilde / problem.tau
    risk = risk_aversion * problem.sigma**2 * problem.tau
    scale = impact / problem.intervals  # the even schedule's impact cost per share squared
    objective = (impact * cp.sum_squares(trades) + risk * cp.sum_squares(inner)) / scale
    cp.Problem(cp.Minimize(objective)).solve(solver="CLARABEL")
    return problem.shares * np.concatenate([[1.0], inner.value, [0.0]])


@settings(max_examples=150, deadline=None)
@given(
    st.floats(1e3, 1e7),
    st.floats(1.0, 400.0),
    st.integers(2, 60),
    st.floats(0.01, 2.0),
    st.floats(1e-7, 1e-4),
    st.floats(0.0, 1.5),
    st.floats(-9.0, -3.0),
)
def test_the_closed_form_is_the_minimum(shares, horizon, intervals, sigma, eta, permanent, log_lambda):
    problem = ExecutionProblem(shares, horizon, intervals, sigma, eta, permanent * eta * intervals / horizon, 0.01)
    risk_aversion = 10**log_lambda
    closed = problem.holdings(risk_aversion)
    direct = minimise_directly(problem, risk_aversion)

    def objective(holdings: np.ndarray) -> float:
        trades = -np.diff(holdings)
        inner = holdings[1:-1]
        return float(
            problem.eta_tilde / problem.tau * trades @ trades
            + risk_aversion * problem.sigma**2 * problem.tau * inner @ inner
        )

    # no solver finds a lower objective than the closed form, and the trajectories agree to a millionth of the order
    assert objective(closed) <= objective(direct) * (1 + 1e-9)
    assert closed == pytest.approx(direct, abs=1e-6 * shares)
