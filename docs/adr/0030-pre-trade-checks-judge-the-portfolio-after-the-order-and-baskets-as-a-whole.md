# 30. Pre-trade checks judge the portfolio after the order, and baskets as a whole

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

A pre-trade check can look at the order ("this buy is larger than 5% of NAV") or at the
portfolio the order would leave behind ("after this buy, Microsoft would be 12.3% of the
account"). Only the second answers the mandate's question. But checking the resulting
portfolio raises two further questions:
- what happens to orders that move the portfolio *towards* compliance;
- what happens to orders that belong together.

## Decision

- An order is applied to today's snapshot, funded from cash, and **every rule is run on
  the result**. Risk-metric rules are re-forecast with the Day 5 model.
- The decision follows the worst effect:
  - a hard limit newly broken or made worse **blocks**;
  - a soft one needs an **override**;
  - a new warning is flagged.
- **An order that reduces a breach is always allowed.** A trade that moves the portfolio
  back towards compliance must never be stopped by the breach it is curing.
- The **largest permissible order** is found by bisection on its size and reported with
  every decision.
- Orders sent together are checked as a **basket**: all applied, one judgement.

## Consequences

- A $100,000 Microsoft purchase is blocked with the reason (single issuer, 10.29% →
  12.28%) and the size that would pass ($85,976). A decision a trader can act on, not
  just a refusal.
- Replaying the book's 43 historical orders, one at a time gives 7 blocked and 6
  overrides. As 12 daily baskets it gives 3 blocked and 3 overrides. Checking orders
  singly would have blocked rebalances that were compliant as a whole.
- Bisection assumes a rule's utilisation moves monotonically with the order's size.
  That holds for the weight and concentration limits a single order moves. For a risk
  metric it is an approximation, and the reported maximum is conservative where it is
  not exact.
