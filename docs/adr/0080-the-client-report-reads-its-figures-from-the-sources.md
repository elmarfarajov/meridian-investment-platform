# 80. The client report reads its figures from their sources

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

The report's purpose is that every number in it agrees with the module that produced
it. Day 8 typed several figures into its text:

- the mandate's 6% tracking-error limit;
- its 30% active-share floor;
- "two other accounts" and "26 block orders".

Each was true only while the data stayed as it was. The trading page also told the
client that shares left undone were "carried to the next session". Nothing in the
platform does that, and the methodology note said so.

## Decision

- The limits are read from the mandate's rules (`ClientPack.limit`).
- The counts are read from the blocks (`blocks_traded`, `other_accounts`).
- An expired block is reported as expired.

## Consequences

- A change to the mandate or the trade list changes the report's words with it. A
  test checks the figures against their sources, and that the report promises nothing
  the platform does not do.
