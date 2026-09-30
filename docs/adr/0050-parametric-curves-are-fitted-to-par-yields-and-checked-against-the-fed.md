# 50. Parametric curves are fitted to par yields and checked against the Federal Reserve's

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

A bootstrapped curve passes through every quote, noise included. A parametric
curve (Nelson-Siegel, or Svensson's six-parameter extension) smooths the noise and
gives the term structure an economic reading. Central banks report such curves to
the BIS, and the Federal Reserve publishes one daily.

The Svensson fit has a reputation for local minima. A curve described by level,
slope and curvature also invites a principal component analysis, which needs sign
conventions to be readable.

## Decision

- **`analytics.parametric`** fits to **par yields**, the quoted quantity, not to
  bootstrapped zeros:
  1. a grid over the decay parameters, with the betas by linear least squares;
  2. a bounded trust-region least-squares refinement of the best four starts.
  A previous fit can seed the next (`initial=`). That is how a long history is
  fitted quickly and without hopping between minima.
- **Two independent checks:**
  - the formula reproduces the Fed's published GSW yields from its published
    parameters;
  - a fit to the Treasury's par curve is set beside the Fed's fit of the same day.
- **Par yields between coupon dates** include the accrued interest of the short
  first period, in both `YieldCurve.par_rate` and the parametric curves.
- **`analytics.curve_pca`** runs a PCA of daily changes in basis points. Each
  eigenvector is oriented to read as its name:
  - level positive;
  - slope rising towards the long end;
  - curvature positive in the belly.

## Consequences

- The formula matches every published GSW yield on 9,171 days to within 0.034 bp.
- On four days from 2000 to 2026, Svensson fits the Treasury's par curve to an RMSE
  of 0.9 to 10.2 bp. Nelson-Siegel does worse on every one, and badly around humps.
- Fitted every quarter since 1990, our curve and the Fed's differ by a median of
  2.9 bp in the 2-year zero rate, 5.9 bp in the 10-year and 10.5 bp in the 30-year.
  The gap is attributed to the data (bills and on-the-runs), not to either method.
- Level, slope and curvature explain 79.4, 12.7 and 4.1 per cent of the Treasury
  curve's daily moves since 1990: Litterman and Scheinkman, reproduced on 36 years.
- Omitting accrued interest had drawn a sawtooth through par curves between coupon
  dates. Bootstraps were unaffected, because their tenors fall on coupon dates.
