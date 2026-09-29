# 42. Access is permissions and entitlements, with separation of duties built into the matrix

- **Status:** Accepted
- **Date:** 2026-09-30

## Context

A client, an analyst, a portfolio manager, a trader, a compliance officer and an
administrator need different access. Checking role names in endpoints ("if role ==
'analyst'") scatters policy through the code. It makes a new role a code change, and it
cannot express "this client, but only her own portfolio".

## Decision

- **Authentication**: username and password against a salted **PBKDF2-HMAC-SHA256**
  hash at 600,000 iterations (OWASP 2023), compared in constant time. This yields an
  **HS256 JWT** with issuer, subject, roles, portfolios, expiry (30 minutes) and a
  unique id.
  - One message for any failure, so a response does not reveal whether a user exists.
  - The service refuses to start in production with the development signing key.
- **Authorisation**: endpoints require **permissions**, and roles are bundles of them
  in one table.
- **Entitlements**: a client's permissions are narrowed to the portfolios on their own
  record. An unentitled portfolio answers 404, like a missing one.
- **Separation of duties** is in the matrix:
  - no role both enters and approves orders;
  - the administrator manages users and reads the audit log, but reads no client data
    and cannot trade;
  - a user holding both "enter" and "approve" still cannot approve their own order.
- **A token bucket per user**: 120 requests a minute by default, then 429 with
  `Retry-After`.

## Consequences

- The role matrix is data. It is drawn from the table and tested for its separations.
- The rate limit is per process. Across workers the effective limit multiplies, and a
  shared store (Redis) would make it exact.
- Tokens are not revocable before expiry. Single sign-on (OpenID Connect) with the
  firm's identity provider is the step a real deployment takes.
