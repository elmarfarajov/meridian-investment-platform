# 52. Quality statistics respect the resolution of the data

- **Status:** Accepted
- **Date:** 2026-10-02

## Context

A fixing printed to four decimals cannot move by less than one tick. Against a window
of identical fixings - a pegged rate, or a quiet one coarsely quoted - the median
absolute deviation is zero. A one-tick wobble then scores as infinitely many
deviations.

Staleness had the mirror problem. "Two repeats in a row" is rare for a share moving
1.5% a day, and it is routine for the krona quoted to one decimal. On 27 years of ECB
fixings these two effects produced more than half of 1,282 findings.

## Decision

- **A resolution floor.** The robust scale is floored at one tick of the quote,
  expressed as a return.
- **Measured locally.** The tick is the finest step among the twenty prints before
  each return, trailing zeros included, because sources change their precision.
- **Staleness is a probability.** With recent robust volatility σ and tick *t*, a
  print repeats with probability `erf(t / 2 sqrt(2) sigma)`. A run of *k* repeats is
  flagged only if that probability to the *k* is below `improbable` (1e-3), and never
  below `min_repeats`.
- `resolution_aware=False` reproduces v1.1.0, so the effect can be measured.

## Consequences

- On real FX the findings fall from 1,282 to 560. Every synthetic test, including
  recall on every planted fault, is unchanged: for a liquid share the floor is far
  below its volatility, and the probability gate never excuses its repeats.
- The model is checkable, and it holds: the expected share of unchanged fixings per
  currency sits close to the share the ECB actually printed.
- The krona's 19 identical fixings in October 2008 are still flagged. A probability
  model excuses rounding, not a frozen source.
