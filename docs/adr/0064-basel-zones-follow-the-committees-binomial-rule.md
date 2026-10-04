# 64. Basel zones follow the Committee's binomial rule, for any window

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Day 5 coded the Basel traffic light as a lookup: green up to four exceptions, red from
ten. That table is for exactly 250 days of a 99% VaR, but callers passed whatever window
they had scored, and a shorter or longer backtest got the 250-day thresholds.

## Decision

- The zone is the Committee's own rule (1996, Table 2): the cumulative binomial
  probability of the count under a correct model; green below 95%, red from 99.99%.
- `traffic_light(exceptions, observations, coverage)` takes the window. The yellow-zone
  plus factor is the Committee's 250-day figure for the count with the same cumulative
  probability.
- A test reproduces the Committee's printed table: every zone, plus factor and
  cumulative probability from 0 to 10 exceptions.

## Consequences

- The familiar 250-day table is unchanged.
- A 100-day backtest turns yellow at three exceptions and a 500-day one at nine.
