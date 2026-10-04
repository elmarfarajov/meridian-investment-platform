# 56. Published examples are the acceptance test for tax rules

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The Day 3 tests of the wash sale rule and UK share identification were written from the
rules, by the same hand as the code. Such tests catch slips in the code. They cannot
catch a misreading of the rule, because the same reading wrote both.

The IRS (Publication 550) and HMRC (CG51560, CG51590, HS284) publish worked examples
to explain their rules. They are the closest thing to an independent reference that
exists.

## Decision

- `devtools.tax_reference` holds the published examples as data, with their dates and
  amounts as printed. Each one runs through the engine unchanged.
- Every figure the authority states is compared with the engine's: to the cent for the
  IRS, and to the pound for HMRC, which prints whole pounds and rounds both ways.
- A published figure that does not follow from the authority's own arithmetic is
  recorded in `KNOWN_ERRATA` with the arithmetic. The engine is not bent to match it.
- A rule change that breaks a published example fails the build.

## Consequences

- 12 cases and 42 figures are checked on every commit.
- One HMRC figure (CG51590 Example 2, a pool cost of £4,236 where HMRC's own
  arithmetic gives £4,235) is documented as an erratum.
- The examples cover what the authorities chose to illustrate. Anything else still
  rests on tests written from the rules.
