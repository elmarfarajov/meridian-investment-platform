# Meridian

**An institutional investment management platform: the book of record, the analytics and the reporting behind a multi-currency, multi-account client portfolio.**

[![CI](https://github.com/elmarfarajov/meridian-investment-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/elmarfarajov/meridian-investment-platform/actions/workflows/ci.yml)
[![Python 3.10 – 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-1B3A6B)](https://www.python.org/)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-1F8A80)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-6A4C93)](https://docs.astral.sh/ruff/)
[![Tests](https://img.shields.io/badge/tests-929-2E7D5B)](tests)
[![License: MIT](https://img.shields.io/badge/license-MIT-4A5C75)](LICENSE)

Asset managers do not run on spreadsheets. They run on systems like BlackRock's Aladdin,
Charles River IMS and SimCorp Dimension: one place that holds every position and tax lot,
values it every night, attributes the return against a benchmark, decomposes the risk,
checks every proposed trade against the mandate, and produces the statement the client
reads. Meridian is a working implementation of that spine, built from first principles.

It is a portfolio engineering project, not a commercial product. The point is to show the
reasoning: why money is a `Decimal` and never a float, why a curve's interpolation method
is a modelling decision rather than a detail, why an exchange calendar is generated from
statutory rules rather than loaded from a file that goes stale, and why duration alone is
not a risk measure.

---

## What it does today

```bash
meridian rates curve --tenors 0.25,1,2,5,10,30 --par 4.25,4.18,3.95,3.90,4.15,4.55
# Bootstraps a zero curve, one instrument at a time, and prints par, zero,
# discount factors and forwards side by side.

meridian rates bond 2034-05-15 --coupon 4 --issue 2024-05-15 --price 96.79
# Yield to maturity 4.500272%, modified duration 6.407, convexity 48.61,
# DV01 0.0629 per 100 of face, accrued 1.40 on 129/184 days.

meridian calendar ladder 2026-12-23 --calendars XNYS,XLON,TARGET,XTKS
# Where T+1 to T+3 land in each market, and in the joint calendar every leg
# of a cross-border trade has to clear.

meridian security validate US0378331005 HWUPKR0MPOU8FGXBT394
# ISIN and LEI, each against its own check-digit algorithm.

meridian market price --persist
# The end-of-day pricing run: three sources collected, 16,758 observations
# recorded with the time they arrived, 211 quality findings, 5,613 golden
# prices published, 143 price challenges raised.

meridian market history US-AAPL --known-at 2026-09-10
# The series as it stood that evening - not as it has since been restated.

meridian market xref FB --on 2021-06-01
# FB (ticker) on 2021-06-01 -> US-META. Ask for 2023 and it resolves to nothing.

meridian book run --persist
# Replays two and a half years of a four-currency account into a double-entry
# ledger - 190 entries, 23 realised lots, 620 valuation days - checks that the
# trial balance balances and the sub-ledger ties to the lots, and writes it.

meridian book bridge --from 2024-12-31 --to 2025-12-31
# Why NAV moved in 2025: flows +250.0k, price -419.5k, currency -16.4k,
# income +51.5k, costs -16.6k. Residual 0.

meridian book wash-sales
# Bayer sold at a loss and bought back 19 days later: 83,338 dollars
# disallowed and carried into the replacement lots' tax basis.

meridian book gains --regime uk
# The same disposals under UK same-day, 30-day and section 104 matching.

meridian book reconcile --as-of 2026-04-08
# The book against the custodian: every break with the cause that explains it.

meridian perf returns --yearly
# Time-weighted returns chained daily from the value bridge, against the
# policy benchmark: 2024 -14.19%, 2025 -7.90%, 2026 +19.90%.

meridian perf attribution --by sector
# Where the +306 bp active return came from: allocation -255, selection +634,
# interaction +128, currency -131, costs -71. Linked by Cariño; residual 1e-15.

meridian perf run --persist && meridian perf stored
# Daily returns and linked effects written for every report period, then read
# back from SQL and checked against the relinked active return.

meridian risk portfolio
# Volatility 12.2%, tracking error 5.8%: the market is two thirds of the
# account's risk; its tracking error is almost all stock-specific.

meridian risk backtest
# The account's forecasts scored against 530 days of outcomes: bias statistics
# with their band, beside what the true volatility scores; Kupiec,
# Christoffersen and the Basel traffic light.

meridian risk validate
# Ten years of a 500-stock universe whose true risk is known: EWMA against the
# sample against the truth, and why a sample covariance promises a riskless
# portfolio that is not.
```

---

## The charts

Every module ships a visual, not only numbers. All seventy-seven are in the
[gallery](docs/GALLERY.md) and are rebuilt from source with `meridian charts gallery`.

**From the benchmark's return to the portfolio's.** The account returned -5.24% against
-8.30% for its policy benchmark. Brinson-Fachler on local returns, with currency and
costs kept apart and index funds looked through, says where the 306 basis points came
from. The sector bets cost 255 bp; stock picking earned 634. Every effect is linked
over 619 days, so the bars add up to the active return exactly.

![The attribution bridge](docs/images/attribution-bridge.png)

**Returns compound; effects add.** Summing daily effects misses the compounded active
return by 16 bp, more than the whole energy sector's contribution. Cariño's factors
rescale each day so nothing is left over.

![Why effects have to be linked](docs/images/attribution-linking.png)

**Which return?** The time-weighted return judges the manager; the money-weighted
return judges the client's timing. In 2025 a deposit before the autumn fall and a
withdrawal near the low put the client 54 bp behind the manager. In 2026, with no
flows, all three methods agree to the last digit.

![Three returns](docs/images/return-methods.png)

**The page a client reads.** Returns by period, risk against the benchmark, the
attribution and the largest contributions, on one page drawn from the book of record.

![The performance report](docs/images/factsheet.png)

**Where the risk comes from.** A 21-factor fundamental model splits the account's 12.2%
volatility and 5.8% tracking error into the market, industries, styles, currencies and
stock-specific risk, exactly, by Euler's theorem. The market is two thirds of the risk;
the tracking error is almost all the stocks the account chose to own.

![Risk decomposition](docs/images/risk-decomposition.png)

**Is the forecast the right size?** A return divided by the forecast made the evening
before should have standard deviation one. Scored on ten years of a universe whose true
risk is known, the EWMA forecast stays within its band; the equal-weighted sample is late
into every crisis and late out of it.

![Bias statistics](docs/images/bias-statistics.png)

**An optimiser finds the errors in a covariance matrix.** With 500 stocks and 252 days
the sample covariance is singular and promises a riskless portfolio; it delivers 12%.
Shrinkage promises too little. The factor model delivers what it promises.

![Minimum-variance portfolios](docs/images/minimum-variance.png)

**Backtesting the account's VaR.** Every morning the model forecast a 99% VaR from what it
knew. The window turned out calmer than its own true risk, and Kupiec's test says so.

![VaR backtest](docs/images/var-backtest.png)

**Where did the value go?** Every day's change in net asset value is split into flows,
price, currency, income and costs, and the split is exact: the residual is printed on the
chart, and across 620 days its largest value is 1.8e-21 dollars. A 4-for-1 split is not a
75% loss and a dividend's ex-date drop is income, because price is measured on the
quantity held after corporate actions.

![Where the value went](docs/images/valuation-waterfall.png)

**A wash sale defers a loss; it does not destroy it.** Bayer was harvested at a loss and
bought back nineteen days later. The loss moves into the replacement lots' tax basis -
never their book cost - and each piece's holding period tacks by its own sold shares'
period. Drawing this chart found the lot engine tacking one replacement twice.

![A wash sale](docs/images/wash-sale.png)

**One book, two tax codes.** The household is a US person resident in the UK. The same
Bayer disposal reports nothing in the US and a gain of 10,243 pounds in the UK, where the
30-day rule matches the sale to the cheaper repurchase.

![One book, two tax codes](docs/images/us-vs-uk.png)

**A correction is a replay, not an edit.** The blotter keeps every version of every trade,
and the book is a pure function of it, so NAV as reported on each evening can be rebuilt
and set against NAV as now known: fifteen reports were wrong until a mispriced trade was
corrected at month-end.

![A correction is a replay](docs/images/restatement.png)

**Reconciliation is measured, not asserted.** Breaks planted where the answer is known in
generated custodian statements are all found with the right cause, and clean statements
raise nothing.

![Reconciliation against the custodian](docs/images/reconciliation-dashboard.png)

**A data quality rule that has only ever seen clean data has not been tested.** Meridian
plants faults whose location is known in a synthetic market that has fat tails,
volatility clustering and real exchange calendars, then counts what the rules find:
**100% recall and 97% precision** over 126 planted faults, with every false alarm a
genuine fat-tailed market move.

![Detection scorecard](docs/images/detection-scorecard.png)

**The textbook outlier test fails in exactly the situation it is needed for.** One bad
tick inflates the standard deviation the next ones are judged against, so they hide
behind it. The median and the MAD have a 50% breakdown point and do not move.

![Why the median, not the mean](docs/images/robust-vs-classical.png)

**A price has two dates: the day it describes and the day we learned it.** Corrections
are new records, never edits, so the series as it stood on any past evening can be
rebuilt - and the gap between that and today's restated history is the look-ahead a
backtest would otherwise enjoy.

![What we knew, and when](docs/images/point-in-time.png)

**No vendor is right every day.** The golden copy takes the highest-ranked source within
25 bp of the consensus, sets aside sources that resent yesterday's close, and records a
challenge wherever they disagree. Against the synthetic truth it is 50 times closer than
the best single vendor on its worst day.

![Three vendors, one price](docs/images/vendor-consensus.png)

**A split is not a crash.** Adjustment is a view derived from the raw history and the
event list, never an overwrite - and it recovers the generator's own economic value to
within a basis point.

![A split is not a crash](docs/images/split-adjustment.png)

**An identifier is not a name.** Tickers change and are reused; ISINs change when a
company redomiciles. Every mapping carries a validity interval and every lookup a date.

![An identifier is not a name](docs/images/identifier-timeline.png)

**Two markets that are open on different days are the reason a cross-border trade fails
to settle.** Meridian generates its calendars from statutory rules - Easter by the
Meeus/Jones/Butcher algorithm, US observed-day shifts, UK substitute days that chain, and
the Japanese equinoxes, which are astronomical events approximated by formula.

![Exchange trading calendars, 2026](docs/images/trading-calendar-2026.png)

**The par curve, the zero curve and the forward curve are three views of one set of
quotes,** and confusing them misprices everything downstream.

![Yield curve](docs/images/yield-curve.png)

**Interpolation is a modelling choice.** The three methods agree at every quoted pillar
and disagree everywhere else - most visibly in the forward curve, where linear
interpolation produces a sawtooth that looks like an arbitrage that is not there.

![Curve interpolation](docs/images/curve-interpolation.png)

**Duration is a straight line drawn through a curved function.** It always overstates the
loss from a rise in yields and understates the gain from a fall; convexity is the
correction, and at 300 basis points it is worth more than two points of face value.

![Price against yield](docs/images/price-yield.png)

**A trade whose legs settle in different markets has to clear both calendars.** These are
the days that produce failed settlements, missed coupons and stale marks.

![Settlement ladder](docs/images/settlement-ladder.png)

**The data model is drawn from the live SQLAlchemy metadata,** so the architecture diagram
cannot drift from the schema.

![Data model](docs/images/data-model.png)

---

## Architecture

The package is layered so each concern is testable on its own, and so nothing above the
persistence layer knows which database is in use.

```
meridian
├── core          value objects: Money, Currency, FX, identifiers, calendars,
│                 day counts, schedules, compounding, interpolation
├── domain        the business model: instruments, portfolios, accounts,
│                 positions, transactions
├── analytics     the quantitative layer: solvers, yield curves, bond mathematics
├── accounting    the book of record: double-entry ledger, trade blotter, settlement,
│                 tax lots and wash sales, income, valuation, the value bridge,
│                 US and UK tax reporting, custodian reconciliation
├── performance   time- and money-weighted returns, holding contributions, the
│                 benchmark, Brinson-Fachler attribution, Cariño linking, risk statistics
├── risk          a fundamental factor model: the estimation universe, exposures,
│                 cross-sectional regression, EWMA and GARCH covariance, Ledoit-Wolf,
│                 specific risk, Euler decomposition, VaR, stress tests, validation
├── persistence   SQLAlchemy 2.0 schema, explicit mappers, repositories, unit of work
├── marketdata    series, point-in-time storage, sources, adjustment, golden copy
├── quality       the data quality rules, the engine and the scoring
├── refdata       the security master: identifier cross-reference, golden records
├── services      application processes: the end-of-day pricing, accounting,
│                 performance and risk runs, the demonstration market, book and benchmark
├── viz           the house chart style and seventy-seven figures
├── cli           a thin Typer layer over tested functions
├── gallery       one definition of every chart, used by the docs and the tests
└── seed          a hand-made demonstration book to run everything against
```

**Dependencies point inwards.** `core` imports nothing from the platform. `domain` and
`analytics` import `core`. `persistence` maps `domain` to rows through explicit functions
rather than persisting the domain classes directly, so the schema can change for storage
reasons without loosening a domain invariant. Analytics code never imports SQLAlchemy.

---

## Engineering standards

| Concern | Decision |
| --- | --- |
| Money | `Decimal` end to end, banker's rounding, currency-tagged, no silent mixing. `Money.allocate` splits an amount so the parts always sum back to the whole. |
| Analytics | `float`, deliberately: this layer solves and differentiates. Values crossing into the ledger convert back to `Decimal` at the boundary ([ADR 0008](docs/adr/0008-decimal-in-the-ledger-float-in-the-analytics.md)). |
| Identifiers | ISIN, CUSIP, SEDOL, FIGI and LEI by their real check-digit algorithms, tested against published identifiers for Apple, Microsoft, BAE, Bayer, Toyota, Roche, Goldman Sachs, JPMorgan, Deutsche Bank, HSBC and Barclays. |
| Calendars | Eight markets generated from rules, not files, with composition for cross-border settlement, plus five business-day conventions and T+n arithmetic. |
| Day counts | Nine conventions, including the three that need a coupon period, a calendar or a maturity flag to be evaluated at all. |
| Numerics | Safeguarded Newton with a bisection fallback; non-convergence raises rather than returning a plausible wrong number. |
| Database | SQLite locally so a clone runs with no setup; the same suite runs against PostgreSQL 16 in CI. Fixed-scale `NUMERIC` columns, never floats. |
| Migrations | Alembic, with `alembic check` in CI failing the build if the models and the migrations drift apart. |
| Market data | Bitemporal: value date and knowledge time on every observation, corrections appended rather than applied ([ADR 0009](docs/adr/0009-bitemporal-market-data.md)). One published price per day from ranked consensus across sources ([ADR 0010](docs/adr/0010-golden-copy-by-ranked-consensus.md)). |
| Data quality | Thirteen rules across the five DAMA dimensions, robust statistics on event-adjusted returns, and detection measured against planted faults - 100% recall, 97% precision ([ADR 0013](docs/adr/0013-quality-rules-are-measured-against-planted-faults.md)). |
| Corporate actions | Eight types, applied to history as a derived view ([ADR 0011](docs/adr/0011-corporate-action-adjustment-is-a-view.md)) and to tax lots with basis conserved and holding periods tacked. |
| Book of record | A double-entry ledger at cost, balanced in base and local currency, with market value a valuation of it rather than an entry ([ADR 0014](docs/adr/0014-a-double-entry-ledger-at-cost-is-the-book-of-record.md)). The trial balance is also computed in SQL and held equal to the ledger. |
| Corrections | Trades are versioned, never edited; the book is a replay of the blotter as known at a moment, and a restatement is the difference between two replays ([ADR 0015](docs/adr/0015-the-book-is-a-replay-of-a-versioned-blotter.md)). |
| Tax lots | Holding period start, opening FX rate and wash sale adjustment carried on the lot, apart from book cost ([ADR 0016](docs/adr/0016-tax-basis-is-kept-apart-from-book-cost.md)); US Schedule D netting and Form 8949, UK same-day, 30-day and section 104 matching. |
| Value bridge | Flows, price, currency, income and costs, with a residual that must be zero - required by a property test over random multi-currency books ([ADR 0017](docs/adr/0017-the-value-bridge-is-exact.md)). |
| Reconciliation | On the custodian's settled terms, breaks classified by cause, measured against planted breaks ([ADR 0018](docs/adr/0018-reconciliation-is-on-the-custodians-terms-and-measured.md)). |
| Returns | Chained daily from the value bridge's own result, flows at the start of the day, so every return reconciles to the ledger ([ADR 0019](docs/adr/0019-returns-are-chained-daily-from-the-value-bridge.md)). |
| Attribution | Brinson-Fachler on local returns, currency and costs apart, funds looked through ([ADR 0020](docs/adr/0020-brinson-fachler-on-local-returns-with-currency-and-costs-apart.md)); linked by Cariño and stored per period ([ADR 0021](docs/adr/0021-attribution-is-linked-by-carino.md)). |
| Benchmark | A synthetic cap-weighted index generated in the same market as the book, in an 80/15/5 policy blend ([ADR 0022](docs/adr/0022-a-synthetic-benchmark-from-the-same-market.md)). |
| Risk model | A 21-factor fundamental model by constrained cross-sectional regression, estimated on a universe whose true risk is known ([ADR 0023](docs/adr/0023-a-fundamental-factor-model-on-a-universe-with-known-truth.md)); EWMA factor covariance ([ADR 0024](docs/adr/0024-ewma-factor-covariance-with-separate-half-lives.md)); specific risk and fund basis ([ADR 0025](docs/adr/0025-specific-risk-by-ewma-and-fund-basis-as-its-own-risk.md)). |
| Model validation | Bias statistics against their band and a truth yardstick, Kupiec, Christoffersen and the Basel traffic light; the risk run writes nothing if a control fails ([ADR 0026](docs/adr/0026-a-risk-model-ships-with-its-validation.md)). |
| Tests | 929 tests, including property-based tests (Hypothesis) for the invariants that must hold for every input: allocation conserves the total, rate conversions round-trip, monotone interpolation stays monotone. |
| Types | `mypy` with `disallow_untyped_defs` across the package; `ruff` for lint and format. |

---

## Quickstart

```bash
git clone https://github.com/elmarfarajov/meridian-investment-platform.git
cd meridian-investment-platform
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

meridian info                 # the effective configuration
meridian db init              # run the migrations (SQLite by default)
meridian db seed              # load the demonstration book
meridian charts gallery       # rebuild every figure in docs/images
meridian market quality       # score the demonstration feed and list the exceptions
meridian market price --persist   # run the end-of-day pricing process into the database
meridian book run --persist       # replay, check, value and reconcile the demonstration book
meridian book trial-balance --from-db   # the trial balance, computed in SQL
meridian perf run --persist       # returns and linked attribution for every report period
meridian perf factsheet --out factsheet.png   # the one-page performance report
meridian risk run --persist       # forecasts, factor history and exposures, after the controls
meridian risk report --out risk-report.png    # the one-page risk report
```

Point it at PostgreSQL by setting one environment variable, with no code change:

```bash
export MERIDIAN_DATABASE_URL=postgresql+psycopg://meridian:meridian@localhost:5432/meridian
```

Run the checks the way CI runs them:

```bash
ruff check src tests && ruff format --check src tests && mypy && pytest -q
```

---

## Documentation

| Document | What it covers |
| --- | --- |
| [Fixed income mathematics](docs/notes/fixed-income-mathematics.md) | Discounting, bootstrapping, clean and dirty price, duration, convexity, key rate durations, and the numerical method behind them |
| [Calendar conventions](docs/notes/calendar-conventions.md) | How each market's holidays are computed, the asymmetries that are easy to get wrong, and why calendars compose |
| [Market data quality](docs/notes/market-data-quality.md) | The rules, the robust statistics behind them, and how recall and precision are measured |
| [Corporate actions](docs/notes/corporate-actions.md) | Adjusting a history and adjusting a holding: factors, cost basis, holding periods and merger boot |
| [Point-in-time data](docs/notes/point-in-time-data.md) | Value date against knowledge time, restatements, and look-ahead bias measured |
| [The security master](docs/notes/security-master.md) | Identifiers that move, vendors that disagree, and how a golden record is built |
| [Portfolio accounting](docs/notes/portfolio-accounting.md) | The chart of accounts, posting rules, trade and settlement dates, income, and why the book is derived |
| [Tax lots and wash sales](docs/notes/tax-lots-and-wash-sales.md) | What a lot carries, the wash sale rule with its look-ahead, Schedule D, and the choice of lots |
| [UK share matching](docs/notes/uk-share-matching.md) | Same-day, 30-day and section 104 matching, and why the two codes disagree |
| [Valuation and the value bridge](docs/notes/valuation-and-the-value-bridge.md) | NAV, price against currency, and the exact decomposition of a change in value |
| [Reconciliation](docs/notes/reconciliation.md) | Comparing on the custodian's terms, classifying breaks by cause, and measuring it |
| [Performance measurement](docs/notes/performance-measurement.md) | Time-weighted, money-weighted and Modified Dietz, contributions, and the risk measures beside them |
| [Performance attribution](docs/notes/performance-attribution.md) | Brinson-Fachler, currency apart, funds looked through, and why effects have to be linked |
| [Benchmark construction](docs/notes/benchmark-construction.md) | A policy benchmark and a cap-weighted index built so attribution can use them |
| [The factor risk model](docs/notes/factor-risk-model.md) | Factors, descriptors, the constrained regression, a universe with known truth, and the account's risk |
| [Covariance estimation](docs/notes/covariance-estimation.md) | Why a sample covariance fails, Ledoit-Wolf, EWMA against GARCH, and a shrinkage that was tested and rejected |
| [Validating a risk model](docs/notes/risk-validation.md) | Bias statistics, the account's backtest and the three errors it caught, VaR four ways, stress tests |
| [Chart gallery](docs/GALLERY.md) | All forty-six figures, with what each one argues |
| [Architecture decisions](docs/adr) | Twenty-six records: what was decided, what the alternatives were, and what it costs |
| [Roadmap](docs/ROADMAP.md) | The nine modules, and the reasoning behind each |

---

## Roadmap

Built in daily increments; each day is an issue, a branch, a pull request and a tag.

| Day | Module | Status |
| --- | --- | --- |
| 1 | Foundation: money, identifiers, calendars, schedules, curves, bond analytics, domain model, persistence, migrations, CLI | ✅ Done |
| 2 | Market data: point-in-time prices, corporate actions, FX, quality rules, golden copy, security master | ✅ Done |
| 3 | Portfolio accounting: double-entry ledger, tax lots, wash sales, US and UK tax, daily valuation, value bridge, reconciliation | ✅ Done |
| 4 | Performance: time- and money-weighted returns, benchmark construction, Brinson-Fachler attribution, Cariño linking, risk statistics | ✅ Done |
| 5 | Risk: fundamental factor model, EWMA, GARCH and Ledoit-Wolf covariance, VaR four ways, stress tests, bias-statistic and VaR backtests | ✅ Done |
| 6 | Compliance: a rule DSL for mandate limits, pre- and post-trade checks | Planned |
| 7 | Tax-aware optimisation: rebalancing with lot selection and tax cost | Planned |
| 8 | Execution: order management, allocation, transaction cost analysis, client reporting | Planned |
| 9 | Platform: web API, role-based access, release | Planned |

---

## Licence

MIT. See [LICENSE](LICENSE).
