"""The trade-off between tracking error and tax: an efficient frontier, and where a rebalance sits on it.

Every rebalance buys a reduction in tracking error with tax and cost. The
frontier answers "for a given tax bill, how close to the benchmark can the
account get?"

Two sweeps look for the answer:

* the **epsilon-constraint** sweep minimises tracking error with the tax
  realised capped at a budget, from the least tax any rebalance can realise
  without making the tracking error worse, to the tax a tax-blind manager
  would pay;
* the **price-of-risk** sweep minimises risk aversion x TE^2 + tax + cost
  over a ladder of risk aversions - what a manager with each view would do -
  and the tax-blind manager's rebalance closes the ladder.

With an active-share floor the problem is not convex (see :mod:`.rebalance`),
so each solve finds a local optimum and a sweep can land above the best
trade-off at some points. The frontier is therefore the **lower envelope** of
everything both sweeps found: a solution is on it when no other realises less
tax (or the same) for less tracking error. The rest are drawn as dominated.

Each solve is a full rebalance - the mandate, the cash band, the wash-sale
repair and the active-share floor all hold - so every point is a portfolio the
account could actually trade to.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from ..core.exceptions import ValidationError
from .rebalance import Rebalancer, RebalanceResult, Settings

MINIMUM_RISK_AVERSION = 1_000.0  # tracking error dominates: tax and cost are tie-breaks
TIE_BREAK = 1e-3
RISK_AVERSIONS: tuple[float, ...] = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
DOMINANCE = 1e-5  # tracking error a point must beat every cheaper point by to be on the frontier


@dataclass(frozen=True)
class FrontierPoint:
    tax_budget: float | None  # fraction of NAV; None for a price-of-risk point or an end
    result: RebalanceResult
    risk_aversion: float | None = None

    @property
    def tax(self) -> float:
        return self.result.tax

    @property
    def tracking_error(self) -> float:
        return self.result.tracking_error_after

    @property
    def cost(self) -> float:
        return self.result.cost * self.result.nav

    @property
    def turnover(self) -> float:
        return self.result.turnover


@dataclass
class Frontier:
    points: list[FrontierPoint]  # on the frontier, from the most tax saved to the least tracking error
    tracking_error_before: float
    dominated: list[FrontierPoint] = field(default_factory=list)  # found by a sweep, beaten by another point

    def tracking_errors(self) -> np.ndarray:
        return np.array([point.tracking_error for point in self.points])

    def taxes(self) -> np.ndarray:
        return np.array([point.tax for point in self.points])

    def at_tax(self, tax: float) -> float:
        """The frontier's tracking error at a tax bill: the best point realising no more tax than that."""
        affordable = [point.tracking_error for point in self.points if point.tax <= tax + 1e-9]
        return min(affordable) if affordable else float("inf")

    def excess(self, result: RebalanceResult) -> float:
        """How much more tracking error a rebalance carries than the frontier at its tax (zero: on it)."""
        return result.tracking_error_after - self.at_tax(result.tax)


def pareto(candidates: Sequence[FrontierPoint]) -> tuple[list[FrontierPoint], list[FrontierPoint]]:
    """Split points into the lower envelope (tax ascending, tracking error descending) and the rest."""
    ordered = sorted(candidates, key=lambda point: (point.tax, point.tracking_error))
    frontier: list[FrontierPoint] = []
    dominated: list[FrontierPoint] = []
    best = float("inf")
    for point in ordered:
        if point.tracking_error < best - DOMINANCE:
            frontier.append(point)
            best = point.tracking_error
        else:
            dominated.append(point)
    return frontier, dominated


def tax_frontier(
    rebalancer: Rebalancer,
    base: Settings | None = None,
    *,
    points: int = 12,
    risk_aversions: Sequence[float] = RISK_AVERSIONS,
) -> Frontier:
    if points < 3:
        raise ValidationError("a frontier needs at least three points")
    base = base or Settings()
    before = rebalancer.evaluate(rebalancer.w0)
    cheapest = rebalancer.solve(replace(base, risk_aversion=TIE_BREAK, tax_weight=1.0, te_limit=before))
    closest = rebalancer.solve(replace(base, risk_aversion=MINIMUM_RISK_AVERSION, tax_weight=TIE_BREAK))
    blind = [
        rebalancer.solve(replace(base, risk_aversion=aversion, tax_weight=0.0))
        for aversion in (base.risk_aversion, MINIMUM_RISK_AVERSION)
    ]
    candidates = [FrontierPoint(None, cheapest), FrontierPoint(None, closest)]
    candidates += [FrontierPoint(None, result) for result in blind]
    low = cheapest.tax / rebalancer.nav
    high = max(closest.tax, *(result.tax for result in blind)) / rebalancer.nav
    if high > low:
        for budget in np.linspace(low, high, points)[1:-1]:
            settings = replace(
                base, risk_aversion=MINIMUM_RISK_AVERSION, tax_weight=TIE_BREAK, tax_budget=float(budget)
            )
            candidates.append(FrontierPoint(float(budget), rebalancer.solve(settings)))
    for aversion in risk_aversions:
        candidates.append(FrontierPoint(None, rebalancer.solve(replace(base, risk_aversion=aversion)), aversion))
    frontier, dominated = pareto(candidates)
    return Frontier(frontier, before, dominated)
