# 60. Performance statistics are reconciled against empyrical, and every convention is recombined

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Day 4's risk and return measures were tested against definitions written by the same
hand as the code. Performance measures have competing conventions, and two systems can
both be right while disagreeing. A difference therefore needs more than an explanation:
it needs to be shown that the explanation accounts for the whole gap.

## Decision

- `devtools.performance_reference` computes fifteen measures with Meridian and with
  empyrical (scipy for the higher moments) on two datasets: the demonstration account,
  daily, and a century of US returns, monthly.
- A measure either agrees to 1e-10, or differs by a convention listed in `CONVENTIONS`.
- For each convention, the module recombines Meridian's own building blocks the way
  empyrical computes the measure, and that figure must agree with empyrical's to 1e-10.
- empyrical-reloaded is a development dependency, as QuantLib is.

## Consequences

- 22 of 30 comparisons agree outright. The other 8 differ by four conventions, each
  reconciled exactly: calendar against count annualisation, geometric against
  arithmetic Sharpe and Sortino, and Jensen's alpha against the regression intercept.
- The reconciliation found the capture-ratio definition wrong. It now matches
  Morningstar's and empyrical's.
- Meridian keeps its own conventions where they are what a client's statement means.
