# 26. A risk model ships with its validation, and a failed control writes nothing

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

A risk number without evidence that it is the right size is an opinion. Regulators
(the Basel backtesting framework, SR 11-7 model risk guidance) and commercial model
reviews judge a model by how its forecasts fared: whether the forecast volatility
matched realised outcomes, and whether VaR was exceeded about as often as it should be.

## Decision

- Every forecast is produced by a **forward-only forecaster**: each morning it uses
  returns up to the previous close and that morning's exposures, and nothing later.
- The model is scored by **bias statistics** with their 95% band and MRAD. This runs on
  the estimation universe (market, random portfolios, each factor, each stock's specific
  risk) and on the account itself, next to a **yardstick**: what the true volatility
  scores over the same days.
- VaR is backtested by **Kupiec** (count), **Christoffersen** (clustering) and the
  **Basel traffic light** (last 250 days).
- **The risk run checks its controls before writing:** decompositions add up to 1e-10,
  every forecast is a finite positive number, and the traffic light is not red. The
  stored forecasts carry their outcomes, so the backtest can be recounted in SQL.

## Consequences

- The backtest found three mis-specifications before this was merged: the missing fund
  basis, a beta factor too loosely tied to the market, and the specific-risk prior.
  Each fix is recorded with its before-and-after numbers.
- The account's total risk reads 0.90 against a band of 0.94–1.06. The yardstick reads
  0.91 over the same days, which shows the gap is the window's calm, not the model. A
  single bias figure without a yardstick would have been misread.
- Kupiec rejects the VaR for too *few* exceptions (1 in 530). That result is reported,
  not hidden: parametric VaR from a correct volatility is conservative in a window
  calmer than its own true risk.
