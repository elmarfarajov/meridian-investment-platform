# 76. The rebalance is checked by an unrelated algorithm

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Every rebalance test used the solver that produced the answer. An answer that belongs
to a solver's tolerances, not to the problem, would pass.

## Decision

The test market's rebalances are solved twice:

- by Clarabel, an interior-point method;
- by SCS, first-order operator splitting.

They must agree within half a basis point of NAV in every weight. Clarabel's
occasional `optimal_inaccurate` stays accepted. On two decades of the century backtest,
7 of 973 solves ended so, and each matched a re-solve at 1e-10 tolerances to within
1e-8 of the objective.

## Consequences

- Where a solve has discrete repair rounds (wash sales, the active-share floor), a
  less precise solver can take a different path. In the demo's tax-blind rebalance,
  SCS's trace purchases set off five wash-sale repairs Clarabel never needed. Clarabel
  leads the chain for that reason, and SCS is the last resort.
