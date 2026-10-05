# 70. The UCITS screen follows the Directive's text, with issuer types

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Version 1 of the UCITS what-if had two problems:

- it cited article 52(4) for the 35% government limit, which is article 52(3); 52(4)
  is covered bonds;
- it applied the 10% and 5/10/40 issuer rules to shares only. Article 52 covers all
  transferable securities of one body, and by 52(5) state issues do not count towards
  the 40%.

The language had no way to tell a state issuer from a company.

## Decision

- The mandate language gains the attribute `issuer_type`: government, corporate, fund
  or cash. The demonstration assigns it from the security master, with state issuers
  listed in `GOVERNMENT_ISSUERS`.
- `ucits_screen.mandate` version 2 applies the issuer rules to corporate shares and
  bonds and the 35% limit to government issuers, with the articles cited correctly.

## Consequences

- The account, which holds no corporate bonds, gets the same answers.
- A book with corporate bonds is now screened as the Directive intends.
