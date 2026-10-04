# 61. The linking method is a recorded choice among four exact methods

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Day 4 linked daily Brinson effects with Cariño's method alone. Every common linking
method is exact: the linked effects sum to the compounded active return. They differ in
how they share that total between effects. On a century of monthly attribution, the
choice moves up to a fifth of the answer between allocation, selection and interaction.

## Decision

- `performance.linking` implements Cariño, Menchero, GRAP and Frongello.
- `link_attribution` and `attribute` take a `method`. The default is Cariño, the
  industry's most common choice, and the method is recorded on every
  `AttributionResult`.
- Frongello is kept although its totals equal GRAP's: its running totals are known at
  each date without future returns, which a report built period by period needs.

## Consequences

- Reports can state, and reproduce, the method they used.
- A property test requires every method to be exact on arbitrary returns.
