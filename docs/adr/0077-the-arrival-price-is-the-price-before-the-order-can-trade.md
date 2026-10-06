# 77. The arrival price is the price before the order can trade

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Implementation shortfall splits into delay (the decision price to the arrival price)
and execution (the arrival price to the fills). The simulator's price for a minute is
the price at the end of that minute. Day 8 had two definitions of arrival:

- for an order released at the open, the arrival was the open;
- for an order released at minute m, it was the price at the end of minute m. That is
  a minute later, after the order could already have traded.

## Decision

`MarketDay.arrival(m)` is the open for m = 0, and the price at the end of minute m − 1
otherwise. The transaction cost analysis and the IS algorithm's problem both use it.

## Consequences

- The total shortfall is unchanged. The delay and timing components are now split at
  the same moment for every order.
- A property test runs random orders, algorithms, start times, sides and limits. The
  seven components add up to the shortfall computed directly from the fills.
