# Trading calendars, settlement and the days markets disagree

Exchange calendars look like plumbing. They are, until a trade breaks — and then
they are the first thing anyone looks at. This note sets out how Meridian computes
them, the asymmetries that are easy to get wrong, and why the platform composes
calendars rather than choosing one.

---

## 1. Why the calendars are generated rather than loaded

A holiday file is simple, exact for the years it covers, and a maintenance
liability. It goes stale, it has to be extended every year, and a valuation dated
beyond its last entry silently produces the wrong answer — the worst failure mode
available, because nothing raises.

Meridian computes each calendar from the statutory rules that produce it, so any
year works, past or future, with nothing to update. The cost is that the rules have
to be implemented carefully, and several of them are asymmetric in ways that are
easy to miss. Those are the interesting parts.

**Implementation:** [`core/calendars.py`](../../src/meridian/core/calendars.py) ·
**Decision:** [ADR 0004](../adr/0004-rule-based-trading-calendars.md)

---

## 2. The rules, and where they bite

### 2.1 Easter

Good Friday and Easter Monday move with the lunar calendar. Meridian uses the
anonymous Gregorian algorithm (Meeus/Jones/Butcher), which is exact for any year in
the Gregorian calendar. Every European calendar in the platform derives at least two
holidays from it, and SIX derives four — Ascension Day is Easter + 39, Whit Monday
is Easter + 50.

### 2.2 US observed days are not symmetric

When a US federal holiday falls at a weekend it is observed on the nearest weekday:
Saturday moves back to Friday, Sunday moves forward to Monday. **Except** New Year's
Day, which is not pulled back into the previous year — 1 January 2028 is a Saturday
and the market is open on Friday 31 December 2027.

Independence Day in 2026 falls on a Saturday, so the NYSE closes on Friday 3 July.
London is open that day. That single asymmetry is one of the twelve divergent days
in the 2026 calendar.

### 2.3 UK substitute days chain

When a UK bank holiday falls at a weekend, a substitute weekday is granted — and
the substitute must not collide with another holiday. In 2026 Boxing Day falls on a
Saturday, so its substitute moves to Monday 28 December, and the algorithm has to
know Christmas Day already has Friday the 25th. The implementation therefore
accumulates the days already taken as it goes, rather than shifting each holiday
independently.

### 2.4 Japan: equinoxes, Happy Mondays and chained substitutes

Tokyo is the most intricate calendar in the platform.

- **The equinoxes are astronomical.** Vernal Equinox Day and Autumnal Equinox Day
  fall on the actual equinox, which moves. Meridian uses the standard approximation
  valid for 1980–2099:
  $\lfloor 20.8431 + 0.242194(Y - 1980) - \lfloor (Y-1980)/4 \rfloor \rfloor$ for
  the vernal, and 23.2488 in place of 20.8431 for the autumnal.
- **Happy Monday.** Coming of Age Day, Marine Day, Respect for the Aged Day and
  Sports Day are fixed to the second or third Monday of their month rather than to
  a date.
- **Substitutes chain.** A holiday falling on a Sunday is observed on the next day
  that is not already a holiday. Constitution Memorial Day 2026 falls on a Sunday
  the 3rd; Greenery Day is the 4th and Children's Day the 5th, so the substitute
  lands on **Wednesday 6 May**.
- **The exchange closes beyond the statute.** 2 and 3 January and 31 December are
  exchange holidays, not public ones.

### 2.5 The bond market is not the equity market

The US fixed income market (SIFMA recommended close) keeps two holidays the NYSE
does not: Columbus Day and Veterans Day. A Treasury settles on a different calendar
from an equity traded on the same morning, which is exactly the sort of detail a
system either encodes or gets wrong twice a year.

---

## 3. Business day conventions

Once a date is known, a convention says what to do when it is not a business day:

| Convention | Rule |
| --- | --- |
| Unadjusted | leave it |
| Following | move forward to the next business day |
| Modified following | forward, unless that crosses into the next month, then backward |
| Preceding | move backward |
| Modified preceding | backward, unless that crosses into the previous month, then forward |

Modified following is the market default precisely because it keeps a payment in the
month it belongs to, which matters for monthly accounting periods.

Settlement arithmetic is separate: **T+n counts n business days forward**, which is
not the same as adding *n* calendar days and adjusting. On 23 December 2026, T+2 in
New York is the 28th; in London, where Boxing Day's substitute closes the 28th, it
is the 29th.

---

## 4. Composing calendars

A trade often has to satisfy more than one calendar at once: a Japanese equity
bought by a euro fund needs Tokyo *and* TARGET. Meridian composes them rather than
picking one — see [ADR 0006](../adr/0006-composable-settlement-calendars.md).

- **Union** (the settlement rule): good only where every member is good.
- **Intersection**: closed only where all members close — the right question for a
  data-quality check asking "was any market open?"

On the command line, `XNYS+XTKS` resolves to the joint calendar without registering
anything in advance:

```bash
meridian calendar ladder 2026-12-23 --calendars XNYS,XLON,TARGET,XTKS
meridian calendar matrix --year 2026
```

The [settlement ladder](../images/settlement-ladder.png) shows where T+0 to T+3 land
in each market and in the joint calendar; the
[divergence matrix](../images/calendar-divergence.png) counts, for every pair, the
weekdays on which exactly one of them trades.

---

## 5. Why this matters downstream

Every one of these dates feeds something:

| Consumer | What breaks when the calendar is wrong |
| --- | --- |
| Settlement | a failed trade, interest claims, a possible buy-in |
| Accrual | coupon interest off by a day, on every position |
| Performance | a return computed against a day the benchmark did not trade |
| Data quality | a stale price flagged that was never missing, or a real gap missed |
| Compliance | a limit tested on a day the book was not marked |

There were **twelve weekdays in 2026** on which NYSE, London or TARGET disagreed.
Each is a day where a cross-border position was marked on one side and not the
other. A platform that cannot enumerate them cannot reconcile them.
