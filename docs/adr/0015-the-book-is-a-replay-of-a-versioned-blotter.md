# 15. The book is a replay of a versioned blotter; a correction is a replay, not an edit

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

Trades are booked and then corrected: a price is keyed wrongly, a quantity allocated
to the wrong account, a trade cancelled. Every correction raises three questions that
an edited record cannot answer - what did the book say on the evenings in between,
which reports went out on the wrong number, and by how much.

A correction to an old trade also changes things that happened after it: which lots a
later sale relieved, the gain it realised, whether a later loss was a wash sale.
Patching the ledger with reversing entries for each of those consequences is
error-prone, because the consequences are the lot engine's to work out, not a
person's.

## Decision

- The **blotter** keeps every version of every transaction - booked, amended,
  cancelled - stamped with the moment it was recorded, exactly as market data keeps
  every observation (ADR 0009). Nothing is edited.
- The **book is a pure function** of the blotter as known at a moment:
  `engine.run(blotter.as_known_at(t))` reproduces the ledger, the lots, the realised
  gains and the valuations exactly as they stood at `t`.
- A **restatement** is the difference between two replays. What a report said on an
  evening is the replay as known that evening, valued that day.
- Settlement fails are recorded on the blotter with their contractual and actual
  dates; an open fail keeps the cash and the securities where they were.

## Consequences

- The engine must be deterministic and fast enough to replay on demand. The
  demonstration history - 94 transactions, 190 journal entries, two and a half years
  - replays in a few hundredths of a second, so the restatement chart rebuilds the
  book for every evening in its window.
- In the demonstration a trade booked 1% too high is corrected at month-end against
  the broker confirmation: fifteen evening NAVs were understated by 620.83 dollars,
  the lot's cost falls by the same amount, and the charts show both.
- Persisting a book replaces what was stored for the portfolio; the transactions are
  the only appended input. Stale derived rows can never outlive a correction.
