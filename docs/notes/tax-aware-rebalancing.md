# Tax-aware rebalancing

A rebalance buys a reduction in risk with tax and trading cost. A taxable account pays
tax on every gain it realises, so it cannot simply trade to its target the way an index
fund does. The question each time is how much tracking error a dollar of tax buys. The
answer depends on:
- which lots are sold;
- whether a loss can be harvested;
- what the wash-sale rule forbids.

This note covers:
- the optimiser that answers that question;
- the rounding that turns its answer into orders;
- the frontier that shows the whole trade-off;
- the simulation that measures what it is worth over years.

**Implementation:** [`optimisation/rebalance.py`](../../src/meridian/optimisation/rebalance.py),
[`optimisation/taxes.py`](../../src/meridian/optimisation/taxes.py),
[`optimisation/constraints.py`](../../src/meridian/optimisation/constraints.py),
[`optimisation/rounding.py`](../../src/meridian/optimisation/rounding.py),
[`optimisation/frontier.py`](../../src/meridian/optimisation/frontier.py),
[`optimisation/backtest.py`](../../src/meridian/optimisation/backtest.py),
[`services/demo_optimisation.py`](../../src/meridian/services/demo_optimisation.py) ·
**Decisions:** [ADR 0031](../adr/0031-tax-aware-rebalancing-is-a-conic-programme.md) to
[ADR 0035](../adr/0035-tax-alpha-is-measured-on-liquidation-value-over-simulated-paths.md)

---

## 1. The problem

Everything is a fraction of net asset value. The decision variables are:
- the weight **bought** of each asset;
- the weight **sold** from each tax lot.

So the optimiser chooses how much of a stock to sell and also which lots to sell it
from. This is the *specific identification* a US taxpayer may elect with a broker.

```
minimise    λ · TE(w)²  +  tax(sold)  +  cost(bought, sold)  +  π · (soft-rule excess)
subject to  w = w₀ + bought − Σ_lots sold          (weights after the trades)
            0 ≤ sold ≤ each lot                     (no short sales)
            cash within its band                    (after costs)
            the mandate's rules, compiled           (Day 6)
            no purchase the wash-sale rule forbids
```

| Term | Form | Why this form |
| --- | --- | --- |
| Tracking error | `252 (‖F^½ Xᵀ a‖² + ‖D^½ a‖²)`, with `a` the active weights in the Day 5 model's coverage assets | the factor form is a second-order cone; the covariance matrix is never formed |
| Tax | `Σ_lots t_lot · sold_lot`, with `t = rate(term) × (price − basis) / price` | linear, per lot; negative for a loss (a saving) |
| Cost | `(commission + ½ spread) · x + η σ √(NAV / ADV) · x^1.5` | the square-root impact law used by commercial cost models |

A fund enters through its **risk row**: its constituents in index weights, plus its own
basis. So the optimiser sees a fund's risk exactly as the Day 5 risk report does.

### Tax rates

| Holding period | Rate | Of which |
| --- | --- | --- |
| a year or less (short-term) | 40.8% | 37% ordinary income plus 3.8% net investment income tax |
| more than a year (long-term) | 23.8% | 20% plus 3.8% |

Accrued interest on a bond is part of what the bond is worth and of what a sale receives.
It is income, not a capital gain, so the gain is measured on the clean price.

### The solver

The problem is convex: a second-order cone for the risk, and the power cone
`t^{2/3} · 1^{1/3} ≥ x` for impact. **Clarabel**, an interior-point conic solver, solves
it through cvxpy.

Two details of the formulation turned out to matter:

1. **Impact is written as a 3-D power cone.** cvxpy's default rewrites `x^1.5` as a tower
   of second-order cones. On trades of a few basis points, that tower stalled the solver
   short of its tolerances in a third of the test cases.
2. **Nothing is pinned by an equality to the edge of its cone.** "Do not buy this stock",
   the wash-sale rule, pinned `buy ≥ 0` at zero. "No tobacco", an exclusion, pinned
   `|w| ≤ 0`. Both leave the feasible set without an interior, and an interior-point
   method needs one. Such variables are removed from the problem instead.

Other safeguards:
- A ridge of 10⁻⁶ on squared trades (a hundredth of a basis point on a 1% trade) makes
  the optimum unique when tax is ignored and the lots of one asset become
  interchangeable.
- The objective is scaled to basis points.
- If Clarabel fails, the chain falls back to Clarabel with more iterations, then SCS.

## 2. Rules that are not convex

Two of the mandate's rules cannot be written as convex constraints. Both are met in
**rounds**, and every round is recorded.

**Wash sales.** A loss is disallowed if the same stock is bought within 30 days. The
rebalance repairs this:
1. solve;
2. find every stock whose loss lots are sold while it is also bought;
3. bar the purchase and solve again.

Two or three rounds settle it. On the demonstration day, Roche, Apple and Johnson &
Johnson are barred. These are the stocks where the optimiser wanted to harvest the loss
*and* keep the exposure. It now buys correlated substitutes instead.

