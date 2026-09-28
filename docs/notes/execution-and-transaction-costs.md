# Execution and transaction cost analysis

A rebalance is a set of weights until someone trades it. Between the portfolio
manager's decision and the shares landing in the account there are several steps:
- the order management system;
- an algorithm that cuts the order into slices;
- a market that moves while it trades, and moves because it trades;
- an allocation that shares the fills among the accounts that wanted them.

Transaction cost analysis asks what all of that cost and where the cost came from.

This note describes how Meridian does each step, and why the cost of the Day 7
rebalance can be decomposed exactly. That is something a real desk can never do.

**Implementation:** [`execution/orders.py`](../../src/meridian/execution/orders.py),
[`execution/market.py`](../../src/meridian/execution/market.py),
[`execution/algorithms.py`](../../src/meridian/execution/algorithms.py),
[`execution/almgren_chriss.py`](../../src/meridian/execution/almgren_chriss.py),
[`execution/allocation.py`](../../src/meridian/execution/allocation.py),
[`execution/tca.py`](../../src/meridian/execution/tca.py),
[`services/demo_execution.py`](../../src/meridian/services/demo_execution.py),
[`reporting/client_pack.py`](../../src/meridian/reporting/client_pack.py) ·
**Decisions:** [ADR 0036](../adr/0036-orders-are-a-checked-state-machine-in-fix-states.md) to
[ADR 0040](../adr/0040-the-client-report-is-assembled-from-the-modules-own-objects.md)

---

## 1. Orders

An order is a history, not a number. Its states are FIX's `OrdStatus` (tag 39), so a
broker's execution report maps onto them one for one:

```
PENDING_NEW ──release──> NEW ──fill──> PARTIALLY_FILLED ──fill──> FILLED
     │                    │                   │
     └──> REJECTED        └──────> CANCELLED / EXPIRED <──┘
```

**A parent order** is the block the desk works. It owns **child orders**, one per
slice of the algorithm's schedule. A child that is not done by the end of its slice
is cancelled, and the rest rolls into the next child.

Every transition is an event in the audit trail. After every event the order checks
three things:
- that `cumulative + leaves = quantity`;
- that the average price is the fill-weighted mean, recomputed from the fills;
- that the trail is in time order.

An overfill, a fill after cancellation or a fill through the limit price is refused.

On the demonstration day, 26 parent orders became 676 child orders and 10,140 fills.

## 2. The market, minute by minute

Day 2's market data gives each stock's close, daily volatility, average volume and
spread. Execution needs the shape of the day as well, so each stock's day is
simulated on 390 one-minute bars:

| Component | Model |
| --- | --- |
| Volume | the U-shape every equity market shows: heavy at the open, a lull at lunch, heaviest into the close; scaled to the stock's ADV, with day-level and bar-level noise |
| Price | a random walk whose minute variance follows the same U-shape, summing to the daily variance; the day opens away from the previous close by an overnight gap |
| Half-spread | paid on every fill |
| Temporary impact | `η σ √(q / V)` on a fill of `q` shares in a bar of `V`: the square-root law, lasting only for that fill |
| Permanent impact | `γ σ q / ADV`: the mid moves for the rest of the day (Almgren–Chriss) |

The simulator keeps **both price paths**: the market as it would have been without
our trades, and as it was with them. A real trading desk only ever sees the second.
That is what makes the cost decomposition below exact, and what makes a calibration
checkable. The same approach gave the Day 5 risk model a universe whose true risk
is known.

## 3. Algorithms

| Algorithm | Schedule | Strength | Weakness |
| --- | --- | --- | --- |
| **TWAP** | even in time | predictable | blind to volume |
| **VWAP** | the expected volume curve | tracks the benchmark institutions are judged on | ignores the price |
| **POV** | a fixed share of realised volume | adapts to the day | finish time unknown; may not finish |
| **IS** | the Almgren–Chriss trajectory | trades impact against the risk of the price moving | front-loads, pays more impact |
| **Close** | the last ten minutes | the index-fund benchmark | cannot finish a large order |

Every algorithm is capped at **25% of any minute's volume**. What is not done by the
end of the window expires and is charged opportunity cost.

**Almgren–Chriss.** Linear temporary impact `η`, permanent impact `γ` and price
variance `σ²` give the optimal holdings

```
x_j = X sinh(κ(T − t_j)) / sinh(κT),    2(cosh κτ − 1)/τ² = λσ² / η̃,    η̃ = η − ½γτ
```

The risk-neutral trader (`λ = 0`) trades evenly. Urgency `κT` front-loads the order.
Sweeping `λ` traces the frontier of expected cost against its standard deviation.

The simulator's temporary impact is the square-root law, so the linear `η` is the one
that matches it at the order's own average rate. The trajectory is therefore optimal
to first order.

**The algorithm wheel.** The desk routes by the order's size as a share of ADV:
- under 2% → VWAP;
- 2–10% → IS at urgency 1.5;
- over 10% → POV at 15%.

The Day 7 rebalance, spread across three accounts, is mostly small. Three Tokyo names
are 18–49% of their daily volume, so they cannot finish in a day and expire with
shares left.

## 4. Allocation

Three accounts follow the model. They are the demonstration account, the Balanced
Pension's equity sleeve (0.45×) and an institutional mandate (2.4×). Their 78 orders
become 26 blocks, one per stock and side, so the accounts never compete in the market.
Fills are shared back by the rules regulators write down (FCA COBS 11.3, the SEC's
guidance on aggregated orders):
- **one price for everyone**: the block's average;
- **pro rata** when the block is not completed, in whole shares, with the odd shares
  by largest remainder;
- **no account receives more than it asked for**, and allocations below a minimum go
  to the others;
