# 59. The demonstration Treasury accrues actual/actual (ICMA)

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The demonstration book holds one US Treasury note, 2.875% 15 May 2032. It inherited
the security master's default day count, 30/360 US. That is a corporate and agency
convention. Treasuries accrue actual/actual (ICMA). The Day 1 revisit found the
mismatch and deferred the fix, because it moves every figure in the demonstration book
that depends on accrued interest.

## Decision

`US-T-2032` carries `DayCountConvention.ACT_ACT_ICMA`. The default for a `Bond`
stays 30/360 US, because most of the bond universe a wealth platform holds is
corporate.

## Consequences

- Accrued interest on the test purchase, settling 3 February 2026 on $250,000 face,
  is $1,588.40 rather than $1,557.29.
- One figure the tests state moved: the largest Microsoft purchase the Day 6 hard limits
  allow, from $85,978 back to $85,976. The test and the documents that quote it were
  updated in the same change.
