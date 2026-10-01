# 41. The API serves the modules; it does not compute

- **Status:** Accepted
- **Date:** 2026-09-30

## Context

A web layer added last is tempted to grow its own logic: a quick aggregation here, a
recalculated figure there. Each one is a second implementation that can disagree with
the first. The question for a reviewer is whether a number on a screen is the number
in the books.

## Decision

- **FastAPI**, with every response a Pydantic model (`extra="forbid"`). The OpenAPI 3.1
  document is generated from the code. Each endpoint records its required permission as
  `x-permission`.
- Endpoints ask a **data facade** and shape its answer. The facade asks the module that
  owns the figure: the Day 3 book, Day 4 returns, the Day 5 model, the Day 6 engine, the
  Day 7 optimiser, the Day 8 trading day.
- The facade is a `Protocol`. The web layer is tested against an in-memory stand-in,
  for every status code and control, and against the real modules, for the numbers.
- Heavy module calls run in a thread pool, so the event loop keeps serving.
- Errors are RFC 9457 problem details with the request id; there are never stack
  traces.

## Consequences

- The API's valuation equals the book's NAV, and its pre-trade answer for a $100,000
  Microsoft purchase is the Day 6 answer: blocked, $85,978 allowed. The tests assert
  both.
- The first call builds the modules (tens of seconds). Later calls take tens of
  milliseconds. A production deployment would warm the modules at start-up or serve
  stored results.
