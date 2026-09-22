# 9. Market data is bitemporal and append-only

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Every price has two dates: the day it describes and the moment the platform learned
it. Vendors correct their data - a bad print on Tuesday is fixed on Wednesday
morning, a dividend is loaded late and the history is restated. The obvious schema
keeps one row per instrument and day and updates it when a correction arrives.

That schema destroys the answer to three questions the platform must be able to
answer:

- **Audit.** A valuation from the 14th is questioned in March. What price did it use,
  and was that the price available on the 14th? With update-in-place, the price that
  was used no longer exists anywhere.
- **Reproducibility.** Re-running last month's valuation must give last month's
  number, not a number built from data corrected since.
- **Backtesting.** A strategy evaluated on today's restated history uses corrections
  nobody had at the time. That is look-ahead bias, and it flatters every backtest in
  exactly the way that is hardest to notice.

## Decision

- Raw observations are stored in `price_observations`, keyed by instrument, value
  date, price type, source **and** `recorded_at`. Rows are never updated or deleted:
  a correction is a new row with a later `recorded_at`.
- The question every reader asks is "as known at": for each value date, the latest
  row recorded on or before a given moment. `BitemporalStore` answers it in memory
  and `PriceObservationRepository.as_known_at` answers it in SQL; both are tested
  against the same cases, including a correction that must not leak into the past.
- Knowledge times are stored and compared in UTC.
- The published golden copy stays in `prices`, one row per instrument and day,
  because valuation wants one number. It is derived; the observations are the record.
- Historical loads are *backfilled*: each observation is stamped with the evening of
  its own value date, the honest assumption for end-of-day data, and the load's run
  id says that it was a backfill.

## Consequences

- Any past state of knowledge can be rebuilt exactly, and the difference between
  first print and restated value is measurable (`lookahead_error`).
- Storage grows with every resend. At end-of-day frequency this is tens of thousands
  of rows a year per source, which is nothing; intraday data would need compaction.
- Every query that wants "the price" must say *as known when*. Forgetting to say it
  means "as known now", which is the right default for operations and the wrong one
  for a backtest - the API makes the argument explicit to keep that visible.
