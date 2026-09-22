# Market data quality: the rules, the statistics, and how they are measured

Nothing downstream is better than the prices it is fed. A stale mark misstates a
valuation, a bad tick ruins a volatility estimate, an unrecorded split turns an
ordinary corporate action into the worst day in the history, and every one of them
does it silently. This note sets out the checks Meridian runs, the statistics behind
the ones that are statistical, and — the part most data-quality write-ups omit — how
well they actually work.

**Implementation:** [`quality/`](../../src/meridian/quality) ·
**Decision:** [ADR 0013](../adr/0013-quality-rules-are-measured-against-planted-faults.md)

---

## 1. Five dimensions, because "wrong" is not actionable

Findings are classified along the dimensions used in data governance frameworks
(DAMA-DMBOK), because each one points at a different fix.

| Dimension | Question | Rules | Who fixes it |
| --- | --- | --- | --- |
| Completeness | Is every expected value there? | `missing_days` | the vendor's coverage |
| Timeliness | Is it current? | `stale_mark`, `late_mark` | the feed schedule |
| Validity | Is it a legal value at all? | `non_positive_price`, `non_trading_day`, `crossed_quote` | the load |
| Accuracy | Is it plausibly the true value? | `robust_outlier`, `spike_reversal`, `wide_spread` | the source |
| Consistency | Does it agree with related data? | `unexplained_jump`, `close_outside_quote`, `fx_triangle`, `fx_inverse` | reference data |

Each series is scored per dimension as the share of its expected trading days
untouched by a finding of that dimension, and the five are combined
25/15/20/25/15 into one number with a traffic light. Accuracy and completeness carry
the most weight because they are the two that reach a valuation unnoticed.

---

## 2. Expected days come from the instrument's own calendar

A London stock with no price on the late-May bank holiday is complete; one with no
price on the US Memorial Day is not. Every completeness check is run against the
exchange calendar of the instrument itself, generated from statutory rules
([note](calendar-conventions.md)). This is the single most common source of false
alarms in a naive implementation, and it disappears entirely once the calendars are
right.

![Expected against received](../images/coverage-calendar.png)

---

## 3. Why the median and not the mean

The textbook outlier test flags a return more than *k* standard deviations from the
mean. It fails in exactly the situation it is needed for.

- **Masking.** One bad tick of +12% inflates the standard deviation it is judged
  against. With three bad ticks inside one 60-day window, the classical score catches
  the first and misses the next two.
- **Swamping.** A burst of genuine volatility inflates the same estimate, so ordinary
  days afterwards look extreme.

The median and the median absolute deviation have a breakdown point of 50%: half the
window can be garbage before they move. Scaling the MAD by 1.4826 makes it an
unbiased estimate of σ for normal data, so a robust z-score reads on the familiar
scale — it simply cannot be talked out of its answer by the outlier it is judging.

```
robust z = (return − rolling median) / (1.4826 × rolling MAD)
```

![Why the median, not the mean](../images/robust-vs-classical.png)

Three further details matter as much as the estimator:

1. **The window never includes the day being judged,** and never includes days after
   it. A check that uses tomorrow's data could not have run on the day.
2. **Returns are event-adjusted first.** A 4-for-1 split is a −75% return; without
   adjustment the most ordinary event in equity markets is the worst print of the
   year.
3. **Returns are scored net of a market proxy** — the leave-one-out cross-sectional
   median of the other instruments the same day. A 6% fall on a day the market fell
   5% is a market move; a 6% fall on a flat day is a question. Leaving the instrument
   out of its own proxy stops a bad print diluting the evidence against itself.

The threshold is 9 robust deviations, which is high on purpose: returns have fat
tails, and a rule that fires on every genuine four-sigma day is a rule the desk
learns to ignore.

---

## 4. The rules that need no statistics

The cheapest checks catch the most embarrassing errors.

- **A zero price.** Almost always a vendor's placeholder for "no data", and it
  values the position at nothing. Critical, always.
- **A print on a closed day.** The exchange was shut; the record is mis-dated.
- **A crossed quote** (bid above ask) cannot trade and cannot produce a mid.
- **A stale run.** The same close repeated across consecutive trading days. One
  unchanged day happens; the probability that a stock moving 1.5% a day closes on the
  same cent three times running is of the order of one in a million.
- **A jump that matches a corporate action ratio.** A price that falls to exactly a
  half, a third or a quarter, with no event on file, is an unrecorded split. A jump
  of exactly ×100 is the pence-and-pounds trap: a London price delivered in pence
  instead of pounds. Both are reported with the explanation in the message, because
  an analyst then knows what to go and look for.
- **The converse:** an event *is* on file, and the price did not move by its factor.
  Usually the event was loaded with the wrong ex-date.

![Finding the bad prints](../images/anomaly-detection.png)

---

## 5. FX has a consistency constraint prices do not

Exchange rates are not independent numbers. EURGBP must equal EURUSD ÷ GBPUSD, or
there is a riskless profit in going round the triangle. Real markets close such gaps
in milliseconds, so in end-of-day reference data a broken triangle is never an
opportunity — it is a stale leg, a mis-keyed cross, or a rate taken at a different
fixing time. Because a multi-currency book is translated through these rates, one bad
cross misstates every position held in either currency.

![The triangle must close](../images/fx-triangle.png)

---

## 6. Measuring the rules instead of admiring them

"The rules look sensible" is an opinion. The platform plants faults whose location is
known and counts what the rules find.

A seeded synthetic market provides clean data with the stylised facts that make the
problem hard — fat tails, volatility clustering, correlation, real calendars and
corporate actions — and a fault injector damages it in the nine ways real feeds fail,
keeping a ledger of every fault.

![The synthetic market behaves like a real one](../images/return-distribution.png)

Two numbers come out, and they pull against each other:

- **Recall**: of the faults planted, how many were caught? A miss is a wrong price in
  a client's valuation.
- **Precision**: of everything flagged, how much was real? A false alarm costs an
  analyst's time, and a rule with too many gets switched off.

Over 126 faults planted across three independently seeded markets: **recall 100%,
precision 97%**. Every false alarm is a genuine fat-tailed market move in the
synthetic data — which is exactly what it would be on a real desk.

![Measured, not asserted](../images/detection-scorecard.png)

---

## 7. What happens to a finding

Rules report; they never repair. Repair is a decision with an audit trail — who
overrode which price, why, on whose authority — and it belongs to the pricing
workflow, not to a validation pass.

An error or worse withholds that **source's** value for that instrument and day from
the golden copy, not the instrument itself, so the published price can still be built
from the sources that were clean. Warnings are recorded and reviewed but do not
block. Every finding, its severity, its dimension and the numbers behind it are
persisted with the run that produced them, so this evening's exceptions are tomorrow
morning's work list.

![Market data quality dashboard](../images/quality-dashboard.png)
