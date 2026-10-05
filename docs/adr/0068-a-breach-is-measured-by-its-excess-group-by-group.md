# 68. A breach is measured by its excess past the limit, group by group

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Day 6 judged whether an order made a breach worse by its utilisation, and a "max weight
by" rule by its heaviest group. A property test of the pre-trade check found both
judgements unsafe:

- **Infinite utilisation.** A limit of zero ("no holdings") or a value of zero (no cash
  against a floor) makes utilisation infinite before and after a trade, so a bigger
  breach looked unchanged.
- **The heaviest group alone.** A second issuer crossing its limit was invisible while
  the first was still over it.

On 3,000 random orders, 302 that made a hard limit worse were let through.

## Decision

- `engine.excess` measures how far a value is outside its bound, in the measure's own
  units.
- `engine.group_breaches` returns one excess per group for a "max weight by" rule with
  an upper limit, and one for any other rule.
- Pre-trade compares these, group by group. A breach in a group that was within its
  limit is new; a group further past its limit is worse; only when neither happens can
  an order reduce a breach.
- `tests/compliance/test_pretrade_properties.py` requires, for any portfolio and order,
  that an order let through makes no group's excess grow, against an oracle written
  independently of the engine.

## Consequences

- None of the 3,000 random orders slips through.
- Utilisation stays as the reporting figure. It is no longer used to decide.
