# Reconciliation against the custodian

Every morning the book is compared with the custodian's statement, and every
difference - a break - is explained before anyone trades on the numbers. Most breaks
are two parties looking at the same thing on different dates. The work is in telling
those apart from the few that are real, quickly.

**Implementation:** [`accounting/reconciliation.py`](../../src/meridian/accounting/reconciliation.py),
[`accounting/custodian.py`](../../src/meridian/accounting/custodian.py) ·
**Decision:** [ADR 0018](../adr/0018-reconciliation-is-on-the-custodians-terms-and-measured.md)

---

## 1. Compare like with like

A custodian reports **settled** positions and cash. The book is read the same way:
trade-date position less trades agreed but not settled. A position bought yesterday is
not yet at the custodian and a position sold in full yesterday still is; neither is a
break.

## 2. Classify by cause

Each difference is tested against candidate explanations, singly and in pairs:

| Cause | The test |
| --- | --- |
| Failed settlement | the difference equals a trade the book settled in the last week |
| Duplicate booking | the difference equals minus such a trade: the custodian booked it twice |
| Corporate action | the custodian's quantity is the book's times a split ratio |
| Transposition | the same digits in another order, a multiple of nine apart |
| Income timing | a dividend paid before the book's pay date, or a coupon paid after it |
| Unbooked cash | a line on the custodian's statement with no entry in the book |
| Price | the custodian's price is more than 50 bp from the golden copy |
| Unexplained | none of the above - listed first, because a person has to read it |

Pairs matter: a failed purchase and a custody fee in the same currency on the same day
produce one cash difference, and it is explained as both.

## 3. Measured, not asserted

A synthetic custodian generates statements from the book, prices the holdings a few
basis points away from the golden copy, and plants breaks where the answer is known -
the method the Day 2 quality rules were scored by.

Over 127 statement days from March to August 2026, clean statements raise **no breaks
at all**. With 25 breaks planted across seven causes, lasting one to eight days, the
reconciler raised 50 break-days and every one was planted and correctly explained:
**recall 100%, precision 100%**.

Two defects were found on the way, both in the measurement rather than the reconciler:
a break's age as of a past date used the day it later cleared, and the transposition
generator could key 1,011 as 0,111.

## 4. Where it would need more

A holding bought entirely in one recent trade and doubled at the custodian is either a
2-for-1 split or a duplicate; the reconciler reports the first explanation that fits,
and a production system would consult the corporate action feed. Real custodians also
disagree on accrued interest, on the pay date of a reclaim, and on the naming of cash
lines, none of which is modelled here.

```bash
meridian book reconcile --as-of 2026-04-08 --chart dashboard.png
```
