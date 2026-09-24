# One book, two tax codes: UK share matching

The demonstration household is a US person resident in the United Kingdom. Both
countries tax their capital gains, on the same transactions, under rules that do not
agree - in size, and sometimes in sign.

**Implementation:** [`accounting/uk_matching.py`](../../src/meridian/accounting/uk_matching.py)

---

## 1. The UK does not tax lots

A UK disposal of shares is matched, in this order (TCGA 1992 ss. 104-106A):

1. **Same day** - with shares of the same class acquired on the same day.
2. **Bed and breakfast** - with shares acquired in the **30 days after** the disposal,
   earliest first, earlier disposals first.
3. **The section 104 pool** - every other share, at the pool's average cost.
   Acquisitions join the pool; disposals take cost out of it pro rata.

Same-day matching is applied to every disposal before any 30-day matching.

## 2. Two rules against the same trick

Both countries stop an investor selling at a loss and buying straight back, but in
opposite ways. The US **disallows** the loss and moves it into the replacement shares.
The UK **matches** the sale to the repurchase, so the gain or loss is measured against
the new shares' cost.

The demonstration shows the difference sharply. Bayer was sold on 13 March 2025 and
bought back nineteen days later at a lower price. Under US rules the loss was entirely
disallowed and the disposal reports nothing. Under UK rules the sale is matched to the
cheaper repurchase and reports a **gain of 10,243 pounds**.

## 3. Currency and years

UK gains are measured in sterling: cost at the rate on the day of acquisition, proceeds
at the rate on the day of disposal. The tax year runs from 6 April to 5 April. The
annual exempt amount has been 3,000 pounds since April 2024, and the rates on shares
rose from 10%/20% to 18%/24% for disposals from 30 October 2024; the estimate uses the
higher rates, apportioned by the gains on each side of the change.

Quantities are restated in post-split units - a split changes neither the pool's cost
nor the identity of the shares - and shares transferred in join the pool at their
carried cost translated on the day they arrive.

## 4. The demonstration's years

| Year | Net | Taxable |
| --- | --- | --- |
| US 2024 (USD) | -82,311 | carried forward |
| US 2025 (USD) | -194,789 | carried forward |
| US 2026 to 18 Sep (USD) | -214,469 | carried forward |
| UK 2024/25 (GBP) | -59,913 | nil |
| UK 2025/26 (GBP) | -92,847 | nil |
| UK 2026/27 to 18 Sep (GBP) | +8,658 | 5,658 |

```bash
meridian book gains --regime uk
```

Relief for tax paid in one country against the other's liability (the US-UK treaty's
foreign tax credit) is out of scope; the point here is that the gains themselves differ.
