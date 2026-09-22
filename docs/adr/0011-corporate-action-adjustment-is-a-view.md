# 11. Corporate action adjustment is a view, never an overwrite

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

A price history that crosses a split or a dividend has to be adjusted before any
analytical use, or a 4-for-1 split looks like a 75% loss. Many systems adjust the
stored history in place when an event is loaded.

That makes three things impossible: matching a historical price to a trade
confirmation or a client statement, which show the price as quoted; correcting an
event that was loaded with the wrong ratio or date, because the original prices are
gone; and loading an event late, because the history has to be rewritten in a
particular order that nobody remembers.

## Decision

- The raw history is stored exactly as quoted and is never adjusted in place.
- Adjusted histories are derived on demand from the raw history and the event list
  by `adjust_history`, using CRSP-style multiplicative factors applied to every price
  before each ex-date. The adjusted series ends at the unadjusted latest price.
- Two views are offered because they answer different questions: **capital**
  (splits, stock dividends, spin-offs, rights) for price return, and **total return**
  (capital events plus cash dividends, equivalent to reinvesting on the ex-date) for
  performance and risk.
- The quality engine scores event-adjusted returns, so a recorded split is not an
  outlier; an *unrecorded* one is caught by the jump rule because its ratio matches a
  split and no event explains it.

## Consequences

- Correcting or adding an event changes every adjusted number consistently, with no
  data migration.
- Adjustment costs a pass over the history each time it is asked for. At end-of-day
  frequency this is microseconds; a cache keyed on the event list's version is the
  optimisation if it is ever needed.
- The total-return adjustment is tested against the synthetic market's own economic
  value, through two splits and three dividends, to within 5 bp - the rounding of
  two-decimal prices.
