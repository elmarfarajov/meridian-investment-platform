# 81. Liquidation cost is tested on a century of real prices

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

Almgren-Chriss gives a liquidation's expected cost and its variance, and so a bound:
the cost exceeds `E + 1.645 √V` one time in twenty. That rests on a random walk with
known volatility. Day 8 tested the formulas on simulated prices that obey those
assumptions by construction.

## Decision

`services.century_execution` runs the paper's own example ($50m over five days) through
every week since 1927, on the market and its twelve industries (Kenneth French's daily
data):

- the volatility is the evening before's EWMA forecast;
- the realised cost uses the real daily returns;
- coverage is judged by Day 5's Kupiec test;
- a random walk with known volatility is the control.

`ExecutionProblem.variance` takes an autocorrelation. It adds `2 ρ σ² τ Σ x_k x_{k+1}`,
because a position held through moves that follow each other is riskier than a random
walk.

## Consequences

- Over 67,769 weeks the bound broke in 6.3% of weeks for sellers and 7.4% for buyers.
  In the 1970s, when daily index returns had a lag-one correlation of 0.29, the market
  broke it in 10.9% of weeks.
- Restated with the year before's autocorrelation, the rates are 5.4% and 6.3%. What
  is left is fat tails and the forecast's own error: the forecast alone gives 5.5% on
  the control.
- The trajectory is still the random walk's optimum; only its risk is restated.
