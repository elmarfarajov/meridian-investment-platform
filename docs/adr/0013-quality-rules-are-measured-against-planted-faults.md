# 13. Quality rules are measured against planted faults in a synthetic market

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

A data quality rule is easy to write and hard to evaluate. On real data nobody knows
which prints were wrong, so a rule set is usually judged by whether its findings look
plausible - which says nothing about what it missed or how much of what it flagged
was noise. A rule that fires too often is eventually ignored, which is worse than not
having it.

The platform also cannot depend on a paid data feed, and tests cannot depend on the
network.

## Decision

- A seeded synthetic market provides the data. It reproduces the stylised facts a
  rule must survive: Student-t(5) innovations for fat tails, GARCH(1,1) volatility
  clustering with parameters that keep the fourth moment finite, market and sector
  factors for correlation, one exchange calendar per instrument, and corporate
  actions that move the quoted price.
- A fault injector damages clean data in the nine ways real feeds fail - stale runs,
  bad ticks, missing days, unrecorded splits, unit errors, crossed quotes, prints on
  closed days, zero prices and broken FX triangles - and records exactly where.
- The rules are scored on **recall** (planted faults found) and **precision**
  (findings that were real). Both are asserted in the test suite and drawn in the
  gallery.
- Statistical rules use trailing median/MAD windows on event-adjusted returns net of
  a leave-one-out market proxy, and never look at days after the one being judged.

## Consequences

- Over 126 faults planted in three independently seeded markets, recall is 100% and
  precision 97%. The false alarms are genuine fat-tailed market moves, which is what
  they would be on a real desk; raising thresholds to remove them would start to miss
  real faults.
- Synthetic data is only as realistic as the generator. The calibration is itself
  tested - realised volatility against specification across seeds, excess kurtosis,
  autocorrelation of squared returns - and a first version with Student-t(4)
  innovations failed that test, which is how the fourth-moment condition was found.
- The same harness evaluates any new rule before it is switched on.
