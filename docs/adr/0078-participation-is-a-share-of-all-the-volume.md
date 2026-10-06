# 78. Participation is a share of all the volume, the order's own included

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

The pre-trade model and the transaction cost analysis measure participation as
`q / (q + V)`: the order's share of everything traded. The POV algorithm and the
participation cap used `q = p V`, a share of the *rest* of the market's volume. So a 10%
POV order was 9.1% of the volume by the platform's own measure, and the 25% cap was
20%.

## Decision

Rates are shares of the total. `shares_at_rate(p, V) = p V / (1 − p)`.

## Consequences

- A POV order trades at the rate it is set. One of the demo's three large blocks now
  finishes on the day.
- The demo day's shortfall moves from −7.9 to −7.1 bp, and the cost of shares left
  undone from −3.1 to −2.2 bp.
