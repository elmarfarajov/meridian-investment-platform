# Valuation, currency, and the value bridge

The ledger says what was paid. The valuation says what it is worth, and the value
bridge says why that changed. The bridge is the chart a client meeting starts with, so
it has to be exact.

**Implementation:** [`accounting/valuation.py`](../../src/meridian/accounting/valuation.py),
[`accounting/bridge.py`](../../src/meridian/accounting/bridge.py) ·
**Decision:** [ADR 0017](../adr/0017-the-value-bridge-is-exact.md)

---

## 1. Net asset value

NAV is every open lot at the day's price and rate, plus accrued interest on bonds,
plus everything cash-like: settled cash, receivables and payables of unsettled trades,
dividends gone ex but not paid, and withholding tax awaiting reclaim. Prices and rates
are looked up **as of** the day with a staleness limit: a holding in a market closed
for a holiday is valued at its last close; one whose price stopped arriving is listed
as missing, not valued at a number nobody would defend.

A bond's price is quoted per 100 of face and its units are bonds of 1,000; the price
scale comes from the security master, which is how the platform avoids the classic
factor-of-ten valuation error.

## 2. Price and currency

For each lot, bought at its own rate:

```
value - cost = (local value - local cost) x rate_today        price
             + local cost x (rate_today - rate_at_purchase)    currency
```

On the demonstration's closing day the foreign holdings' unrealised result is split
roughly evenly: of a 110k dollar unrealised loss across the book, 52k is price and 58k
currency. The same split is used for realised gains, so a gain does not change
character when it is realised.

## 3. The bridge

Between two valuation dates the change in NAV is split into **flows** (money and
securities the client moved), **price**, **currency**, **income** and **costs**. For one
holding over one day:

```
Q1 P1 s X1 - Q0 P0 s X0 = (Qa P1 - Q0 P0) s X0                    price
                        + Qa P1 s (X1 - X0)                        currency
                        + sum over trades (dQ P1 s - consideration) X1   price (trading)
                        + consideration X1                          into cash
```

`Qa` is the quantity after corporate actions and before the day's trades. That one
choice is why a 4-for-1 split is not a 75% crash and why a dividend's ex-date price drop
is offset by the income it creates. The same identity is written for accrued interest
and for every cash-like balance, so the bridge carries a residual - and it is zero.

| 2025 (USD) | |
| --- | --- |
| Opening NAV | 4,346,521 |
| Flows | +250,000 |
| Price | -419,484 |
| Currency | -16,389 |
| Income | +51,473 |
| Costs | -16,645 |
| Closing NAV | 4,195,476 |

The largest daily residual across 620 days is 1.8e-21 dollars. A property test requires
the same of random multi-currency books.

```bash
meridian book bridge --from 2024-12-31 --to 2025-12-31 --chart waterfall.png
```

## 4. What the bridge is not

It is not a rate of return. Day 4 turns the same daily valuations and flows into
time-weighted and money-weighted returns, and the bridge's components into attribution.
The bridge is the accounting identity those calculations have to agree with.
