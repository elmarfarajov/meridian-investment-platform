# 35. Tax alpha is measured on liquidation value, over simulated paths, against a tax-blind manager

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Published tax-alpha figures are often pre-liquidation: they count deferred tax as saved.
They often value a harvested loss at the full short-term rate. And they are often
reported from one historical path. Each of these flatters the result.

## Decision

- **The comparison.** Four managers run through the **same simulated markets**:
  buy and hold, tax-blind (FIFO), tax-aware, and tax-aware with harvesting.
  - The markets are monthly, simulated from the Day 5 factor model.
  - The index is 100 stocks, reconstituted quarterly.
  - Results are reported over many paths.
- **The measure.** Tax alpha is the annual after-tax return over the **tax-blind**
  manager's, on the value the account would have **if liquidated at the end**. The
  pre-liquidation figure is reported beside it.
- **The ledger.** Tax follows the US rules:
  - Schedule D netting;
  - the $3,000 offset and carryforward;
  - the wash-sale rule in both directions.
- **The client.** The client realises short-term gains elsewhere, which harvested losses
  offset. A harvested loss is valued at the short-term rate less the long-term rate: it
  saves the one now and gives back the other when the lower basis is realised.
- **A fair fight.** Both tax-aware managers work to the same 1.5% tracking-error budget.

## Consequences

- Over 16 paths of 36 months, on liquidation value:
  - the tax-aware manager earns +0.55% a year over the tax-blind one;
  - the harvesting manager earns +0.49%;
  - buy and hold earns +0.14%.
  Pre-liquidation the figures are +1.51%, +1.48% and +0.84%.
- The first version valued harvested losses at the full rate. It churned the account and
  lost after-tax return. The valuation, not the harvesting, is what the design has to
  get right.
- The simulation takes about five minutes for the gallery. It is part of the chart build
  and of the slow test, so its numbers are always the code's numbers.
