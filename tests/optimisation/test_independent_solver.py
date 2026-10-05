"""The rebalance solved twice, by two algorithms that share no code: an interior-point method and a first-order one.

Clarabel (interior point, second-order cone) is the house solver; SCS (operator
splitting, first-order) is the last link in the fallback chain. Solving the same
problems with each, and getting the same trades, shows the answer belongs to
the problem rather than to a solver's tolerances. A first-order method stops
short of an interior-point method's precision (SCS reports "optimal_inaccurate"),
so they are held to agree within what matters for an order: half a basis point
of NAV in any weight, a tenth of one in the objective, $5 of tax on a $1m account.
"""

from __future__ import annotations

import pytest

from meridian.optimisation import rebalance
from meridian.optimisation.rebalance import Settings

SCS_ONLY = (("SCS", {"eps_abs": 1e-10, "eps_rel": 1e-10, "max_iters": 200_000}),)
CASES = {
    "tracking": Settings(risk_aversion=10.0),
    "tax-aware": Settings(risk_aversion=20.0, harvest=False),
    "harvesting": Settings(risk_aversion=20.0, harvest=True),
    "tight budget": Settings(risk_aversion=20.0, harvest=True, te_limit=0.004),
}


@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
@pytest.mark.parametrize("name", list(CASES))
def test_two_unrelated_algorithms_find_the_same_rebalance(market, monkeypatch, name):
    settings = CASES[name]
    clarabel = market.rebalancer().solve(settings)
    monkeypatch.setattr(rebalance, "SOLVER_CHAIN", SCS_ONLY)
    scs = market.rebalancer().solve(settings)
    assert clarabel.status == "optimal"
    assert scs.objective == pytest.approx(clarabel.objective, abs=1e-5)
    for key in market.keys:
        assert scs.after[key] == pytest.approx(clarabel.after[key], abs=5e-5), key
    assert scs.tax == pytest.approx(clarabel.tax, abs=5.0)
