# 83. A write is decided by the database, in one step

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Two of Day 9's writes read the state, decided, and wrote in separate steps:

- **Idempotency:** is the key known? then enter the order, then store the key.
- **The four-eyes decision:** read the order as pending, then write the decision.

Two requests at the same moment both passed the check. A retried order was entered
twice or answered 500. Two approvers were both told they had decided the order, one
"approved" and one "rejected", and the last write stood.

## Decision

- **The order and its idempotency record are one transaction.** If the key is taken,
  the first request's stored answer is returned.
- **A decision is one conditional `UPDATE ... WHERE status = 'pending approval'`.**
  If no row changes, someone else decided first, and the answer is 409.

## Consequences

- Unit tests force each interleaving with a barrier, so they fail every time the code
  is wrong.
- Under load on four processes, Day 9 decided 13 of 40 contested orders twice, and the
  revisited code none.
