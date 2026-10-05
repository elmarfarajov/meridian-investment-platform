# 75. Tax alpha is measured on a century of real returns, tracking luck apart

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Day 7 measured tax alpha on 16 simulated three-year paths. It defined it as the
after-tax return over the tax-blind manager's, which mixes the tax saved with whatever
the trades did to the pre-tax return. Its pre-tax return added the tax paid back to
the final value. That leaves out what the tax would have earned had it stayed invested.

## Decision

- `Market.from_history` builds the backtest's market from history.
- `services.century_tax_alpha` runs the four managers through each decade since 1931
  on Kenneth French's twelve industries:
  - the targets are the market's real weights each month;
  - the risk model is the 60 months before the decade;
  - the tax code is today's.
- The pre-tax return is time-weighted: tax paid is an outflow.
- **Tax drag** is the pre-tax return less the after-tax return on liquidation.
- **Tax saved** is the drag below the tax-blind manager's, which is after-tax active
  return less pre-tax active return.

## Consequences

- Harvesting had the least drag in every decade. It saved 3 to 47 bp a year, most in
  the 1930s, when it harvested 28% of the account. In the same decade its trades cost
  50 bp a year before tax, so tracking luck can outweigh the saving.
- Twelve industries are far less dispersed than single stocks. The study shows when
  harvesting pays, not what a direct-indexing account would earn.
- Returns include dividends, treated as reinvested untaxed, the same for every manager.
