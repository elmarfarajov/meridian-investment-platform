# 19. Returns are chained daily from the value bridge, with flows at the start of the day

- **Status:** Accepted
- **Date:** 2026-09-25

## Context

A time-weighted return needs, for each sub-period, the investment result and the
capital that earned it. Two shortcuts are common. The first computes the result as
`NAV_t - NAV_{t-1} - flows`, a second, independent calculation that can disagree with
the accounting. The second uses Modified Dietz over a month, which is a money-weighted
approximation and drifts from the true time-weighted return when flows are large.

There is also a convention to choose. A deposit made on a day can be counted as capital
at risk from the start of that day, or only from its end. Either is defensible, and
reports that mix them disagree by a day's return on every flow.

## Decision

- The daily return is `result / (opening NAV + flows)`. The **result** is the Day 3
  value bridge's own total of price, currency, income and costs, never a recomputed
  difference of NAVs.
- Flows (deposits, withdrawals, transfers in kind at market value) count at the
  **start of the day**. This matches how the demonstration account invested them: a
  deposit is traded the day it arrives.
- Days are chained geometrically. Periods are annualised only when they exceed a year.
- Modified Dietz and the money-weighted return (XIRR on actual days) are computed
  alongside, as comparisons, never as substitutes.
- Returns are floats (ADR 0008). The residual between the holdings' results and the
  day's result is checked against 1e-10 before anything is stored.

## Consequences

- Every daily return reconciles to the ledger. A difference between the performance
  report and the accounts would be a bug in one of them, not a methodology gap.
- On days with no flows, the start-of-day and end-of-day conventions agree. On the
  demonstration account's three flow days, the convention is visible and documented.
- Storing daily rows lets any period be relinked in SQL without rerunning the
  accounting.
