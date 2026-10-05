# 72. The holding period is counted by the calendar

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Long-term treatment needs a holding period of "more than one year". Day 3's book of
record and Day 7's optimiser both read that as more than 365 days. Across a 29
February a year has 366 days. IRS Publication 550 gives the example: shares bought on
5 February 2024 and sold on 5 February 2025 are short-term. A 365-day count calls them
long-term. Between 2020 and 2029, 22% of purchase dates reach long-term a day later
than the count says.

## Decision

One rule, in `domain.positions`, serves the book, the optimiser and the charts.
`long_term_from(start)` is the day after the one-year anniversary of the start of the
holding period. A lot bought on 29 February has its anniversary on 28 February.
`TaxLot`, `RealisedLot` and the optimiser's `LotState` all call it.
`LONG_TERM_HOLDING_DAYS` stays only as the nominal year drawn on charts.

## Consequences

- A sale on the anniversary is short-term, whatever the year.
- The publication's example is a test, as is a property over three centuries of start
  dates: the first long-term day is 366 or 367 days on, and the day before it is not
  long-term.
- A wash-sale replacement still tacks on the sold shares' holding period in days. That
  is the statute's measure ("the period for which he held the stock").
