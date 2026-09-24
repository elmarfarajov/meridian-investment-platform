# Performance measurement: which return, and why

"What was the return?" has more than one right answer. The portfolio manager, the
client and the consultant each ask a different question, and each needs a different
number. This note sets out the three the platform computes, how they are computed from
the book of record, and how far apart they are on the demonstration account.

**Implementation:** [`performance/returns.py`](../../src/meridian/performance/returns.py),
[`performance/contributions.py`](../../src/meridian/performance/contributions.py),
[`performance/statistics.py`](../../src/meridian/performance/statistics.py) ·
**Decision:** [ADR 0019](../adr/0019-returns-are-chained-daily-from-the-value-bridge.md)

---

## 1. Time-weighted return

The time-weighted return (TWR) measures the manager. It removes the effect of the
client's deposits and withdrawals, so a manager is not flattered by money that arrived
just before a rally, or blamed for money withdrawn at the bottom. GIPS requires it, and
benchmarks are compared against it.

With a valuation every day it is exact. Each day's return is that day's investment
result divided by the capital at risk:

```
r_t = result_t / (NAV_{t-1} + flows_t)          TWR = (1 + r_1)(1 + r_2)...(1 + r_n) - 1
```

The **result** is not `NAV_t - NAV_{t-1} - flows_t` recomputed here. It is the value
bridge's own sum of price, currency, income and costs (Day 3,
[ADR 0017](../adr/0017-the-value-bridge-is-exact.md)), so every daily return reconciles
to the ledger. Flows are counted at the **start of the day**: money deposited on a day
is at risk from that day's close, because that is when the demonstration account
invested it. The other convention (end of day) would give the deposit no return on its
first day. The choice is written down in the ADR so every report uses the same one.

## 2. Money-weighted return

The money-weighted return (MWR) measures the client's own experience. It is the
internal rate of return of the client's cash flows: the rate that discounts the
opening value, every deposit and withdrawal, and the closing value to zero. It *does*
depend on when the client moved money, because the client chose when.

`xirr` solves it on actual days (ACT/365) with the bracketing solver from Day 1. It is
shown annualised for the since-inception figure and over the period when compared with
the TWR year by year.

## 3. Modified Dietz

Before daily valuation was cheap, firms approximated the return from just the opening
and closing values and the flows, weighting each flow by the part of the period it was
invested:

```
R = (V_end - V_start - sum F_i) / (V_start + sum w_i F_i)        w_i = (L - d_i) / L
```

Here `L` is the length of the period in days and `d_i` is the number of days before
flow `i` arrived (counted with the same start-of-day convention). Modified Dietz is a
money-weighted measure in disguise. It tracks the IRR, not the TWR.

## 4. The three on the demonstration account

The account had three flows: a transfer in kind worth 62k in May 2024, a deposit of
500k on 3 March 2025, and a withdrawal of 250k on 15 December 2025, close to the low.

| Period | Time-weighted | Money-weighted (period) | Modified Dietz |
| --- | ---: | ---: | ---: |
| 2024 (from 2 April) | -14.19% | -14.16% | -14.16% |
| 2025 | -7.90% | -8.44% | -8.44% |
| 2026 (to 18 September) | +19.90% | +19.90% | +19.90% |
| Since inception | -5.24% | -5.32% | -5.32% |

In 2026 there were no flows, and the three agree to the last digit, as they must. In
2025 the deposit meant more money was invested through the autumn fall, and the
withdrawal took money out near the bottom. So the client's money did 54 bp worse than
the manager's decisions. Both numbers are right; they answer different
questions. Modified Dietz stays within 0.4 bp of the IRR in every year.

![Which return](../images/return-methods.png)

## 5. Contributions

The portfolio's daily return is also split holding by holding
(`performance.contributions.decompose`). Each holding's contribution is its opening
value at risk times its return. That return has three parts: the local price move,
income (dividends and coupons from the ledger), and the currency move on the closing
local value. Cash and everything cash-like forms one exposure per currency. Costs are
their own line. On every one of the 619 days, the exposures and the costs add up to the
day's result: the largest daily residual is 9e-11 dollars, and the run refuses to write
anything above 1e-10.

Linked over time with Cariño's factors (the same method as the attribution, see
[the attribution note](performance-attribution.md)), the contributions add up to the
-5.24% time-weighted return exactly.

![Contributions](../images/contribution-to-return.png)

## 6. Risk

A return means little without the risk taken to earn it. The platform computes the
standard measures from daily returns, annualised with 252 days and a flat 4% risk-free
rate. The since-inception figures, portfolio against the policy benchmark:

| Measure | Portfolio | Benchmark |
| --- | ---: | ---: |
| Annualised return | -2.16% | -3.46% |
| Volatility | 10.95% | 11.19% |
| Sharpe ratio | -0.56 | -0.67 |
| Sortino ratio | -0.79 | -0.91 |
| Maximum drawdown | -23.0% | -22.6% |
| Daily VaR / ES 95% | -1.08% / -1.41% | -1.21% / -1.54% |

Against the benchmark, the tracking error is 5.66% and the information ratio 0.23. Beta
is 0.85, up capture 72% and down capture 93%, and the portfolio beat the benchmark on
51% of days. Rolling 63-day windows show how these moved. Beta peaked above 1.0 in the
summer of 2025 and has been below 0.9 since.

![Rolling risk](../images/rolling-risk.png)

## 7. What is stored

`meridian perf run --persist` stores one row per day in `performance_returns`: capital,
result, the portfolio's return and the benchmark's. Any period can then be relinked
from SQL. The attribution is stored separately (see the attribution note), because
linked effects are not additive across periods.
