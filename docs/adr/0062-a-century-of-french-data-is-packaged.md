# 62. A century of US equity returns from Kenneth French's library is packaged

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Day 4's benchmark and portfolio were synthetic, over about two years. That was enough to
test the arithmetic, but not to see how attribution, linking and risk measures behave
on real markets, or over horizons where their conventions diverge.

## Decision

- Package the Kenneth R. French Data Library's 12 industry portfolios and the
  Fama-French three factors, monthly from July 1926:
  - value- and equal-weighted returns;
  - number of firms;
  - average firm size.
- `marketdata.french` loads them; `devtools.fetch_french` rebuilds them from the
  library's files.
- The library publishes the data for research and teaching and asks to be cited. Every
  chart and note that uses them cites the source.

## Consequences

- The market can be rebuilt from its industries and checked against the published
  market factor: 11 bp a month apart.
- A century of Brinson attribution, linking comparisons and risk statistics run
  offline and reproducibly.
- If the library's terms change, the data can be withdrawn without touching the code:
  the loader names the rebuild command.
