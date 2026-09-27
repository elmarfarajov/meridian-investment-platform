# 31. Tax-aware rebalancing is a conic programme, solved by Clarabel through cvxpy

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

A rebalance trades off tracking error, tax and trading cost under the mandate's limits.
The options were:
- a hand-written heuristic (sell the worst lots, buy towards the target);
- a quadratic programme with a dense covariance matrix;
- a general nonlinear solver;
- a conic programme.

The heuristic cannot weigh risk against tax. The dense QP needs a covariance of every
coverage asset and cannot express x^1.5 impact. A nonlinear solver gives no certificate
of optimality.

## Decision

- The problem is written in **cvxpy** as a **conic programme**:
  - tracking error in the Day 5 model's **factor form** (a second-order cone, never a
    dense covariance);
  - tax **linear per lot**;
  - market impact as the epigraph of a **three-dimensional power cone**,
    `t^{2/3} · 1^{1/3} ≥ x`.
- It is solved by **Clarabel**, an interior-point conic solver. The fallback chain is
  Clarabel with more iterations, then SCS.
- Nothing is pinned by an equality to the edge of its cone. A barred purchase or an
  excluded stock is removed from the problem instead, because an interior-point method
  needs a feasible set with an interior.
- A 10⁻⁶ ridge on squared trades makes the optimum unique, and the objective is scaled
  to basis points.

## Consequences

- One solve takes 0.1–0.5 s for 40 assets and 31 lots, with the mandate's compilable
  rules as constraints.
- Two bugs were found by looking at why the solver was "almost" solving:
  - cvxpy's default rewriting of `x^1.5` into second-order cones stalled Clarabel in a
    third of the cases;
  - equality pins on non-negative variables made it fail outright.
  Both are formulation choices, now recorded in the code where they are made.
- cvxpy is a dependency of the library. The optimiser loads it lazily, so the CLI and
  the persistence layer do not pay its import time.
