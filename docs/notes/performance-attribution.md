# Performance attribution: Brinson-Fachler, currency apart, linked by Cariño

The portfolio returned -5.24% since inception and its benchmark -8.30%, so the active
return is +3.06%. Attribution says where those 306 basis points came from: which
decisions added value and which took it away. This note describes the method, the two
places where the textbook formula needs care, and what the demonstration account's
numbers say.

**Implementation:** [`performance/attribution.py`](../../src/meridian/performance/attribution.py) ·
**Decisions:** [ADR 0020](../adr/0020-brinson-fachler-on-local-returns-with-currency-and-costs-apart.md),
[ADR 0021](../adr/0021-attribution-is-linked-by-carino.md)

---

## 1. Three decisions per segment

For each segment `s` (a sector or a region), with portfolio and benchmark weights `wp`
and `wb`, segment returns `Rp_s` and `Rb_s`, and total benchmark return `Rb`:

```
allocation   = (wp - wb) x (Rb_s - Rb)        overweighting a segment that beat the benchmark
selection    =  wb       x (Rp_s - Rb_s)      picking better securities within it
interaction  = (wp - wb) x (Rp_s - Rb_s)      the cross term
```

This is the **Brinson-Fachler** form. The original Brinson-Hood-Beebower measures
allocation against zero, `(wp - wb) x Rb_s`, which rewards overweighting any segment
that went up, even one that went up less than the market. Against `Rb`, allocation
pays only when the overweight segment beat the benchmark as a whole. Summed over
segments, the `Rb` term vanishes (the weights of both sides sum to one), so nothing is
lost.

**When the portfolio holds nothing in a segment at the start of a day**, `Rp_s` is
undefined, and the code does not invent one. Allocation is then the whole story, which
is the honest description of "we chose not to own Japan". If a position bought during
the day earned something, the effect goes to selection and interaction is zero. In
general the code computes selection plus interaction as one exact quantity,
`contribution - wp x Rb_s`, and derives interaction as the remainder. So the three
effects add up to the segment's active contribution by construction, not by rounding.

## 2. Local returns, then currency apart

A manager who picks German stocks well should not be credited or blamed for the euro.
So the three effects are computed on **local** returns, and the currency effect is kept
apart. For each currency, it is the portfolio's currency contribution less the
benchmark's: weight times the currency move on the closing local value. This is the
same convention the value bridge uses
([ADR 0017](../adr/0017-the-value-bridge-is-exact.md)), so like is compared with like.

Holding no yen when the benchmark holds 4.5% is a currency position too. Over the
period it cost 86 bp, most of it in 2026 when the yen strengthened against the dollar. Conversion spreads on the account's own FX trades are charged to the dollar
line, where they were paid.

**Costs** (commissions, fees and unreclaimable withholding) have no benchmark
counterpart. They are the portfolio's own line: -71 bp.

![Currency](../images/currency-attribution.png)

## 3. Index funds are looked through

The portfolio holds two index funds: a US fund and a world fund. Treated as holdings,
they would be a segment ("funds") that the benchmark does not have, and all of their
effect would be misclassified as allocation. Instead, each fund is **looked through**
to the benchmark's own composition on the day. The US fund is spread over the North
American constituents in their index weights; the world fund over all of them. A fund
that tracks its part of the benchmark then contributes almost nothing to selection,
which is correct: the choice was allocation, not stock picking.

## 4. Linking over time

Each day, the effects add up exactly to that day's active return `R_t - B_t`. Over many
days they do not, because returns compound and effects add. On the demonstration
account the plain sum of daily effects misses the compounded active return by 16 bp,
more than the whole energy sector's contribution.

**Cariño** rescales each day's effects by

```
k_t = [ln(1 + R_t) - ln(1 + B_t)] / (R_t - B_t)        K = [ln(1 + R) - ln(1 + B)] / (R - B)
linked effect = sum over days of effect_t x k_t / K
```

Because `sum (R_t - B_t) k_t = sum ln((1 + R_t)/(1 + B_t)) = ln((1 + R)/(1 + B)) = K (R - B)`,
the linked effects sum to `R - B` exactly. (When `R_t = B_t`, the limit
`k = 1 / (1 + R_t)` is used.) The scale `k_t / K` ranged between 0.91 and 0.96 over the
619 days. The residual after linking is -1.1e-15, the rounding of a float.

![Linking](../images/attribution-linking.png)

The same method links the holding contributions (against a zero benchmark) and the
effects of each month in the monthly calendar. Linked effects are **not additive across
periods**: the effects for 2025 plus those for 2026 do not equal the effects for
2025-2026. So each report period is attributed and stored separately.

## 5. The demonstration account

By sector, since inception:

| Effect | bp |
| --- | ---: |
| Allocation | -255 |
| Selection | +634 |
| Interaction | +128 |
| Currency | -131 |
| Costs | -71 |
| **Active return** | **+306** |

The account's sector bets cost money. It was 15 points overweight health care, which
lagged, and underweight financials, which led. Stock picking more than paid for it. The
book's industrials, mostly BAE Systems, returned 66% in local terms against -20% for
the benchmark's. Within technology, the book lost 5% while the sector lost 17%. Health
care is where selection and interaction went wrong together: Bayer, Roche and Johnson
& Johnson, held at four times the benchmark's weight, fell 23% against the sector's
13%, for -337 bp.

By region, allocation almost disappears (-9 bp), because the account's regional weights
are close to the benchmark's. The same skill shows up as selection in North America,
Europe and the UK.

![Attribution bridge](../images/attribution-bridge.png)

![Sector attribution](../images/sector-attribution.png)

## 6. Checks and storage

The run attributes since inception and each calendar year, by sector and by region. It
refuses to store a period whose residual exceeds 1e-10. `attribution_effects` holds one
row per segment, per currency and for costs, with the average weights and the linked
effects. `meridian perf stored` sums them back and compares them with the active return
relinked from `performance_returns`, a check that runs on SQLite and on PostgreSQL in CI.
