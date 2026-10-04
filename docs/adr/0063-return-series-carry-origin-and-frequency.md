# 63. Return series carry their origin and frequency; ratios use annual rates

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Four of the faults found in the second reading of Day 4 came from implicit
assumptions:

- every series was daily (252 periods a year);
- a series started the calendar day before its first return;
- the presented return, unannualised under a year per GIPS, was fit to put in a ratio;
- XIRR's day basis was 365.25.

## Decision

- `ReturnSeries` carries an optional `origin`, the valuation the first return is
  measured from, and `periods_per_year`, 252 by default and 12 for monthly data.
- `annualise` keeps the GIPS presentation rule. `annual_rate` gives the annual rate for
  any period, and the Sharpe, Sortino, information ratio and alpha use it.
- XIRR and XNPV count actual/365, as Excel does.

## Consequences

- Monthly data from any source can use the same statistics.
- Ratios on short periods are comparable with ratios on long ones.
- Money-weighted returns agree with the spreadsheet a client checks them in.
