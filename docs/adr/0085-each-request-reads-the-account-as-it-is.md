# 85. Each request reads the account as it is

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Day 9 took the caller's roles and portfolios from the access token alone. A token lives
thirty minutes, so changes to the account did not take effect until it expired:

- an account deactivated, as for a leaver, kept every right;
- an account removed kept every right;
- an account moved to a role without trading could still trade.

## Decision

The token says who is calling. On each request the platform reads the account:

- if it is missing or inactive, the request gets 401;
- otherwise the roles and portfolios are the ones on record now.

## Consequences

- One indexed primary-key read per request.
- Revoking access takes effect on the next request, which is what separation of duties
  and a leaver process need.
