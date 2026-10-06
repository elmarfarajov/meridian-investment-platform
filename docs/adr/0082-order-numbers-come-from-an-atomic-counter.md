# 82. Order numbers come from an atomic counter

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Day 9 numbered an order as the count of orders plus one. Two orders entered at the same
moment counted the same orders and took the same number, and the second failed with a
500. Retrying a taken number does not scale. Forty orders at once all read the same
count, one wins each round, and on PostgreSQL every conflicting insert waits for the
other to commit. The retries queued past a minute.

## Decision

A counter row (`platform_counters`, migration 0011) is incremented by one
`UPDATE ... RETURNING` inside the order's own transaction.

## Consequences

- The database hands out each number once, and an order rolled back gives its number
  back: there are no gaps.
- Order entry is serialised on the counter row for the length of one short transaction.
  Forty simultaneous orders on four processes take about four seconds, none fails.
