# 46. The rates engine is reconciled against QuantLib, and every break is explained

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

Day 1 tested calendars, day counts, bonds and curves against examples written by
the same hand as the code, so the tests shared the code's misunderstandings.
QuantLib is the reference implementation that banks, vendors and regulators use.
Agreeing with it is not proof of being right, but a disagreement always deserves an
explanation.

## Decision

- **QuantLib** is a development dependency, never a runtime one.
  `meridian.devtools.reference` compares the two on the same inputs:
  - every weekday 1990-2060 in six calendars;
  - eight day counts on generated date pairs;
  - bond and gilt analytics;
  - a SOFR curve.
- The comparison is treated as a **reconciliation**. Every difference is a break that
  is either fixed, or listed in `KNOWN_DIFFERENCES` with its reason and its
  evidence.
- A test asserts that the breaks are **exactly** the documented ones. A new break
  fails, and so does a documented break that disappears, because its explanation
  has gone stale.
- **When the references disagree**, a third source decides:
  - astronomy for Japan's equinoxes (Meeus, chapter 27);
  - Deutsche Boerse's own calendar for Xetra;
  - SIFMA's *Standard Securities Calculation Methods* for 30/360 street pricing.

## Consequences

- 309 calendar breaks at version 1.0.0 became 72, all explained:
  - Xetra's New Year's Eve;
  - QuantLib's pre-2000 Japanese equinoxes, a day early;
  - QuantLib's retroactive 2007 substitute rule.
- It found 30/360 US without its February rules, and 30/360 bonds priced on calendar
  days. Both are fixed.
- The comparison runs in two seconds and is part of the test suite; CI installs
  QuantLib with the development extras.
- Conventions where the two libraries measure different things are set to agree
  before comparing, not tolerated with a loose tolerance. Payment-date discounting
  is one: QuantLib uses the adjusted date, the street the nominal one.
