# 23. A fundamental factor model, estimated on a universe whose true risk is known

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The account needs risk forecasts: volatility, tracking error, their sources and VaR.
There are three families of equity risk model:

- **Statistical:** principal components of past returns. They have no names, drift from
  window to window, and cannot say "your risk is health care".
- **Macroeconomic:** time-series regressions on rates and growth. They need long
  histories per stock and react slowly to a company changing.
- **Fundamental:** exposures from observable characteristics, with factor returns
  estimated by cross-sectional regression each day. This is the Barra approach.

A risk model also has to be validated, and with real data the answer is never
observed: a volatility forecast can only be compared with a realised volatility that
is itself noisy.

## Decision

- **Fundamental model.** 21 factors: world, the 11 GICS industries, five styles (beta,
  size, value, momentum, quality) and four currencies. Style exposures are standardised
  descriptors (cap-weighted mean zero, unit cross-sectional spread, winsorised at ±3).
- **Daily constrained WLS regression** with square-root-of-capitalisation weights, on
  exposures known at the start of the day. Cap-weighted industry returns are
  constrained to sum to zero, imposed exactly by substitution.
- **A synthetic estimation universe** of 500 stocks over ten years, generated from a
  recorded factor structure with GARCH Student-t dynamics and crisis regimes. Every
  true factor return, exposure and conditional variance is kept, so every forecast can
  be scored against the truth.
- **Over the demonstration window, the universe replays the Day 2 market:** its world
  factor and variance, sector moves and exchange rates. Style premia are silenced
  there, because that market has none, and only beta's ride on the world factor
  remains.
- **Estimation and coverage are separate universes.** The account's holdings get
  exposures from their own descriptors on the estimation universe's scale. Index funds
  are looked through. The bond gets a time-series beta, and cash carries its currency.

## Consequences

- Exposures have names and units a portfolio manager can act on: "+0.15 health care,
  −0.46 size against the benchmark".
- The model's quality is measured, not asserted. The recovered world factor has
  correlation 0.989 with the truth; the styles 0.91–0.97.
- A model estimated on synthetic data carries no claim about any real market. The
  interfaces take exposures and returns, so a vendor's or a real universe's data would
  replace the generator without touching the estimation.
- Silencing the style premia over the replayed window makes R-squared fall there. That
  is the honest behaviour, and it is documented on the charts.