- the allocation rule is fixed **before** the block is worked.

A Hypothesis property test checks, over random fill sizes, that allocations are whole
shares, add up to the fill, never exceed a request, and give every account the same
fill rate to within a share.

## 5. Implementation shortfall

Against the paper portfolio (every share at the decision price `P_d`, the previous
close), the shortfall of an order of `X` shares with `q_i` filled at `p_i` splits
exactly:

| Component | Formula | What it is |
| --- | --- | --- |
| delay | `s X (P_0 − P_d)` | the move between the decision and the order's arrival |
| spread | `Σ q_i m_i h` | half the bid-ask spread |
| temporary impact | `Σ q_i m_i θ_i` | the square-root cost of each fill |
| permanent impact | `s Σ q_i (m_i − u_i)` | our earlier fills' lasting effect on the price |
| timing | `s Σ q_i (u_i − P_0)` | where the market went on its own while we traded |
| opportunity | `s (X − Σq_i)(P_c − P_0)` | the shares not traded, marked at the close |
| fees | commission | 2 bp |

Here `m` is the mid we traded against, `u` is the mid without us, and `s` is +1 to buy.
The last four rows need `u`, which only a simulator has. Every order checks that its
components add up to the shortfall computed directly from its fills.

**The day, 21 September 2026** (26 blocks, $20.3m at decision prices):

| | bp |
| --- | --- |
| delay | −2.6 |
| spread | +2.5 |
| temporary impact | +5.2 |
| permanent impact | +0.2 |
| timing | −12.1 |
| opportunity | −3.1 |
| fees | +2.0 |
| **shortfall** | **−7.9** |

The shortfall splits into two parts:
- **the costs the desk controls** (spread, impact, fees): **+9.8 bp**;
- **the market's own move** (delay, timing, opportunity): **−17.7 bp**.

The market moved in the account's favour on this day. On another day it will not. That
is why a desk is judged on the first number, and why a single day's shortfall says
little about the desk.

**The same day, every algorithm** (each block re-run on the identical simulated day):

| | TWAP | VWAP | POV | IS | Close |
| --- | --- | --- | --- | --- | --- |
| controllable cost, bp | 10.6 | 10.4 | 21.9 | 10.8 | 21.3 |
| share of value traded | 98.4% | 98.4% | 96.3% | 98.4% | 94.1% |

POV and Close pay twice as much. Both concentrate their trading: POV into the minutes
before it finishes, Close into its last ten minutes. Close also leaves the most undone.

**The VWAP benchmark** can flatter. An order that trades all day into a price it
pushes up itself can beat its own VWAP and still cost its owner a great deal. That is
why the shortfall against the decision price is the primary measure here, and VWAP
slippage only a secondary one.

## 6. Is the model right? Calibration with the answer known

The desk's history is 400 simulated orders across the account's stocks: sizes from
0.2% to 25% of ADV, every algorithm. The square-root coefficient is fitted through the
origin two ways:

| Fitted from | Coefficient | 95% interval | R² |
| --- | --- | --- | --- |
| impact measured by the simulator (steady-rate orders) | 0.355 | 0.353 – 0.357 | 1.00 |
| what a desk observes: execution cost against arrival, less the spread | 0.175 | −0.04 – 0.39 | 0.01 |
| **the truth** | **0.350** | | |

Measured directly, the coefficient is recovered to within 1.5%. From the prices a desk
actually sees, the market's own moves drown the impact: 400 orders give an interval
that includes zero. This is why brokers estimate impact models from millions of
orders, and why a small desk should borrow its broker's model rather than fit its own.

The **pre-trade estimate** (commission, half the spread, square-root impact at an even
pace, half the permanent impact) averages 16.4 bp against 18.5 bp realised, with a
correlation of 0.88. It is slightly low, because front-loaded and POV schedules pay
more impact than an even pace.

## 7. The client report

The pack is nine A3 pages written to one PDF:
1. the cover;
2. the summary;
3. holdings and tax;
4. the Day 4 factsheet;
5. the Day 5 risk report;
6. the Day 6 compliance report;
7. the Day 7 proposal;
8. trading and costs;
9. methodology.

Every page is drawn from the objects the modules themselves use; nothing is re-keyed.
So the NAV on the summary is the valuation's, and the trading costs are the
allocations' shortfall. The PDF carries its metadata and no creation date, so the
same data gives the same file.

## What is simplified

- **One day, one venue.** There is no smart order routing across lit and dark venues,
  and no auction mechanics beyond the heavier closing volume.
- **Impact without decay.** Temporary impact vanishes after its fill; permanent impact
  lasts the day. Models with transient impact (Obizhaeva–Wang, propagator models) sit
  between the two.
- **Carrying over.** An expired block is not carried to the next day. On a real desk
  the Tokyo names would continue on the 22nd.
- **Fixed income** goes to a separate desk by request for quote, and is not simulated.

## References

- Perold, A. (1988), "The implementation shortfall: paper versus reality", *Journal of Portfolio Management*.
- Almgren, R. and Chriss, N. (2000), "Optimal execution of portfolio transactions", *Journal of Risk*.
- Almgren, R., Thum, C., Hauptmann, E. and Li, H. (2005), "Direct estimation of equity market impact", *Risk*.
- Kissell, R. and Glantz, M. (2003), *Optimal Trading Strategies*. — the shortfall decomposition.
- Bouchaud, J.-P., Bonart, J., Donier, J. and Gould, M. (2018), *Trades, Quotes and Prices*. — the square-root law.
- FIX Trading Community, FIX 4.4 / 5.0 specification: `OrdStatus` (tag 39), `ExecType` (tag 150).
- FCA Handbook COBS 11.3 (aggregation and allocation); MiFID II RTS 27/28 (best execution reporting).
