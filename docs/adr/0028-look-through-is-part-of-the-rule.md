# 28. Look-through is part of the rule, not a global setting

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The account holds two index funds, 28% of its value. Microsoft is 10.29% of the account
directly and 15.59% including the Microsoft inside those funds. A tobacco company the
mandate excludes is not held directly but is 0.10% of the account through the world fund.

A compliance system could treat funds one way everywhere:
- as opaque holdings, which misses the concentration and the exclusion;
- or always looked through, which makes a hard limit depend on index weights the
  portfolio manager cannot trade.

## Decision

- Look-through is a **clause of each rule**: `with look-through`. Without it, a rule
  sees funds as holdings.
- Looked through, a fund is replaced by its index's constituents in their weights on
  the day (from the Day 4 benchmark), carrying each constituent's attributes: sector,
  industry, issuer, country, currency.
- The account's mandate uses both deliberately:
  - hard limits on direct holdings, where a breach can be cured today;
  - soft limits looked through, where curing means selling a fund.
- A trade in a fund counts as touching every constituent, when breaches are classified
  as active or passive.

## Consequences

- The report shows both numbers, and the difference between them is itself information:
  "Microsoft is 10.3% of the account, 15.6% counting the funds".
- Exclusions can be enforced strictly on direct holdings and monitored with a tolerance
  on indirect ones. That is the only honest policy for an index fund that cannot drop
  one company.
- Look-through uses index weights as a proxy for each fund's actual holdings. A fund
  that does not track its index well would need its own holdings file. The interface
  (fund → constituents with weights) takes that without change.
