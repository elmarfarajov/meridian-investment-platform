# 25. Specific risk by EWMA without Bayesian shrinkage; a fund's basis is its own risk

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Specific risk is most of an active portfolio's tracking error: 5.2 of the account's 5.8
points. Two choices had to be made.

- **Shrinkage.** Barra's USE4 shrinks each stock's specific volatility towards the
  average of its size decile, as a remedy for noisy short-window estimates.
- **Index funds.** Looking a fund through to its index explains its exposures, but not
  its tracking of that index.

Both were first built one way, and changed after the backtest measured them.

## Decision

- Specific variance is an **EWMA of daily specific returns, 63-day half-life, without
  shrinkage**. Bayesian shrinkage is implemented and kept as a documented, tested
  alternative, off by default.
- Each index fund held is split into its **look-through** (the constituents, in index
  weights) and its **basis** (the fund's return less the look-through's), and the basis
  is an asset of its own with EWMA specific risk.

## Consequences

- Shrinkage failed both tests. On the estimation universe it widened the spread of the
  stocks' own bias statistics more than fourfold (0.016 → 0.069). On the account it
  raised the tracking error bias from 1.07 to 1.22 (MRAD 0.105 → 0.260), because the
  universe's size deciles are the wrong prior for the account's mega-caps.
- Without a basis line the tracking error was under-forecast (bias 1.18). With it, the
  two funds' tracking risk is visible in the report: the US fund's basis is the
  fourth-largest contributor to tracking error.
- The rejected variants stay in the code with their evidence (`DemoRisk.with_shrinkage`,
  the specific-risk chart), so the decision can be re-examined when the data changes.
