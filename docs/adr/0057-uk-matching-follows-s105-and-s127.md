# 57. UK matching treats one day as one transaction, and rights as part of the holding

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Writing out HMRC's examples exposed three places where `uk_matching` departed from the
statute:

- Two sales on one day were matched in turn, so the first took every share bought that
  day.
- Rights taken up were treated as purchases. A disposal shortly before a take-up would
  have been matched with the rights under the 30-day rule.
- A disposal larger than the pool was refused, although HS284 matches it with later
  acquisitions.

## Decision

- Acquisitions on one day are merged into one acquisition, and disposals on one day
  into one disposal, before matching (TCGA 1992 s105(1)). The merged result is split
  back to each transaction pro rata to its quantity.
- A purchase whose metadata names a rights issue (`REORGANISATION`) is part of the
  original holding (s127). It joins the section 104 pool at its cost and is excluded
  from same-day and 30-day matching. `builders.rights_take_up` creates such a purchase.
- After the pool, any shortfall is matched with later non-rights acquisitions, earliest
  first. Only a disposal of more than was ever acquired is an error.

## Consequences

- Two sales on one day now report the same cost per share.
- CG51590 Examples 2 and 4, Mr Browne and the Peninsula Trust with their rights issues,
  are reproduced.
- A feed must mark a take-up as rights. If it does not, the take-up is matched as a
  purchase, which is the conservative reading.
