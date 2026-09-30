# 48. Calendars carry history, and a simulation steps through the scheduled view

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

The calendars applied today's rules to every year. Compared with QuantLib, they
were wrong on:

- years before a rule existed (Martin Luther King Jr. Day before 1998, TARGET's
  Easter before 2000, Japan before its reforms of 2000 and 2003);
- closures no rule predicts (9/11, Hurricane Sandy, state funerals, jubilees);
- decisions taken year by year (SIFMA's Good Friday early closes).

Correcting them exposed a second fault. The synthetic market drew one shock per
business day, so adding one holiday in January 2025 shifted every draw after it,
and every number from Days 2 to 9 with it.

## Decision

- **Rules carry the years they apply to.** Japan follows the Act on National
  Holidays as it stood each year, including:
  - the pre-2007 substitute rule;
  - citizens' holidays;
  - the Olympic moves of 2020 and 2021.
- **The equinoxes are computed** (Meeus, chapter 27, with delta T), not approximated.
- **Special closures and special openings are data**, with names:
  - `special_closures`, for the days a market shut that no rule predicts;
  - `special_openings()`, for SIFMA's Good Friday decisions. Years not yet decided
    are projected by the pattern those decisions follow.
- **Scheduled and actual are separate views.** The actual calendar is the scheduled
  one, less the special openings, plus the special closures; it is what settlement,
  valuation and data quality use. `calendar.scheduled()` is the rules alone, and it
  is what a simulation steps through.

## Consequences

- NYSE, SIFMA, LSE and TARGET match QuantLib on every weekday from 1990 (1999 for
  TARGET) to 2060. Xetra and Tokyo differ only on documented days, where the
  evidence favours Meridian.
- The demonstration world is unchanged, bit for bit. A funeral closes the market,
  but the simulation's random path is the same, as the world's is: news
  accumulates, and the next open prices it.
- Special closures must be added as they happen. Nothing can predict the next one.
  A production system would load them from a reference data feed; here they are
  code, reviewed like code.
