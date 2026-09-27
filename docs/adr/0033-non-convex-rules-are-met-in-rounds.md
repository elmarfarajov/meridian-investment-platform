# 33. Rules that are not convex are met in rounds: wash-sale repair and the convex-concave procedure

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Two rules of the account cannot be written as convex constraints:
- **the wash-sale rule:** a stock whose loss lots are sold may not be bought. This is a
  complementarity condition;
- **a floor on active share:** a lower bound on a convex function.

A mixed-integer formulation could state both exactly. But it would lose the
interior-point solver, and with it the speed and the certificate of optimality.

## Decision

- **Wash sales by repair:**
  1. solve;
  2. bar the purchase of every stock whose loss lots are sold while it is bought;
  3. solve again.
  A loss on a lot bought within 30 days is valued at zero before the solve.
- **An active-share floor by the convex-concave procedure:**
  - Linearise active share at the signs of the active weights. `½ Σ sᵢ aᵢ` never
    exceeds it, so requiring it to clear the floor is a convex restriction that
    guarantees the floor.
  - Refine the signs from each solution until they settle.
  - Start twice, from the current portfolio's signs and from the unrestricted
    solution's, and keep the lower objective.
- Every round is recorded: what it proposed, and what the next round had to fix.
- A tracking-error budget and the cash ceiling are **soft**, priced above anything the
  risk term could gain by breaking them. When the wash-sale rule bars every substitute,
  the month is not declared infeasible. The optimiser gets as close as it can, and the
  excess is reported.

## Consequences

- The demonstration proposal settles in three rounds:
  - three names are barred by the wash-sale rule;
  - active share is held at 30.0% where the unrestricted solution would reach 12.7%;
  - the price of the floor is 0.44 percentage points of tracking error.
- The result is a **local** optimum. That is why the frontier is the lower envelope of
  two sweeps rather than one sweep's points.
- The Day 6 pre-trade metric model now re-computes active share for a proposed
  portfolio instead of carrying the morning's value. The compliance engine therefore
  sees what the optimiser did to it.
