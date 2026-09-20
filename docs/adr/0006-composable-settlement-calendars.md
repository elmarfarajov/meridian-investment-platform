# 6. Settlement calendars are composed, not chosen

- **Status:** Accepted
- **Date:** 2026-09-20

## Context

A trade has one settlement date, but it may have to satisfy more than one
calendar. A Japanese equity bought by a euro-denominated fund settles only on a
day that is open in Tokyo *and* good for a euro payment in TARGET. A cross-currency
swap needs both currency calendars. A cross-listed security needs the calendar of
the venue it traded on and the calendar of the depository it settles in.

Systems commonly handle this by picking one calendar - usually the instrument's -
and accepting that some trades will be booked to settle on a day the other side
cannot pay. The consequence is a settlement fail, which costs interest, attracts a
buy-in, and takes an operations team a morning to unpick.

The alternative of hard-coding a "USD+JPY" calendar for every pair does not scale:
with a dozen markets there are sixty-six pairs, and the list has to be maintained.

## Decision

Calendars compose. `JointCalendar` takes any number of calendars and combines them
in one of two modes:

- **union** (the default and the settlement rule): a day is good only if it is good
  in *every* member calendar, so the holiday set is the union of theirs. This is
  the rule for any date that has to work everywhere at once.
- **intersection**: closed only on days *all* members close, which answers the
  different question "was any market open?" - the one a data-quality check asks
  before flagging a missing price.

Composition is available in configuration and on the command line through a plus:
`XNYS+XTKS` resolves to the joint calendar without anything being registered in
advance. A joint holiday reports which market closed it, so an operations enquiry
gets an answer rather than a date.

## Consequences

- Settlement dates are never earlier than the slowest market involved, which is the
  conservative and correct direction to be wrong in.
- The number of calendars that must be maintained stays linear in the number of
  markets rather than quadratic.
- A joint calendar is more closed than either member, so accrual periods computed on
  one will differ from the same period computed on the other. Instruments therefore
  keep their own calendar for accrual and use the joint one only for settlement.
- Composition is computed rather than cached across processes. The per-year caching
  inside each calendar keeps that cheap; if it ever stops being cheap, the fix is a
  cache on the joint calendar rather than a table of pairs.
