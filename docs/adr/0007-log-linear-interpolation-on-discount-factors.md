# 7. Curves interpolate log-linearly on discount factors

- **Status:** Accepted
- **Date:** 2026-09-20

## Context

A yield curve is quoted at perhaps ten tenors and used at every date in between.
The interpolation method is therefore not a presentation detail: it determines
every discount factor the curve produces, and through them every valuation, every
duration and every forward rate.

Three candidates were considered.

**Linear on the zero rate** is the obvious choice. It is also the worst behaved.
The forward rate implied between two pillars depends on the *slope* of the zero
curve, so a piecewise-linear zero curve produces a forward curve that jumps at
every pillar. Those jumps look like arbitrage opportunities that do not exist, and
anything that prices off forwards inherits them.

**Cubic spline on the zero rate** is smooth, and invents humps. A natural cubic
spline through market quotes will overshoot between pillars, producing forward
rates nobody quoted and, at the short end, occasionally negative ones.

**Log-linear on the discount factor** is linear in the logarithm of the discount
factor, which is exactly the assumption that the forward rate is constant between
pillars. The forward curve becomes a step function - still discontinuous, but
piecewise flat, economically interpretable and bounded by the neighbouring quotes.

## Decision

The default is log-linear interpolation on discount factors, with the curve
anchored at *t=0, DF=1* so the short end extrapolates towards par rather than
flat. Monotone cubic (Fritsch-Carlson) is available where smoothness matters more
than the piecewise-flat forward, and linear on the rate is available mainly so the
comparison can be drawn.

All three are implemented behind one interface, the choice is a property of the
curve rather than a global setting, and `plot_interpolation_comparison` draws the
three against each other because the argument is far more convincing as a picture.

## Consequences

- Discount factors are positive and monotone by construction: no interpolation
  artefact can produce a negative rate or a factor above one.
- The forward curve is a step function. This is honest about what the market data
  supports, but it means an instrument that depends on a smooth instantaneous
  forward - a short-rate model calibration, for instance - will need the monotone
  cubic curve instead.
- The method is recorded on the curve and printed on every chart, so a valuation
  can always be traced back to the assumption that produced it.
