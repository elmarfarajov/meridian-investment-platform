# 65. GARCH is filtered by one function, checked against arch to the last bit

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Day 5 fitted GARCH with `arch` and then filtered it forward with its own loop, in more
than one place. A reference check against `arch` would only prove the copy written for
the test right, not the code the forecasters run.

## Decision

- `risk.garch.garch_filter` is the single recursion. It takes the variance before the
  first return in `arch`'s backcast convention, s2_0 = omega + (alpha + beta) x
  backcast.
- `risk.backtest.garch_var` filters each refit segment with it.
- `devtools.risk_reference` compares `garch_filter` with `arch`'s conditional
  volatilities and one-day forecast, using `arch`'s parameters and backcast, on 1,500
  days of real returns.

## Consequences

- The two agree to 0 on the conditional volatilities and on the forecast.
- Moving `garch_var` onto `garch_filter` left the century backtest unchanged, exception
  for exception.
