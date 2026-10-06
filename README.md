# Meridian

**An institutional investment management platform: the book of record, the analytics and the reporting behind a multi-currency, multi-account client portfolio.**

[![CI](https://github.com/elmarfarajov/meridian-investment-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/elmarfarajov/meridian-investment-platform/actions/workflows/ci.yml)
[![Python 3.10 – 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-1B3A6B)](https://www.python.org/)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-1F8A80)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-6A4C93)](https://docs.astral.sh/ruff/)
[![Release](https://img.shields.io/badge/release-v1.9.0-E07A29)](https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v1.9.0)
[![Validated against QuantLib](https://img.shields.io/badge/validated-QuantLib-1F8A80)](docs/notes/the-rates-engine-validated.md)
[![Tests](https://img.shields.io/badge/tests-1489-2E7D5B)](tests)
[![Docker](https://img.shields.io/badge/docker-compose-4E86C7)](docker-compose.yml)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1-6A4C93)](docs/notes/the-web-platform.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-4A5C75)](LICENSE)

Asset managers do not run on spreadsheets. They run on systems like BlackRock's Aladdin,
Charles River IMS and SimCorp Dimension: one place that holds every position and tax lot,
values it every night, attributes the return against a benchmark, decomposes the risk,
checks every proposed trade against the mandate, and produces the statement the client
reads. Meridian is a working implementation of that spine, built from first principles -
nine modules in nine days, and a web platform over all of them.

It is a portfolio engineering project, not a commercial product. The point is to show the
reasoning: why money is a `Decimal` and never a float, why a curve's interpolation method
is a modelling decision rather than a detail, why an exchange calendar is generated from
statutory rules rather than loaded from a file that goes stale, and why duration alone is
not a risk measure.

![Nine days, one platform](docs/images/nine-days.png)

## Run the whole platform

```bash
docker compose up --build
```

| Where | What |
| --- | --- |
| http://localhost:8000/docs | the API, interactive: sign in as `pm` / `pm-demo-2026` (or `analyst`, `trader`, `compliance`, `aliyeva`, `admin`, each `<name>-demo-2026`; the client is `client-demo-2026`) |
| http://localhost:3000 | Grafana, with the Meridian dashboard provisioned |
| http://localhost:9090 | Prometheus, scraping the API |

PostgreSQL 16, a migration job, the API (two workers, non-root, health-checked),
Prometheus and Grafana: the same stack CI builds and smoke-tests on every pull request.

![The architecture](docs/images/platform-architecture.png)

---

## Validated against QuantLib, empyrical, real markets and the tax authorities

After the nine days, each module is being revisited in order and held to a stricter
standard. Day 1 went first. Its rates engine had been tested against examples written by
the same hand as the code. It is now reconciled against **QuantLib**, the reference
library banks and vendors use, and against **the real US Treasury curve** and **the
Federal Reserve's own fitted curve**, every business day since 1990.

![Meridian against QuantLib](docs/images/quantlib-reconciliation.png)

The comparison is run like a reconciliation. Every difference is either fixed, or
explained in writing with the evidence for which side is right, and a test holds the set
of breaks to exactly the documented ones.

- **The calendars did not know their own history.** v1.0.0 disagreed with QuantLib on
  309 weekdays between 1990 and 2060. It applied rules to years before they existed
  (Martin Luther King Jr. Day before 1998, TARGET's Easter before 2000, Japan before its
  Happy Monday reforms). It also knew nothing of the closures no rule predicts: 9/11,
  Hurricane Sandy, five presidential days of mourning, the jubilees and the royal
  funeral. 72 breaks remain, all explained, and on each the evidence favours Meridian.
- **When the two references disagree, the astronomy decides.** Japan's equinox holidays
  are now computed (Meeus, chapter 27), not approximated. QuantLib's formula puts them a
  day early before 2000.
- **30/360 US had no February rule**, and 30/360 bonds were priced on calendar days
  rather than SIFMA's DSC/E. Both are fixed. Both day counts now match QuantLib on 19,884
  date pairs, and bonds match to 1e-12.
- **The fix exposed a design fault, and that was fixed too.** Adding one holiday
  reshuffled every simulated price from Days 2 to 9. Markets now have a *scheduled*
  calendar, which the simulation steps through, and an *actual* one, which settlement
  uses. The simulated history keeps its random path; prices are published only on the
  days the market actually opened, and every Day 2-9 result the tests check still holds.

![What QuantLib found in the calendars](docs/images/calendar-breaks.png)

**Curves from instruments on their real dates.** A SOFR curve is built from twenty
overnight index swaps: spot lags, the SIFMA calendar, modified-following rolls, ACT/360
and payment lags. It reprices every swap to 1e-10 bp and matches QuantLib to 2e-13 in
discount factors. Hagan-West **monotone convex** interpolation gives continuous, positive
forwards; the US Treasury has used it for its official curve since 2021. Risk is reported
in the quoted instruments, as a Jacobian and bucketed DV01 with the hedge that flattens
it.

![Four interpolators, one set of quotes](docs/images/interpolation-forwards.png)

**36 years of the real Treasury curve**, packaged so it runs offline:

- Level, slope and curvature explain 79.4, 12.7 and 4.1 per cent of its daily moves
  since 1990. That is Litterman and Scheinkman's result, reproduced.
- Nelson-Siegel-Svensson fits each day's par curve to a few basis points.
- The formula reproduces the Federal Reserve's published curve on all 9,171 days to
  within 0.034 bp.

![The Treasury curve since 1990](docs/images/treasury-history.png)

![Nelson-Siegel and Svensson on real curves](docs/images/nss-fits.png)

The full account is in [the rates engine, validated](docs/notes/the-rates-engine-validated.md).

**Day 2 revisited: the quality engine on 27 years of real FX.** Day 2's quality
rules were measured against a synthetic market with planted faults. Run over every
euro reference rate the ECB has fixed since 1999 - 41 currencies, 221,093 fixings -
they raised 1,282 findings. Most were facts about currencies the rules had never been
told:

- a pegged rate is *meant* to look stale;
- a currency that joined the euro is meant to stop;
- a price cannot move by less than one tick of its quote.

Taught resolution, lifecycles, regimes and a register of real market events, the
rules leave 53 findings for a person. Among them is a genuine fault in the ECB's own
history: the krona frozen at 305 for 19 days as Iceland's banks failed.

![The quality engine on real data](docs/images/fx-quality-waterfall.png)

![Forty-one currencies against the euro](docs/images/currency-lifecycles.png)

The ECB and the Federal Reserve fix the same rates 3h45 apart, and differ by a median
of 18 bp: not an error, but a different moment. The golden copy now compares sources
only when they price the same one. The full account is in
[market data on real FX](docs/notes/market-data-on-real-fx.md).

![Two central banks, one exchange rate](docs/images/ecb-vs-fed.png)

**Day 3 revisited: the book of record against the tax authorities.** Day 3's tax tests
were written from the rules by the same hand as the code. They are now joined by the
authorities' own worked examples, run exactly as published: 12 cases from IRS
Publication 550 and HMRC's CG51560, CG51590 and HS284.

- **All 42 published figures agree**: the IRS's to the cent and HMRC's to the pound.
  One HMRC figure does not follow from HMRC's own arithmetic (£4,236 where
  6,160 − 1,925 = £4,235). It is recorded as an erratum, and the engine is not bent to
  match it.
- **UK matching now follows the statute.** Two sales on one day are one disposal
  (s105). Rights taken up join the pool and are never matched under the 30-day rule
  (s127). A disposal the pool cannot cover is matched with later purchases.
- **Property tests found two engine bugs.** Hypothesis writes random histories and
  checks the trial balance, the sub-ledger tie, quantities and that a wash sale defers
  a loss without destroying it. Under HIFO, shares sold together could replace each
  other, and the disallowed loss vanished. An intraday round trip was refused. Both
  are fixed.
- **The demonstration Treasury accrues actual/actual (ICMA)**, as Treasuries do.

![The tax authorities' own examples, reproduced](docs/images/published-examples.png)

![The wash sale rule on the IRS's own examples](docs/images/wash-sale-timelines.png)

The full account is in
[the book against the tax authorities](docs/notes/the-book-against-the-tax-authorities.md).

![Property-testing the book](docs/images/book-invariants.png)

**Day 4 revisited: performance against the references, and on a century of real
returns.** A second reading found six faults, among them:

- a trailing year three days too long;
- Sharpe ratios of short periods mixing units;
- XIRR on years of 365.25 days.

The statistics are now reconciled against **empyrical**, the library behind pyfolio:

- 22 of 30 measures agree to 1e-10;
- the other 8 differ by four conventions, and each is recombined to land exactly on
  empyrical's figure.

**Kenneth French's data library** brings a century of real US returns:

- the market rebuilt from its twelve industries tracks the published market to 11 bp
  a month;
- a Brinson attribution of the equal-weighted market against the cap-weighted runs
  over 1,202 months;
- four linking methods, all exact, move up to a fifth of the answer between effects
  over a century.

![Every measure against empyrical](docs/images/empyrical-reconciliation.png)

![The US market rebuilt from twelve industries](docs/images/market-rebuilt.png)

The full account is in
[performance against the references](docs/notes/performance-against-the-references.md).

![Four linking methods, one total](docs/images/linking-methods.png)

**Day 5 revisited: risk against the references, and a century of daily VaR.** A second
reading found six faults, among them:

- Monte Carlo specific risk drawn once for the whole book;
- Basel's zones hard-coded for 250 days;
- exposures outside the estimation universe skipping two steps of their
  standardisation.

The checks are now independent:

- the Basel Committee's 1996 table is reproduced to the printed digit;
- the GARCH filter agrees with `arch` to the last bit;
- Ledoit-Wolf agrees with scikit-learn and with PyPortfolioOpt. PyPortfolioOpt feeds
  Ledoit and Wolf's own code a T - 1 sample; given theirs, it agrees exactly.

On **every trading day since 1929**, four one-day 99% VaR forecasters were scored as a
regulator would score them:

- the normal model is exceeded twice as often as it promises;
- historical simulation has ten red years;
- filtered historical simulation has none in 97;
- the worst surprise of the century was not 1987 but the day after Eisenhower's
  heart attack.

![Ninety-seven years of 99% VaR](docs/images/var-century-zones.png)

![The worst surprises in a century](docs/images/var-surprises.png)

The full account is in
[risk against the references](docs/notes/risk-against-the-references.md).

![Is the risk forecast the right size?](docs/images/bias-by-decade.png)

**Day 6 revisited: compliance that cannot be talked past.** Hypothesis now writes
portfolios and orders, and an independent oracle checks the pre-trade check's one duty:
an order it lets through makes no hard limit worse, for any issuer or sector. On 3,000
random orders Day 6 let **302** unsafe ones through, by two routes:

- utilisation is infinite before and after when a limit or a value is zero, so adding
  to an excluded stock, or spending the last cash, looked unchanged;
- a second issuer crossing a limit was hidden behind the first.

Breaches are now measured by their excess, group by group, and none slips through. The
breach register keeps one breach per issuer, and finds seven it had missed.

![Orders the pre-trade check let through](docs/images/pretrade-guarantee.png)

On **a century of the market**, held as an index fund under a 40% single-industry
limit, the first breach came in August 2025. Even the technology bubble of 2000 stayed
at 34.9%. The market has never been so concentrated.

![A 40% industry limit since 1926](docs/images/century-sector-limit.png)

The full account is in
[compliance that cannot be talked past](docs/notes/compliance-that-cannot-be-talked-past.md).

**Day 7 revisited: the tax code as the IRS writes it.** The optimiser's tax arithmetic
was held to Publication 550 and to Day 3's separately written ledger, and four faults
came out:

- **"More than one year" was counted as 365 days.** Across a 29 February that is a day
  short, so the IRS's own example (bought 5 February 2024, sold 5 February 2025) was
  called long-term. The fault was in Day 3 as well as Day 7, and touched 22% of
  purchase dates.
- **The $3,000 deduction used long-term losses as readily as short-term ones**, and
  was valued with the 3.8% net investment income tax, which a loss never saves.
- **A long-term loss larger than a short-term gain was carried as short-term.**
- **A lot bought in the last 30 days was its own wash-sale replacement.**

![The capital loss carryover, as Schedule D computes it](docs/images/carryover-schedule-d.png)

The four managers then ran through **a century of the real US market**, decade by
decade since 1931, under today's tax code. Harvesting paid the least tax in every
decade: 15 bp a year at the median, 47 bp in the 1930s. Its trades' tracking luck was
often as large as the saving, and the results now report the two apart.

![Harvesting saved tax in every decade](docs/images/century-tax-saved.png)

The full account is in
[the tax code as the IRS writes it](docs/notes/the-tax-code-as-the-irs-writes-it.md).

**Day 8 revisited: execution against the paper.** Almgren and Chriss's own worked
example is reproduced (κ = 0.607 a day, κT = 3.04; the paper: "≈ 0.6", "≈ 3"), and the
closed-form trajectory matches a conic solver's minimum. Around it, four faults came
out:

- **The arrival price was taken a minute late.**
- **POV traded at the wrong rate:** a tenth of everyone else's volume, which is 9.1% of
  the total, not 10%.
- **Hypothesis found a block that could not be allocated.**
- **The client report typed four figures into its text** and promised to carry
  unfilled shares to the next session, which nothing in the platform does.

![Almgren and Chriss's own example, reproduced](docs/images/almgren-chriss-paper.png)

The paper's liquidation then ran through **every week of the US market since 1927**.
The model promises that the cost exceeds its 95% bound one week in twenty. On real
prices it did so in 6.3% of weeks for sellers and 7.4% for buyers, and in 10.9% of the
1970s, when daily index returns moved together. Restating the variance for that
autocorrelation brings it to 5.4%.

![Almgren-Chriss's 95% bound on a century of real prices](docs/images/century-liquidation-bound.png)

The full account is in [execution against the paper](docs/notes/execution-against-the-paper.md).

**Day 9 revisited: the platform under concurrent requests.** Day 9's tests sent one
request at a time. Sent together, three writes that checked and then wrote in separate
steps broke:

- **two orders took one number;**
- **a retried order was entered twice;**
- **two compliance officers were both told they had decided the same order**, one
  "approved" and one "rejected".

Each race is now forced in a unit test and decided by the database in one step.
Deployed as four processes on one PostgreSQL, the Day 9 code failed 19% of simultaneous
orders and decided a third of contested orders twice; the revisited code, none.

![The promises Day 9 broke under load](docs/images/platform-under-load.png)

An attacker's questions found two more faults:

- **A failed sign-in for a name that does not exist came back in 7 ms**, against 206 ms
  for a real one, which told which usernames were real.
- **A deactivated account kept its rights until its token expired.**

![What a failed sign-in told an attacker](docs/images/sign-in-timing.png)

The full account is in [the platform under load](docs/notes/the-platform-under-load.md).

---

## What it does today

```bash
meridian rates curve --tenors 0.25,1,2,5,10,30 --par 4.25,4.18,3.95,3.90,4.15,4.55
# Bootstraps a zero curve, one instrument at a time, and prints par, zero,
# discount factors and forwards side by side.

meridian rates bond 2034-05-15 --coupon 4 --issue 2024-05-15 --price 96.79
# Yield to maturity 4.499894%, modified duration 6.408, convexity 48.62,
# DV01 0.0629 per 100 of face, accrued 1.40 on 129/184 days.

meridian rates treasury 2008-09-15
# The real Treasury par curve on the day Lehman failed, bootstrapped with
# monotone convex and fitted by Svensson (RMSE 2.4 bp) and Nelson-Siegel.

meridian rates validate
# 27 checks against QuantLib - six calendars over 106,451 weekdays, eight day
# counts, bonds, gilts, a SOFR curve - with every remaining break explained.

meridian calendar ladder 2026-12-23 --calendars XNYS,XLON,TARGET,XTKS
# Where T+1 to T+3 land in each market, and in the joint calendar every leg
# of a cross-border trade has to clear.

meridian security validate US0378331005 HWUPKR0MPOU8FGXBT394
# ISIN and LEI, each against its own check-digit algorithm.

meridian market price --persist
# The end-of-day pricing run: three sources collected, 16,735 observations
# recorded with the time they arrived, 211 quality findings, 5,606 golden
# prices published, 141 price challenges raised.

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

meridian compliance check
# The account's 18 investment restrictions, written in the Meridian mandate
# language: 14 pass, 4 warn - Microsoft is 10.3% held directly, 15.6% counting
# the index funds.

meridian compliance pretrade US-MSFT 100000
# Blocked: single issuer 10.29% -> 12.28% against a 12% hard limit. The
# largest purchase the hard limits allow is 85,976 dollars.

meridian compliance replay
# The book's 43 historical orders through the pre-trade check it never had:
# 7 blocked one at a time, 3 trading days blocked as baskets.

meridian rebalance propose
# Tracking error 5.80% -> 2.64% for -96.9k of tax: 540k of losses harvested,
# three names barred by the wash-sale rule, active share held at its 30% floor,
# 27 orders in whole lots, and the compliance engine's verdict on the basket.

meridian rebalance lots
# Every lot the proposal sells, and the same trades relieved FIFO, LIFO and
# highest cost first: choosing lots is worth 45k against last in, first out.

meridian rebalance backtest --paths 16
# Four managers through the same simulated markets: tax-aware +0.55% a year
# after tax against the tax-blind manager, on liquidation value.

meridian trade blotter
# The rebalance traded the next morning: 78 orders from three accounts in 26
# blocks, each worked by the algorithm its size calls for - VWAP, IS or POV.

meridian trade costs
# Implementation shortfall -7.9 bp: +9.8 bp the desk controls (spread, impact,
# fees) and -17.7 bp the market gave while it traded. Components add up exactly.

meridian trade calibrate
# The square-root impact coefficient from 400 orders: 0.355 measured, against a
# true 0.350; from what a desk actually observes, an interval that includes zero.

meridian report client --out client-report.pdf
# The quarterly client report: nine pages, from the valuation to the trades,
# every number drawn from the module that owns it.

meridian platform serve
# The API on :8000 - 21 endpoints, bearer tokens, role-based access, rate limits,
# idempotent writes, four-eyes order approval, and every request hash-chained.

meridian platform verify-audit
# Walks the audit log's hash chain: "608 records, chain intact" - or the first
# record that was edited, deleted or forged.
```

---

## The charts

Every module ships a visual, not only numbers. All two hundred and three are in the
[gallery](docs/GALLERY.md) and are rebuilt from source with `meridian charts gallery`.

**How much tracking error does a dollar of tax buy?** Every point on this frontier is a
full, compliant rebalance of the account: the mandate, the cash band, the wash-sale rule
and the active-share floor all hold. Harvested losses pay for the first half of the move;
after that, each 0.1 point of tracking error costs about $11k of tax. The proposal sits
on the frontier; the tax-blind trade sits at its far end, $100k of tax away.

![The efficient frontier of tracking error against tax](docs/images/tax-frontier.png)

**What tax-awareness is worth over years.** Four managers through the same simulated
markets, 16 paths of three years, with the US tax ledger and the value the account
would have if liquidated at the end. Choosing lots and deferring gains is worth about
half a percent a year after tax; harvesting saves more tax but spends it on turnover.

![Tax alpha across simulated paths](docs/images/tax-alpha.png)

**What the rebalance cost to trade, exactly.** Against the paper portfolio - every
share at the decision price - the day's shortfall splits into what the desk controls
(spread, impact, fees) and what the market did on its own. The simulator keeps the
price path the market would have taken without the orders, so impact is measured, not
estimated.

![Implementation shortfall of the rebalance](docs/images/implementation-shortfall.png)

**Calibrating the impact model, with the answer known.** Measured directly, 400
orders recover the square-root coefficient to within 1.5%; from the prices a desk
actually sees, the market's own moves drown it.

![Calibrating the impact model](docs/images/impact-calibration.png)

**The client report,** assembled from every module's objects - so no number on one
page can disagree with another.

![The client report](docs/images/client-report-pages.png)

**Seven layers between a request and the data.** A working day on the platform, driven
over HTTP against the real modules by seven people - one of them an intruder. Each layer
stops what it should, and every request, stopped or not, is written to a hash-chained
audit log.

![Seven layers between a request and the data](docs/images/request-pipeline.png)

**The platform watching itself.** Request rate by user, responses by status, latency and
the busiest routes, as its Prometheus metrics and its audit log recorded them.

![The operations dashboard](docs/images/operations-dashboard.png)

**A tamper-evident audit trail.** Edit one record and it, and every link after it, stop
verifying - and readiness fails, so a doctored deployment stops taking traffic.

![A tamper-evident audit trail](docs/images/audit-chain.png)

**Nine days, ten releases** - measured from the git tags.

![Nine days, ten releases](docs/images/codebase-growth.png)

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

**A mandate is a contract, and it has to be machine-checkable.** The account's investment
restrictions are eighteen rules in the Meridian mandate language, parsed by a Lark
grammar. Every day each rule reports how much of its limit is in use.

![Limit utilisation](docs/images/limit-utilisation.png)

**What the index funds hide.** Microsoft is 10.3% of the account held directly and 15.6%
counting the Microsoft inside the S&P 500 and world funds. Look-through is a clause of each
rule, so the mandate says which of the two numbers each limit applies to.

![One issuer, two limits](docs/images/issuer-limits.png)

**Active or passive?** Replayed through its mandate, the book breached eight of its rules
37 times since inception: 9 times because of a trade, 28 because prices moved. Each
breach opens, ages against its deadline, and closes by trading or by the market.

![The breach timeline](docs/images/breach-timeline.png)

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
├── compliance    the mandate language (a Lark grammar), the rule engine with
│                 look-through, pre-trade checks and baskets, the breach register
├── optimisation  tax-aware rebalancing: a conic programme over lots (cvxpy, Clarabel),
│                 the mandate compiled, wash-sale and active-share rounds, orders
│                 rounded by MILP (HiGHS), the frontier, the tax-alpha simulation
├── execution     orders in FIX states, a minute-by-minute market with its
│                 counterfactual, TWAP / VWAP / POV / IS (Almgren-Chriss) / Close,
│                 block allocation, implementation shortfall and impact calibration
├── reporting     the client report: every module's pages in one PDF
├── api           the web platform: FastAPI, JWT and PBKDF2, roles and entitlements,
│                 rate limits, idempotency keys, four-eyes orders, Prometheus metrics
├── devtools      the project measured: growth by release, the package graph, a
│                 working day driven over HTTP
├── persistence   SQLAlchemy 2.0 schema, explicit mappers, repositories, unit of work
├── marketdata    series, point-in-time storage, sources, adjustment, golden copy
├── quality       the data quality rules, the engine and the scoring
├── refdata       the security master: identifier cross-reference, golden records
├── services      application processes: the end-of-day pricing, accounting,
│                 performance, risk, compliance, rebalance and trading runs, the
│                 demonstration market, book and benchmark
├── viz           the house chart style and one hundred and thirty-two figures
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
| Mandates | Investment restrictions written in a small language parsed by Lark, printed back exactly (a property test), stored as text with a hash ([ADR 0027](docs/adr/0027-mandates-are-written-in-a-language-parsed-by-lark.md)); look-through stated rule by rule ([ADR 0028](docs/adr/0028-look-through-is-part-of-the-rule.md)). |
| Compliance | Active and passive breaches with deadlines ([ADR 0029](docs/adr/0029-breaches-are-active-or-passive-and-age-against-a-deadline.md)); pre-trade checks on the resulting portfolio, baskets as a whole, the largest permissible order ([ADR 0030](docs/adr/0030-pre-trade-checks-judge-the-portfolio-after-the-order-and-baskets-as-a-whole.md)). |
| Optimisation | A conic programme over tax lots, solved by Clarabel ([ADR 0031](docs/adr/0031-tax-aware-rebalancing-is-a-conic-programme.md)); lots as decision variables ([ADR 0032](docs/adr/0032-lots-are-decision-variables.md)); wash sales and an active-share floor met in rounds ([ADR 0033](docs/adr/0033-non-convex-rules-are-met-in-rounds.md)); orders rounded by a MILP ([ADR 0034](docs/adr/0034-orders-are-rounded-by-a-mixed-integer-programme.md)). |
| Tax alpha | Measured on liquidation value, over simulated paths, against a tax-blind manager, with harvested losses valued at the rate difference they actually earn ([ADR 0035](docs/adr/0035-tax-alpha-is-measured-on-liquidation-value-over-simulated-paths.md)). |
| Orders | FIX `OrdStatus` as a checked state machine with an audit trail; parent and child orders ([ADR 0036](docs/adr/0036-orders-are-a-checked-state-machine-in-fix-states.md)). |
| Execution | A minute-by-minute market with the price path without our trades kept, so impact is measured ([ADR 0037](docs/adr/0037-execution-is-simulated-with-the-counterfactual-price-kept.md)); algorithms as schedules, IS by Almgren-Chriss ([ADR 0038](docs/adr/0038-algorithms-are-schedules-and-is-follows-almgren-chriss.md)); blocks allocated at one price ([ADR 0039](docs/adr/0039-block-orders-are-allocated-at-one-price-pro-rata.md)). |
| Transaction costs and reporting | Implementation shortfall decomposed exactly; the client report built from the modules' own objects ([ADR 0040](docs/adr/0040-the-client-report-is-assembled-from-the-modules-own-objects.md)). |
| Web platform | The API serves the modules and computes nothing ([ADR 0041](docs/adr/0041-the-api-serves-the-modules-it-does-not-compute.md)); permissions, entitlements and separation of duties ([ADR 0042](docs/adr/0042-permissions-entitlements-and-separation-of-duties.md)); a hash-chained audit log in the readiness probe ([ADR 0043](docs/adr/0043-the-audit-log-is-a-hash-chain.md)); idempotent writes and four-eyes orders ([ADR 0044](docs/adr/0044-writes-are-idempotent-and-orders-need-four-eyes.md)); one-command deployment tested in CI ([ADR 0045](docs/adr/0045-one-command-deployment-with-its-own-observability.md)). |
| Layering | Every import points down the layers - checked by a test that parses the source. |
| Tests | 1127 tests, including property-based tests (Hypothesis) for the invariants that must hold for every input: allocation conserves the total, rate conversions round-trip, monotone interpolation stays monotone. |
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
meridian compliance run --persist # the mandate checked on every day, the register, the orders
meridian compliance pretrade US-MSFT 100000   # test an order before it is sent
meridian rebalance propose        # today's tax-aware rebalance, as orders
meridian rebalance run --persist  # the proposal, its orders, lots and frontier, after the controls
meridian trade run --persist      # the day's orders, fills, allocations and costs, after the controls
meridian report client --out client-report.pdf   # the nine-page client report
meridian platform serve           # the web platform on :8000 (OpenAPI at /docs)
```

Or the whole stack - PostgreSQL, migrations, the API, Prometheus and Grafana - with
`docker compose up --build`.

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
| [The rates engine, validated](docs/notes/the-rates-engine-validated.md) | QuantLib as a reconciliation, calendars that know their history, curves from dated instruments, monotone convex, 36 years of the Treasury curve, Nelson-Siegel-Svensson against the Fed, gilts ex-dividend |
| [Market data on real FX](docs/notes/market-data-on-real-fx.md) | The pence trap, the quality engine on 27 years of ECB fixings, currency regimes and lifecycles, the events register, the ECB against the Fed, fixing times |
| [The book against the tax authorities](docs/notes/the-book-against-the-tax-authorities.md) | The IRS's and HMRC's worked examples reproduced, an HMRC erratum, UK matching per the statute, the book property-tested, the Treasury day count |
| [Performance against the references](docs/notes/performance-against-the-references.md) | Six faults, every measure against empyrical, Microsoft's XIRR, four linking methods, a century of Kenneth French's data |
| [Risk against the references](docs/notes/risk-against-the-references.md) | Six faults, the Basel table, GARCH against arch, Ledoit-Wolf against PyPortfolioOpt, a century of daily VaR, bias by decade |
| [Compliance that cannot be talked past](docs/notes/compliance-that-cannot-be-talked-past.md) | The pre-trade guarantee property-tested, breaches per group, the UCITS screen per the Directive, a century of a sector limit |
| [The platform under load](docs/notes/the-platform-under-load.md) | Three races forced and fixed, four processes on one PostgreSQL, sign-in timing, rights read from the account on every request |
| [Execution against the paper](docs/notes/execution-against-the-paper.md) | Almgren and Chriss's example reproduced, the arrival price, POV's rate, allocation property-tested, the client report's figures, liquidation on a century of real prices |
| [The tax code as the IRS writes it](docs/notes/the-tax-code-as-the-irs-writes-it.md) | The holding period by the calendar, the carryover as Schedule D computes it, wash sales, two solvers, tax-loss harvesting on a century of real returns |
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
| [The mandate language](docs/notes/mandate-language.md) | Rules, measures and filters, look-through, parsing with Lark, and the UCITS rules in four lines |
| [Pre-trade and post-trade compliance](docs/notes/pre-and-post-trade-compliance.md) | Checking orders and baskets, the history replayed, active and passive breaches, the register |
| [Tax-aware rebalancing](docs/notes/tax-aware-rebalancing.md) | The rebalance as a conic programme over lots, rules that are not convex, orders, the frontier, and tax alpha measured honestly |
| [Execution and transaction costs](docs/notes/execution-and-transaction-costs.md) | Orders in FIX states, a market with its counterfactual, five algorithms and Almgren-Chriss, allocation, the shortfall decomposed, calibration, the client report |
| [The web platform](docs/notes/the-web-platform.md) | One API over the modules, seven layers of control, roles and entitlements, four eyes, the hash-chained audit log, idempotency, a measured working day, deployment |
| [Chart gallery](docs/GALLERY.md) | All one hundred and fifty-eight figures, with what each one argues |
| [Architecture decisions](docs/adr) | Fifty-five records: what was decided, what the alternatives were, and what it costs |
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
| 6 | Compliance: a mandate language parsed by Lark, look-through, pre- and post-trade checks, baskets, the breach register | ✅ Done |
| 7 | Tax-aware optimisation: a conic rebalance over tax lots, wash sales and an active-share floor in rounds, MILP rounding, the tracking-error / tax frontier, tax alpha over simulated years | ✅ Done |
| 8 | Execution and reporting: orders in FIX states, a simulated intraday market, five algorithms and Almgren-Chriss, block allocation, implementation shortfall, a nine-page client report | ✅ Done |
| 9 | Platform: a FastAPI service with JWT, roles and entitlements, a hash-chained audit log, idempotent writes, four-eyes orders, Prometheus and Grafana, Docker Compose; release v1.0.0 | ✅ Done |
| 1+ | Day 1 revisited: reconciled against QuantLib, calendars with history, curves from dated instruments, monotone convex, 36 years of the Treasury curve, NSS against the Fed, gilts; release v1.1.0 | ✅ Done |
| 2+ | Day 2 revisited: the pence trap and three more faults; the quality engine on 27 years of real FX from the ECB and the Fed, currency regimes and lifecycles, an events register, fixing times in the golden copy; release v1.2.0 | ✅ Done |
| 3+ | Day 3 revisited: the IRS's and HMRC's worked examples reproduced (one HMRC erratum), UK matching per s105 and s127, the book property-tested (two bugs fixed), the Treasury on actual/actual; release v1.3.0 | ✅ Done |
| 4+ | Day 4 revisited: six faults fixed, every measure reconciled against empyrical, Microsoft's XIRR examples, four linking methods, a century of Kenneth French's industry data; release v1.4.0 | ✅ Done |
| 5+ | Day 5 revisited: six faults fixed, the Basel table reproduced, GARCH against arch, Ledoit-Wolf against PyPortfolioOpt, a century of daily VaR backtests in Basel's zones; release v1.5.0 | ✅ Done |
| 6+ | Day 6 revisited: the pre-trade check property-tested (302 unsafe orders of 3,000, now none), breaches per group, the UCITS screen as the Directive writes it, a century of a sector limit; release v1.6.0 | ✅ Done |
| 7+ | Day 7 revisited: the holding period by the calendar (Day 3 too), the carryover as Schedule D computes it, wash sales, the rebalance against a second solver, tax-loss harvesting on a century of real returns; release v1.7.0 | ✅ Done |
| 8+ | Day 8 revisited: Almgren and Chriss's example reproduced, the arrival price and POV's rate corrected, allocation property-tested, the client report's figures from their sources, a century of real liquidations against the model's 95% bound; release v1.8.0 | ✅ Done |
| 9+ | Day 9 revisited: three check-then-write races forced and fixed (order numbers, idempotency, four eyes), the platform tested as four processes on one PostgreSQL, sign-in timing that no longer reveals usernames, rights read from the account on every request; release v1.9.0 | ✅ Done |

---

## Licence

MIT. See [LICENSE](LICENSE).
