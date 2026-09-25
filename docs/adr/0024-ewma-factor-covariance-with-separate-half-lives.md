# 24. The factor covariance is EWMA, with a shorter half-life for volatility than for correlation

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The factor covariance `F` sets how much risk every exposure carries. The candidates
were:

- **The equal-weighted sample over a year:** simple, but late into every crisis and
  late out of it.
- **EWMA** with one half-life (RiskMetrics), or with separate half-lives for
  volatilities and correlations (Barra).
- **GARCH per factor:** mean-reverting and the most accurate for one series, but 21
  separate fits do not make a consistent covariance matrix, and their parameters move.
- **Shrinkage (Ledoit-Wolf):** essential for a 500 × 500 asset covariance, and
  unnecessary for 21 factors estimated on 2,500 days.

## Decision

- EWMA with a **42-day half-life for volatilities** and a **200-day half-life for
  correlations**, recursive so a daily backtest costs O(K²) per day. The mean is taken
  as zero.
- **GARCH(1,1)** (the `arch` package, Student-t, refitted monthly on four years) is kept
  as the benchmark for factor volatility forecasts.
- **Ledoit-Wolf and the sample** are kept as the asset-level estimators the factor model
  is compared against.

## Consequences

- Over ten years of the universe, the market portfolio's bias statistic is 1.013 with
  EWMA (inside the band) against 1.052 with the equal-weighted sample, and 93% of random
  portfolios are in the band against 7%.
- GARCH forecasts the world factor's true volatility more accurately (6.5% mean
  absolute log error against 15.3% for EWMA). The factor is GARCH by construction, so
  the margin overstates GARCH's advantage on real data; the comparison is reported
  rather than acted on.
- Built from the factor model, minimum-variance portfolios delivered what was promised
  (8.1% against 8.4%). A sample covariance promised a riskless portfolio that delivered
  12%.
