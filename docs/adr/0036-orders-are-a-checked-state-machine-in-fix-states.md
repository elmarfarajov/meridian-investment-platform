# 36. Orders are a checked state machine, in FIX states

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

An order could be modelled as a row with a filled quantity that goes up. That loses
the things a best-execution review asks about:
- when the desk accepted the order;
- which child order each fill belonged to;
- whether a partially filled slice was cancelled or left working;
- whether anything was filled after the order was cancelled.

It also invents vocabulary that no broker would recognise.

## Decision

- An order's status is FIX `OrdStatus` (tag 39): pending new, new, partially filled,
  filled, cancelled, expired, rejected. The allowed transitions are a table.
- Every event (release, fill, cancel, expire, reject) goes through the table and is
  appended to the order's **audit trail**.
- After every event the order checks its invariants:
  - `cumulative + leaves = quantity` while open, and `leaves` is zero once done;
  - no overfill, and no fill through the limit price;
  - the average price is recomputed from the fills, never updated incrementally;
  - the trail is in time order.
- **Parent and child orders** are the same class. A child names its parent, and a
  parent's fills equal its children's.

## Consequences

- An illegal message is refused at the moment it arrives: a fill before release, a
  fill after cancellation, an overfill, a fill through the limit. The consistency
  errors of real OMS feeds therefore cannot be stored.
- The audit trail is persisted (`execution_events`), one row per transition. It
  answers "what happened to this order, when" without reconstruction.
- A FIX gateway would map `ExecType` messages onto the same events without changing
  the model.
