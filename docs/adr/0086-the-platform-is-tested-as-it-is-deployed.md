# 86. The platform is tested as it is deployed

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Day 9's tests sent one request at a time to one process. The container runs two Uvicorn
workers, and a deployment may run several containers. A lock inside one process
protects nothing across processes; only what the database enforces does.

## Decision

An integration test starts four API processes on a fresh PostgreSQL database and spreads
requests over them in turn, as a load balancer would. Many requests are sent at the same
moment, and the platform's promises are checked afterwards:

- every order gets its own number;
- one key enters one order;
- one approver decides each order;
- the audit chain is unbroken.

The processes are separate servers rather than Uvicorn's `--workers`, because on
Windows a worker sharing the listening socket can block in `accept()` while holding
connections it has not served.

## Consequences

- Measured this way, the Day 9 code failed 61 of 320 simultaneous orders and decided 13
  of 40 contested orders twice. The revisited code did neither.
- The measurements are kept in `docs/data/platform-under-load.json` with their method.
