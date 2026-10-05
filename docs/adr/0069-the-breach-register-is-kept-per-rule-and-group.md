# 69. The breach register is kept per rule and group

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

The register kept one breach per rule. Two issuers over a single-issuer limit were one
record, judged active or passive by the heaviest. An issuer bought over the limit while
another was already over it was neither recorded nor called active.

## Decision

- A breach is keyed by rule and group (`group_breaches`): one record per issuer, sector
  or currency over the limit. It opens, closes and is judged active or passive on its
  own trades.
- `Breach.group` holds the group, and migration 0010 adds `group_label` to
  `compliance_breaches`.

## Consequences

- The demonstration account's register holds 44 breaches, not 37. The seven more are
  Apple over the look-through issuer limit while Microsoft was too, 36 breach-days in
  all.
- Active breaches are unchanged at nine.