A loss on a lot bought in the last 30 days is valued at zero before the solve. That part
of the rule looks backwards.

**An active-share floor.** The mandate asks for at least 30% active share: the account
must not be a closet index fund.

Active share is half the sum of absolute active weights. That is convex, so a *floor* on
it is not. The optimiser uses the **convex-concave procedure**:
- Fix the sign `s` of each active weight. Then `½ Σ sᵢ aᵢ` is a linear function that
  never exceeds active share, and requiring it to clear the floor is a convex
  restriction that guarantees the floor.
- The signs are updated from each solution until they settle. Each round is feasible,
  and each is no worse than the last.
- The procedure starts twice, from the current portfolio's signs and from the
  unrestricted solution's, and keeps the better result. Each start finds a local
  optimum.

On the demonstration day:
- The unrestricted solution would cut active share to 12.7%.
- The rounds hold it at 30.0%.
- The tracking error is 2.64% where it would otherwise be 2.20%. This is the price of
  the floor.

**Limits inside a buffer.** Every limit is met 5 bp inside. The optimiser measures
weights its own way and the compliance engine its own. A limit met to the last decimal
by one can be a breach to the other.

## 3. Lots

The lots of one stock differ only in their tax. Per dollar sold, the cheapest lot is the
one with the lowest `rate × gain / price`. This is not always the long-term one:

| Lot | Gain | Rate | Tax per dollar sold |
| --- | --- | --- | --- |
| young, 10% gain | short-term | 40.8% | 4.1% |
| old, 40% gain | long-term | 23.8% | 9.5% |
| any loss | either | — | a saving |

To measure what choosing lots is worth, the proposal's own trades are relieved four
ways:

