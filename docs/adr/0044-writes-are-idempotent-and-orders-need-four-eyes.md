# 44. Writes are idempotent by key; orders are checked pre-trade and need four eyes above a threshold

- **Status:** Accepted
- **Date:** 2026-09-30

## Context

A client that times out does not know whether its order was entered. Retrying risks
two orders; not retrying risks none. Separately, an order entered by one person and
executed without anyone else seeing it is the classic operational-risk failure.

## Decision

- **Idempotency.** Writes accept `Idempotency-Key`:
  - the response is stored per user and key, with a SHA-256 fingerprint of the body;
  - a retry with the same key and body gets the stored response
    (`Idempotent-Replayed: true`) and nothing is done again;
  - the same key with a different body is 409.
- **Orders** are checked against the Day 6 mandate before they are recorded:
  - blocked orders are refused with the reasons and the largest order that would pass;
  - orders above $250,000, or needing a soft-limit override, wait for approval by
    someone with `orders:approve` who is not the person who entered them;
  - every decision records who made it and why.

## Consequences

- In the measured working day:
  - the portfolio manager's retried orders were entered once;
  - oversized orders were stopped by the mandate before they existed;
  - every pending order was decided by compliance.
- Stored responses accumulate. Keys older than a retention period can be deleted
  (`forget_before`); a production deployment runs that daily.
