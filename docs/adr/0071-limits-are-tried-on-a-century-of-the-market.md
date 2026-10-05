# 71. Limits are tried on a century of the market

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Day 6 checked one account over two years. A limit's behaviour - how often a passive
breach arrives, how long the market takes to cure it, what a cap costs - is a property
of markets, and one account over two years cannot show it.

## Decision

`services.century_compliance` runs the engine and the register on Kenneth French's
twelve industries every month since July 1926, held as an index fund under a 40%
single-industry limit. It also runs a capped index: monthly, market weights with no
industry above 35% and the excess shared pro rata.

## Consequences

- The market broke the 40% limit only in August 2025, cured it by March 2026 and broke
  it again in May. Even March 2000 stayed at 34.9%.
- The capped index bound in 40 months, all since December 2021, and cost about 0.5% in
  total, almost all of it in those years.
- The study is at the level of industries; issuer weights of the whole market are not
  public data.