| Rule | Tax on the proposal's trades |
| --- | --- |
| **Chosen lots (specific identification)** | **−$96.9k** |
| Highest cost first | −$96.9k |
| First in, first out (the broker's default) | −$94.7k |
| Last in, first out | −$51.8k |

## 4. From weights to orders

The optimiser trades fractions of NAV. A broker takes:
- whole shares;
- board lots where the market has them (100 shares in Tokyo);
- tickets above a minimum size (here $10,000).

Rounding each trade separately can break the cash band, for example when many buys all
round up. So rounding is its own small **mixed-integer programme**, solved by HiGHS:

```
minimise    Σ |order value − continuous trade value|
subject to  each order a whole number of lots, in the continuous trade's direction
            each order zero or at least the minimum ticket     (binary per asset)
            no sale larger than the position
            cash after the orders within its band
```

Sales are then allocated to lots at the lowest tax per unit first. On the demonstration
day:
- 27 orders;
- a total drift of $988 from the continuous trades;
- tracking error 2.64% before rounding and 2.64% after.

## 5. The frontier

Every rebalance sits somewhere on a trade-off between the tax it realises and the
tracking error it leaves. Two sweeps map that trade-off:
- **Tax capped (epsilon constraint).** Minimise tracking error with the tax realised
  capped at a budget. The budget runs from the least tax any rebalance can realise
  without raising the tracking error, to the tax a tax-blind manager pays.
- **Risk priced.** Minimise `λ TE² + tax + cost` over a ladder of `λ`.

With the active-share floor, each solve is a local optimum. So the **frontier is the
lower envelope** of everything both sweeps found; the rest are drawn as dominated. Every
point is a full rebalance, with the mandate, the cash band, the wash-sale rule and the
floor all holding.

The demonstration account starts at 5.80% tracking error:

| Rebalance | Tax | Tracking error |
| --- | --- | --- |
| cheapest end of the frontier | −$130k (harvested losses pay for the move) | 4.17% |
| **the proposal (λ = 10)** | **−$96.9k** | **2.64%** |
| tax-aware, letting losses sit | −$36.7k | 2.74% |
| tax-blind (FIFO) | +$4.1k | 1.77% |

The proposal lies on the frontier, and so does the tax-blind rebalance, at its closest
end. What differs is where each chooses to stand. From the tax-blind point to the
proposal:
- the tax bill falls by about $100k;
- the tracking error rises by 0.9 percentage points;
- the price is about $11k of tax per 0.1 point of tracking error.

## 6. Is it worth it? Tax alpha

One day's saving says little. The question is years.

**The account and its index.**
- A taxable account tracks a 100-stock index: the largest stocks of the Day 5
  estimation universe, cap-weighted.
- The markets are simulated month by month from the Day 5 factor model.
- The index is reconstituted every quarter, which forces an indexer to trade.

**The managers.** Four managers run side by side on the very same prices:

| Manager | What it does |
| --- | --- |
| buy and hold | invests once, never trades |
| tax-blind | tracks the index as closely as it can, FIFO lots, ignores tax |
| tax-aware | trades tracking error against tax within a 1.5% budget, choosing lots, and lets losses sit |
| tax-aware, harvesting | also harvests losses and buys substitutes |

**The tax ledger** is the US one:
- short- and long-term netting each year (Schedule D);
- a $3,000 ordinary-income offset, with the remaining losses carried forward;
- tax paid from the account each December;
- the wash-sale rule in both directions: a loss sold within 30 days of buying is
  disallowed and joins the replacement's basis, and a stock sold at a loss is not
  bought back for 30 days.

**Losses need something to offset.** The client realises short-term gains elsewhere,
2% of the account's value a year. Harvested losses offset those gains, and the saving
is credited to the account. A harvested loss is valued at the short-term rate *less*
the long-term rate. It saves 40.8% now, but it lowers the basis, and at the end that
gain comes back at 23.8%. A loss is worth the rate difference, not the full rate. The
first version valued losses at the full rate. It harvested three times as much, churned
the account and *lost* after-tax return. The valuation is the design.

**Tax alpha** is the annual after-tax return over the tax-blind manager's. It is
measured on the value the account would have **if liquidated at the end**, with every
remaining gain taxed. That is the honest comparison, since deferral that ends in a tax
bill is worth less than it looks on a statement.

Results over 16 paths of 36 months, as recomputed in the
[Day 7 revisit](the-tax-code-as-the-irs-writes-it.md). The revisit:

- counts the holding period by the calendar;
- nets the carryover as Schedule D does;
- makes the pre-tax return time-weighted;
- adds tax saved: the tax drag avoided, apart from tracking luck.

| Manager | Pre-tax | After tax | Tax alpha (liquidated) | Tax saved | Tax alpha (as held) | Tracking error | Turnover a year |
| --- | --- | --- | --- | --- | --- | --- | --- |
| buy and hold | 6.17% | 4.69% | +0.22% | +0.35% | +0.85% | 0.83% | 0% |
| tax-blind | 6.29% | 4.47% | — | — | — | 0.08% | 91% |
| tax-aware | 6.26% | 5.02% | **+0.55%** | +0.58% | +1.52% | 0.58% | 44% |
| tax-aware, harvesting | 6.11% | 5.01% | **+0.54%** | +0.73% | +1.47% | 1.21% | 161% |

What the table shows:
- **Most of the value is in not realising gains:** choosing lots and deferring. The
  tax-aware manager earns half a percent a year after liquidation, with less tracking
  error than buy and hold, and trades half as much as the tax-blind manager.
- **Harvesting saves the most tax**: 0.73% a year of drag avoided, against 0.58%
  without harvesting. But it spends that saving on turnover and tracking error, 0.15%
  a year before tax. On liquidation value, with outside gains of 2% a year, the two
  tax-aware managers are within one standard error of each other (about 0.1%).
- Harvesting earns more when the client has more gains elsewhere to offset, over longer
  horizons, and when the account is never liquidated (a step-up in basis at death, or
  a gift to charity). The "as held" column is the upper bound for that case.
- These figures are the same order as the industry's published estimates of tax alpha:
  1–2% a year pre-liquidation, much less after it.

## 7. What is simplified

- **Federal tax only**: no state tax, no qualified-dividend rate. Dividends are left out
  of the simulation, since every manager would receive the same ones.
- **The wash-sale test is by security.** "Substantially identical" is not modelled across
  share classes or ETFs on the same index.
- **Costs are a model, not an execution record.** Impact uses a coefficient of 0.1 on
  the square-root law, for trades that are a small share of daily volume.
- **The frontier and the proposal are local optima** of a non-convex problem. Two
  starts and two sweeps make it unlikely that a much better point is missed, but not
  impossible.
- **The backtest is monthly**, so a wash-sale window of 30 days spans one rebalance. A
  daily or event-driven harvester would find more losses, and pay more to trade them.

## References

- Grinold, R. and Kahn, R. (2000), *Active Portfolio Management*, 2nd ed. — tracking error, active share and risk aversion.
- Almgren, R., Thum, C., Hauptmann, E. and Li, H. (2005), "Direct estimation of equity market impact", *Risk*. — the square-root law.
- Lipp, T. and Boyd, S. (2016), "Variations and extension of the convex–concave procedure", *Optimization and Engineering*.
- Goulart, P. and Chen, Y. (2024), "Clarabel: an interior-point solver for conic programs with quadratic objectives".
- Huangfu, Q. and Hall, J. (2018), "Parallelizing the dual revised simplex method", *Mathematical Programming Computation* (HiGHS).
- Arnott, R., Berkin, A. and Ye, J. (2001), "Loss harvesting: what's it worth to the taxable investor?", *Journal of Wealth Management*.
- Chaudhuri, S., Burnham, T. and Lo, A. (2020), "An empirical evaluation of tax-loss-harvesting alpha", *Financial Analysts Journal*.
- Internal Revenue Code §1091 (wash sales) and §1211–1212 (capital loss limits and carryovers).
