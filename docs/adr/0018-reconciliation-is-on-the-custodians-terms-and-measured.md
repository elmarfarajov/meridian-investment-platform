# 18. Reconciliation is on the custodian's terms, classified by cause, and measured

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

A daily reconciliation that raises every difference between the book and the
custodian drowns an operations team: most differences are the two parties looking at
the same thing on different dates. A reconciliation that raises only "a difference of
2,049 shares" leaves the team to work out why, every time. And, as with data quality
rules (ADR 0013), a reconciler that reports nothing on real data proves nothing -
nobody knows what it missed.

## Decision

- Compare on the **custodian's terms**: settled positions and settled cash. The book
  is read on a settlement-date basis - trade-date position less trades not yet
  settled - so the gap between trade date and settlement is never a break. A holding
  sold in full but not yet settled is still at the custodian.
- **Classify every break by cause**, by testing candidate explanations against the size
  of the difference, singly and in pairs: failed settlement, duplicate booking, a split
  applied on one side only (the quantities differ by a split ratio), a keying
  transposition (the same digits, a multiple of nine apart), income paid early or
  late, a charge on the custodian's statement with no entry in the book, and a price
  beyond tolerance. Anything else is **unexplained** and listed first.
- A **break register** carries breaks from one statement to the next and ages them.
- **Measure** the reconciler: a synthetic custodian generates statements from the book,
  prices the holdings a few basis points from the golden copy, and plants breaks where
  the answer is known.

## Consequences

- On clean statements the reconciler raises nothing, every day of the window. Over six
  months of planted breaks in seven categories it finds every one with the right cause,
  and every break it raises is one that was planted.
- Measuring it found two defects in the measurement itself before any in the
  reconciler: a break's age as of a past date used the day it later cleared, and the
  transposition generator could put a zero in front of a quantity - a keying error
  nobody makes.
- Some differences are genuinely ambiguous: if a whole holding was bought in one recent
  trade, a custodian holding twice as much is either a 2-for-1 split or a duplicate.
  The reconciler reports the first explanation that fits; the corporate action feed is
  the tie-breaker a production system would add.
