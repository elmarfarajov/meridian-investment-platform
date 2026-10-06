# 79. Allocation places every share it can, and never past an account's request

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Block allocation gives the odd shares of a pro-rata split by largest remainder.
Hypothesis found a block it could not allocate: requests in fractions of a share,
where an odd share would take an account past its request. Day 8 capped that share
away, and the block then failed its own check, with a filled share unallocated.

## Decision

- The odd shares go by largest remainder only to accounts with room for them.
- What no whole share can place goes, in fractions, to accounts still short of their
  request.
- What nobody can take, less than a share, is left for the error account.

## Consequences

- Property tests over random blocks hold all of the following:
  - every filled share is allocated, or less than one is left over;
  - every account gets one price;
  - no account gets more than it asked;
  - whole-share requests are within a share of their exact pro-rata part.
