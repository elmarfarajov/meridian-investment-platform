# 47. Curves are built from dated instruments, with monotone convex forwards and an iterative bootstrap

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

`bootstrap_par_curve` solves on a grid of year fractions. That suits a
constant-maturity series and not a desk curve. A desk curve is built from
instruments whose dates follow conventions: spot lags, calendars, rolls, ACT/360
accrual and payment lags. It also has to report risk in those instruments.

Version 1.0.0 offered three interpolators. Its sequential bootstrap was wrong for
the non-local one: it left monotone cubic curves up to 0.86 bp off their quotes.

## Decision

- **`analytics.curve_building`** builds a curve from `Deposit` and
  `OvernightIndexSwap` instruments, each dated by the market's rules. The OIS
  floating leg telescopes to a ratio of discount factors, so each pillar is a
  one-dimensional solve.
- **Monotone convex** (Hagan and West, 2006) is added as an interpolation method, in
  `core.monotone_convex`, with the positivity collar and closed-form integrals.
  The axes, where a node forward equals the discrete forward, take the plain
  quadratic; a gap at rounding level counts as zero.
- **Non-local interpolators iterate.** Both bootstraps repeat the pass, each pillar
  solved with all the others in place, until no pillar moves by 1e-13.
- **Risk is in the quoted instruments.** The curve reports:
  - its repricing errors;
  - the Jacobian of zero rates to quotes;
  - bucketed DV01 by quote, and so the hedge notionals.
- Log-linear on discount factors stays the default. It is local and exact in one
  pass, and it is what the SOFR comparison with QuantLib checks.

## Consequences

- A 20-swap SOFR strip reprices every instrument to 1e-10 bp. It matches QuantLib's
  `PiecewiseLogLinearDiscount` to 2.4e-13 in discount factors, with identical pillar
  dates, with and without the cleared two-day payment lag.
- QuantLib's `ConvexMonotone` is a blend (quadraticity 0.3). It sits within 8.1 bp
  of pure Hagan-West in forwards. With the blend switched off, QuantLib's bootstrap
  did not converge on the same strip; Meridian's converges in six passes.
- Jacobians and bucketed DV01 rebuild the curve twice per quote. That is fine for
  twenty instruments. Analytic derivatives through the bootstrap (adjoint
  differentiation) are the step a production library would take next.
- Futures with convexity adjustments, FRAs, basis swaps, and a multi-curve setup
  with a separate discounting curve are not built yet. The instrument interface
  admits them.
