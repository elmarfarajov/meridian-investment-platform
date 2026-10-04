# 66. A century of daily returns validates the market-risk forecasters

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Day 5's validation used a synthetic universe whose true risk is known. That measures a
forecaster against the truth, but only against the behaviour the generator was given.
Real markets have crashes, regime changes and quiet decades it did not write.

## Decision

- Package the daily value-weighted returns of Kenneth French's 12 industry portfolios
  and the daily Fama-French factors, from 1 July 1926. This extends ADR 0062.
- `risk.backtest` holds four one-day VaR forecasters for a single series: normal with
  RiskMetrics volatility, historical and filtered historical simulation, and GARCH-t.
  Each uses only the past.
- `services.century_risk` scores them since 1929 with Kupiec, Christoffersen and
  Basel's zone year by year. It also gives bias statistics by decade, QLIKE losses
  (`risk.validation.qlike`) and minimum-variance trials on the twelve industries.

## Consequences

- Filtered historical simulation is the only forecaster with no red year in 97.
  Historical simulation has the most.
- The RiskMetrics forecast runs low by 3-27% in every decade for every series. A model
  review on real daily data should expect a bias statistic near 1.05.
- With twelve assets, covariance shrinkage barely matters. It is a remedy for
  dimension, which the 500-stock universe still demonstrates.
