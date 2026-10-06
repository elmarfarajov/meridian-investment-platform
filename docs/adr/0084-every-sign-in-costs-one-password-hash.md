# 84. Every sign-in costs one password hash

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

A failed sign-in returns the same message for an unknown username and a wrong password.
That keeps usernames secret only if the two also take the same time. Day 9 hashed the
password only for an account that existed and was active. At 600,000 PBKDF2 iterations:

- a wrong password for a real user took 206 ms;
- an unknown or deactivated name took 7 ms.

The time told an attacker which usernames are real (OWASP: authentication responses must
not allow username enumeration).

## Decision

Every sign-in computes exactly one hash: against the account's stored hash, or against
a decoy hash no password matches when there is no such account.

## Consequences

- All three cases now take about 217 ms.
- A test counts the hashes each kind of failure computes.
