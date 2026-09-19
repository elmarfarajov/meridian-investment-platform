# 4. Trading calendars are generated from rules, not loaded from files

- **Status:** Accepted
- **Date:** 2026-09-19

## Context

Settlement dates, coupon accrual, performance periods and data-quality checks all depend
on knowing whether a given market was open on a given day. There are two ways to know
that: ship a list of holidays, or generate them from the rules that produce them.

A shipped list is simple and exact for the years it covers. It is also a maintenance
liability: it goes stale, it has to be extended every year, and a valuation run for a
future date silently produces the wrong answer when the list runs out. A third-party
package solves that but adds a dependency whose update cycle the platform does not
control, for logic that is not large.

Holiday rules are not trivial, which is the argument for care rather than for a file.
Easter moves. Independence Day on a Saturday is observed on the Friday before, but New
Year's Day on a Saturday is not pulled back into the previous year. The UK grants a
substitute weekday when a bank holiday falls at a weekend, and the substitute must not
collide with another holiday. Juneteenth only became an NYSE holiday in 2022.

## Decision

Each calendar is a class that computes its holidays for a year from statutory rules:
`NYSECalendar`, `LSECalendar`, `TARGETCalendar`, with a `WeekendCalendar` base. Easter is
computed by the Meeus/Jones/Butcher algorithm. US observed-day shifting and UK substitute
days are implemented explicitly, with the asymmetries noted in comments where they are
easy to get wrong. Results are cached per year, because calendars are long-lived
singletons and the computation is pure.

Correctness is pinned by tests against the published 2026 holiday schedules for all three
calendars, plus settlement arithmetic and the business-day conventions.

## Consequences

- Any year works, past or future, with no data file to update.
- The rules are visible and testable, and a change in the law is a one-line change with a
  test that documents the year it takes effect.
- The rules encode market holidays, not half-days or unscheduled closures. Those, when
  they matter, will need an override layer on top of the generated set.
