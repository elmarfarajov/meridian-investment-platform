# 34. Orders are rounded to whole lots by a separate mixed-integer programme

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

The optimiser proposes continuous trades. The desk needs whole shares, board lots where
the market has them, and tickets above a minimum. Putting integer variables into the
main problem would make it a mixed-integer conic programme: slow, and without a
certificate at the tolerances the rest of the platform uses. Rounding each trade on its
own can break the cash band when many buys round up together.

## Decision

- The continuous problem is solved first. Its trades are then rounded by a **separate
  MILP**, solved by HiGHS:
  - it minimises the total absolute difference from the continuous trades;
  - each order is a whole number of lots, in the continuous trade's direction;
  - each order is zero or at least the minimum ticket;
  - no sale is larger than the position;
  - cash after the orders stays within its band.
- Sales are allocated to lots at the lowest tax per unit first.

## Consequences

- The demonstration proposal becomes 27 orders, $988 away from the continuous trades in
  total. Tokyo names trade in board lots of 100.
- The rounding cannot change what was decided, only how precisely it is executed. A
  trade the optimiser proposed in one direction is never reversed.
