# 43. The audit log is a hash chain, verified by the readiness probe

- **Status:** Accepted
- **Date:** 2026-09-30

## Context

Record-keeping rules (SEC 17a-4, MiFID II) expect records that cannot be altered
unnoticed. An audit table can be edited by anyone with write access to the database,
and nothing would show.

## Decision

- **Every request**, allowed or refused, is appended to `audit_log` by the middleware
  after the response is formed. Each record holds:
  - the user, the method and path, the status and the latency;
  - the request id and the idempotency key.
- Each record stores the previous record's hash and its own:
  `SHA-256(previous_hash ‖ canonical JSON of its fields)`. Timestamps are hashed as UTC
  without a zone, so the hash survives any database's round trip.
- **Verification** walks the chain and reports the first record whose sequence, link
  or contents fail. It is exposed at `/v1/audit/verify`, run by
  `meridian platform verify-audit`, and part of **readiness**: a broken chain takes the
  service out of rotation.
- **Concurrency**: within a process a lock serialises writers. Across processes the
  append is optimistic: a collision on the sequence number (the primary key) is
  retried against the new head, so the chain never forks.
- The chain logic is pure (`core/audit_chain.py`) and imports nothing from the
  platform.

## Consequences

- A Hypothesis property test edits any field of any record in a generated chain.
  Verification must name exactly that record, and it does. A test against the database
  edits a stored row and sees readiness fail.
- 400 concurrent requests against two Docker workers leave an intact chain of 408
  records.
- Appending one record at a time bounds write throughput. Sealing batches under a
  Merkle root, and publishing the head hash outside the database, are the next steps.
  Without the second, an attacker who rewrites the whole table undetected is not
  defeated. That limit is stated, not hidden.
