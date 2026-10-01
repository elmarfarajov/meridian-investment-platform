# 55. A golden copy compares sources only at the same moment

- **Status:** Accepted
- **Date:** 2026-10-02

## Context

The ECB fixes the euro at 14:15 Frankfurt time; the Federal Reserve takes its noon rate
in New York. Over 27 years the two disagree by a median of 18 bp. The later fix
correlates 0.6 with the ECB's next move, and the largest gaps fall on news that came
between them. Neither source is wrong. They price different moments.

A golden copy that pools them as consensus would do one of two things. It would blend
18 bp of timing noise into every published price, or it would raise a price challenge
every time the market moved.

## Decision

- `PricingPolicy` may name each source's `FixingTime`: a time of day and a time zone.
- The anchor is the highest-ranked source present. A source fixed more than
  `max_fixing_gap` (one hour by default) from it is set aside, with the gap as the
  reason. It is not counted as disagreeing.
- The gap is measured in UTC on the day, so daylight saving is respected: Frankfurt to
  New York is 3h45 most of the year and 2h45 in the weeks the clocks disagree.

## Consequences

- On the day the ECB eased in March 2016, a policy without fixing times publishes
  nothing (the two sources are 280 bp apart). A policy with them publishes the ECB
  rate, unchallenged, and records why the Fed's was set aside.
- Policies without fixing times behave as before, so Day 2's synthetic vendors are
  unaffected.
- A firm still has to choose its moment. The WM/Reuters 16:00 London fix is the
  industry's; the chart shows how far each source sits from it.
