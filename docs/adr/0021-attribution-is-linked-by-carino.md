# 21. Multi-period attribution is linked by Cariño, and stored per period

- **Status:** Accepted
- **Date:** 2026-09-25

## Context

Daily effects add up to each day's active return. Over a period they do not add up to
the period's active return, because returns compound. On the demonstration account the
plain sum misses by 16 bp. A report that shows effects not summing to the active return
invites the question "where is the rest?". Adding a "residual" line hides the problem
instead of solving it.

The candidates were Cariño (logarithmic smoothing), Menchero (optimised smoothing) and
GRAP/Frongello (recursive, order-dependent).

## Decision

- Link by **Cariño**. Each day's effects are scaled by `k_t / K`, where
  `k_t = [ln(1 + R_t) - ln(1 + B_t)] / (R_t - B_t)`, `K` is the same over the whole
  period, and the limit `1 / (1 + R)` is used when the returns are equal.
- The same linking is used for holding contributions (against a zero benchmark) and
  for each month of the monthly calendar.
- Linked effects are **stored per report period** (since inception and each calendar
  year, by sector and by region), never summed across periods.
- The size of the unlinked gap is reported next to the linked effects.

## Consequences

- Linked effects sum to `R - B` exactly; the residual is float rounding (about 1e-15).
- Cariño is symmetric in time and does not depend on the order of the days, unlike
  GRAP. It is also closed-form and simple to explain. The scale factors on the
  demonstration account lie between 0.91 and 0.96, so no single day is distorted.
- Because linking is period-specific, the database holds one set of effects per report
  period, and each stored period is checked against its relinked active return.
