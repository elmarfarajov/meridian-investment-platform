# 32. Lots are decision variables; fixed relief rules are applied after the solve

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

How much tax a sale realises depends on which lots it relieves. A US taxpayer may name
the lots (specific identification). A broker's default is usually first in, first out.
"Sell a lot only once every older lot is gone" is not a convex constraint.

## Decision

- The optimiser's sale variables are **per lot**. Each lot carries its own tax per unit
  of value sold: rate by holding period × gain share, negative for a loss.
- **Specific identification relieves the lowest tax per unit first.** This is what the
  optimiser chooses whenever tax counts. When tax is ignored the lots of one asset are
  interchangeable, and it still takes the cheapest.
- FIFO, LIFO and highest-cost-first are applied **after** the solve to each asset's
  total sale. `Rebalancer.relieve` applies any rule to any trades, which is how the value
  of choosing lots is measured: the same trades, relieved four ways.

## Consequences

- On the demonstration proposal, choosing lots realises −$96.9k of tax. FIFO would
  realise −$94.7k and LIFO −$51.8k on the same trades.
- A tax-blind manager is modelled honestly: it decides how much of each asset to sell
  without regard to tax, and its broker relieves the lots FIFO.
- Per dollar sold, a large long-term gain can cost more than a small short-term one. A
  young lot with a 10% gain costs 4.1%; an old lot with a 40% gain costs 9.5%. So "sell
  the long-term lots first" is not a rule the optimiser follows.
