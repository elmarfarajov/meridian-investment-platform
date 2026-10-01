# 54. Findings on documented market events are explained, not suppressed

- **Status:** Accepted
- **Date:** 2026-10-02

## Context

Some days really were extraordinary: the SNB removing its floor, the Brexit vote,
Lehman, Turkey floating the lira. A rule that flags them is working. A data team that
has to re-investigate them every run will stop reading the report.

The usual fixes do not help. Raising the threshold hides the next real fault.
Deleting the finding hides the evidence.

## Decision

- `quality.fx_regimes.MARKET_EVENTS` is a register of documented events. Each event
  records:
  - its day and its currencies, or every currency;
  - what happened;
  - how long its aftermath can trip the rules.
- `review()` attaches each statistical finding (outlier, spike) that falls in an
  event's window to that event. The finding stays in the report, labelled
  *explained*. Everything else stays *open*.
- Staleness, missing data and band findings are never explained by an event: a market
  shock does not excuse a frozen feed.

## Consequences

- On 27 years of ECB fixings, 82 of 135 findings are explained by 31 events, and 53
  remain open: a work queue a person can read in an afternoon.
- The queue holds a genuine fault in the ECB's own history. The krona fixing stood at
  305 for 19 days in October 2008.
- The register needs care. An event entered too broadly would hide a real fault in its
  window, so windows are short by default (10 days), widened only for crises that
  lasted, and every event says in words what happened.
