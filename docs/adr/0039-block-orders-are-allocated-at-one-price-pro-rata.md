# 39. Block orders are allocated at one average price, pro rata, by a rule fixed before trading

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

Several accounts follow the same model. Trading their orders separately would make
them compete: each order's impact would raise the price for the next, and the order
of dispatch would decide who gets the best price. Regulators require aggregation to be
fair and allocation to be decided in advance (FCA COBS 11.3; the SEC's guidance for
advisers on aggregated trades).

## Decision

- Account orders are aggregated into **one block per stock and side**. The block's
  decision price is the members' quantity-weighted decision price.
- Fills are allocated:
  - **at the block's average price** to every account;
  - **in full** if the block is completed;
  - **pro rata** if it is not, in whole shares, with the odd shares by largest
    remainder;
  - never beyond an account's request, and never below a minimum (a share), in which
    case the account's share goes to the others.
- The rule is code that runs after the block and cannot see which fills were good. The
  allocation cannot be chosen after the fact.
- Accounts buying and selling the same stock are **not crossed** internally; they go to
  the market as separate blocks.

## Consequences

- The day's 78 account orders become 26 blocks. The three accounts' costs are
  identical to within 0.1 bp (−7.9, −7.9 and −8.0 bp), which is what "one price"
  should produce.
- A Hypothesis property test checks that allocations add up, are whole shares, and give
  equal fill rates.
- Internal crossing, which would save the spread on offsetting orders, is left for a
  later version. It needs its own fairness rules (at which price, and who crosses
  first).
