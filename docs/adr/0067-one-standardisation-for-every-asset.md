# 67. One fitted standardisation for every asset, in the universe or not

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Style exposures are descriptors standardised against the estimation universe:
cap-weighted centre, scale, winsorise at three, re-centre and rescale. Assets the account
holds outside the universe went through a shorter path that skipped the last two steps.
An exposure of one therefore did not mean the same thing for both kinds of asset.

## Decision

`risk.exposures.Standardisation` is fitted once on the universe (four numbers and the
limit) and applied to any values. `standardise` and `standardise_against` both use it.

## Consequences

- An off-universe asset with a universe stock's descriptor gets that stock's exposure
  exactly; a test requires it.
- The demonstration account's style contribution moved by three hundredths of a point,
  and its volatility forecast from 12.22% to 12.24%.
