# 10. The golden copy is the highest-ranked source within tolerance of the consensus

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

The platform takes prices from several sources, and none is right every day. Three
policies are common:

1. **Source hierarchy.** Take the exchange close if there is one, else the vendor,
   else the evaluated price. Simple and explainable, but a single bad print from the
   top source goes straight into the book.
2. **Median.** Robust to any one bad source, but the published price may be a number
   no vendor sent, which is hard to defend to an auditor or a client.
3. **Hierarchy checked by consensus.** Rank the sources, but only let a source win if
   it agrees with the others.

## Decision

Policy 3, with the median available as a configurable alternative.

- Values withheld by the quality engine are excluded first, per source and day.
- The consensus is the median of the remaining values. Sources more than
  `tolerance_bps` (25 bp by default) from it are excluded and the day is flagged as a
  **price challenge**, with the reason recorded.
- The highest-ranked source inside the tolerance is published.
- If no two sources agree, nothing is published for that day - a missing price is
  visible, a wrong one is not.
- **Stale consensus is guarded against.** A source whose value is unchanged from its
  own previous close is set aside whenever another source did move. This rule was
  added after charting the golden copy against the synthetic truth showed a 254 bp
  error: two vendors had both resent the previous close, agreed with each other and
  outvoted the one vendor that was right.

## Consequences

- On the demonstration market no published price is more than 13 bp from the truth,
  against worst days of 670 to 990,000 bp for the individual sources.
- Every published price records its source, the candidates, what was excluded and
  why - the audit trail a pricing committee reviews.
- The tolerance is one number for every instrument. A high-yield bond and a large-cap
  equity deserve different tolerances; that becomes a per-asset-class setting when
  the book contains both.
