# 73. Capital losses are netted as Schedule D nets them

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Day 7's `TaxAccount` kept the yearly tax ledger for the backtest. Day 3's
`TaxYearSummary` kept the same ledger for the book of record. They were written
separately and did not agree:

- Day 7 took the $3,000 deduction out of long-term losses as readily as short-term
  ones. Publication 550: "use your short-term capital losses first".
- Day 7 valued the deduction at the ordinary rate plus the 3.8% net investment income
  tax. The NIIT is charged on positive net investment income only, so a loss saves
  none of it.
- When a long-term loss was larger than a short-term gain, Day 7 carried the remainder
  as short-term. A net loss keeps the character of the larger side.

## Decision

`TaxAccount.close_year` nets as Schedule D does, and a property test holds it to Day
3's `TaxYearSummary` on random four-year histories: the tax each year and both
carryovers.

## Consequences

- A short-term carryover is worth more than a long-term one, so the old order
  overstated harvesting slightly in later years.
- Two ledgers remain, one in `Decimal` for the book and one in floats for the
  optimiser. They are kept honest by the test, not by sharing code.
