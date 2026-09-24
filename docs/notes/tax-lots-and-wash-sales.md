# Tax lots, wash sales, and the choice of lots

A position is not one number. For a taxable account it is a stack of lots, each with
its own acquisition date and cost, and every sale is a choice of which lots to close.
That choice, and two rules about holding periods and losses, decide most of an
investor's tax bill on capital gains.

**Implementation:** [`accounting/lots.py`](../../src/meridian/accounting/lots.py),
[`accounting/wash_sales.py`](../../src/meridian/accounting/wash_sales.py),
[`accounting/tax.py`](../../src/meridian/accounting/tax.py) ·
**Decision:** [ADR 0016](../adr/0016-tax-basis-is-kept-apart-from-book-cost.md)

---

## 1. What a lot carries

| Field | Why |
| --- | --- |
| `open_date`, `quantity`, `cost_per_unit` | the economic facts: what was bought, when, for how much |
| `holding_period_start` | the holding period tacks: shares transferred in keep the donor's date, wash sale replacements add the sold shares' period |
| `open_fx_rate` | base per unit of the lot's currency on the day it was bought, so the base-currency cost is historical |
| `wash_sale_adjustment` | a disallowed loss added to the **tax** basis, per unit, in base currency |

`tax_basis = quantity x (cost_per_unit x open_fx_rate + wash_sale_adjustment)`. Book
cost never includes the wash sale adjustment: the shares did not cost more.

Long-term means held **more than one year** - one year and a day - measured from the
holding period start.

## 2. Relieving lots

A sale closes lots by the account's method: FIFO (the regulatory default), LIFO,
highest cost first, or specific identification. A partly sold lot keeps its
identifier - the one the custodian and the client see. Every closed lot, or part of one,
becomes a realised lot with its own holding period, its proceeds at the sale rate and
its cost at the purchase rate, split into price and currency.

## 3. The wash sale rule (IRC 1091)

A loss is disallowed if substantially identical shares are acquired within 30 days
before or after the sale - a 61-day window. The loss moves into the replacement shares'
basis, and the sold shares' holding period is added to theirs.

The awkward part is the look-ahead: a sale on 10 March cannot be finalised until
9 April. The engine therefore knows every acquisition in advance and keeps replacement
capacity per purchase. Following IRS Publication 550:

- replacements are taken earliest first, and each share replaces at most one sold share;
- the shares being sold cannot replace themselves, but other shares from the same
  purchase can if it falls inside the window and they are still held;
- only the fraction of the loss matched by replacement shares is disallowed;
- a match against a purchase not yet booked is deferred and applied when it is;
- the loss is measured in the tax currency, so a euro loss that is a dollar gain is not
  a wash sale.

**In the demonstration** Bayer was sold at a loss on 13 March 2025 and bought back
nineteen days later: 83,338 dollars disallowed, carried into the replacement lots, whose
holding periods tack by 343 and 255 days - one piece per sold lot. Johnson & Johnson was
harvested correctly, the exposure kept through the S&P 500 ETF, and its loss stands.

## 4. Reporting

Schedule D nets short-term gains against short-term losses, long-term against
long-term, then the two against each other. A net loss is deductible against ordinary
income up to $3,000 a year; the rest carries forward, keeping its character, with the
deduction taken from short-term first. Form 8949 lists each realised lot with the code
`W` and the disallowed amount where the wash sale rule applied.

```bash
meridian book gains --year 2025 --form-8949
meridian book wash-sales
```

## 5. Which lots to sell

For a given sale the realised gain and the tax differ by method. The minimum-tax order
sells the lots with the lowest tax per share first - losses before gains, short-term
losses first, then the gains cheapest to tax. With a linear tax each share's tax does
not depend on the others, so the greedy order is optimal; a property test confirms that
no method ever beats it.

On an illustrative six-lot holding of Microsoft, selling 200 shares at 480 costs 7.9k
dollars of federal tax under FIFO; the minimum-tax order sells the same 200 shares for a
small tax *benefit* of 246 dollars - 8.1k better. The
demonstration account's own lots sit below cost after a falling market, where the
methods differ by less than two thousand dollars - which is why the chart uses the
illustration and says so.

```bash
meridian book lot-choice US-MSFT 100
```

## 6. What the day-3 engine does not do

Substantially identical securities are the same instrument here; options and
contracts to buy are not tracked as replacements; state taxes and the alternative
minimum tax are out of scope. The rules that are implemented are implemented fully.
