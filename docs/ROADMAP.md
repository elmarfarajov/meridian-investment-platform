# Roadmap

Meridian is built in daily increments. Each day is a GitHub issue, a feature branch, a
series of small commits, a pull request that explains the reasoning, a green CI run and a
version tag. The history is meant to be read as much as the code.

Every module ships three things: the logic, tests that would fail if the logic were wrong
in a way that matters, and at least one chart. A number without a picture is hard to
argue with; a picture without a test is hard to trust.

---

## Day 1 - Foundation ✅

**Issue #1.** The vocabulary everything else is written in.

- `Money` on `Decimal` with banker's rounding, currency tagging and an `allocate` that
  conserves the total to the cent.
- Currencies with correct minor units (including the three-decimal dinar), FX rates with
  inversion and pivot cross rates.
- ISIN, CUSIP, SEDOL and FIGI with their real check-digit algorithms.
- Trading calendars generated from statutory rules: NYSE, LSE, TARGET, business-day
  conventions, T+n settlement.
- Day-count conventions: ACT/360, ACT/365F, 30/360, ACT/ACT ISDA.
- Domain model: instruments, clients, households, accounts, portfolios, transactions with
  fixed sign conventions, positions as tax lots with FIFO/LIFO/HIFO/average/specific
  identification.
- Persistence: typed SQLAlchemy 2.0 schema, explicit domain-to-row mappers, repositories,
  a unit of work, and Alembic migrations with a drift check in CI.
- A Typer + Rich CLI, a structured-logging setup, the house chart style, and the trading
  calendar chart.

### Day 1, continued ✅

The financial mathematics everything above the ledger depends on.

- Eight trading calendars with named holidays, including Tokyo's equinoxes and chained
  substitute days, and `JointCalendar` for cross-border settlement.
- Nine day-count conventions, including the three that cannot be evaluated from two
  dates alone.
- Payment schedules: backward rolls, the sticky end-of-month rule, four stub
  conventions, payment lags, adjusted or unadjusted accrual.
- Compounding conventions with exact conversion, and three interpolation methods
  including Fritsch-Carlson monotone cubic.
- Yield curves bootstrapped from par yields, with zero, par and forward views, parallel
  shifts and key-rate bumps.
- Bond analytics: clean and dirty price, accrued interest, yield to maturity, duration,
  convexity, DV01, z-spread, key rate durations.
- Safeguarded Newton root finding that raises rather than returning a wrong number.
- LEI validation and identifier scheme detection.

**Charts:** seventeen in total, including the yield curve three ways, the interpolation
comparison, the price-yield curve against its own approximations, key rate durations,
the settlement ladder, the calendar divergence matrix, and an entity-relationship
diagram generated from the live database metadata.

**Notes:** [fixed income mathematics](notes/fixed-income-mathematics.md),
[calendar conventions](notes/calendar-conventions.md).

## Day 2 - Market data ✅

**Issue #2.** Nothing downstream is better than the prices it is fed.

- Price and FX series that are *bitemporal*: every value carries the day it describes
  and the moment the platform learned it, so any past state of knowledge can be
  rebuilt and the look-ahead in a restated history can be measured.
- A seeded synthetic market with the stylised facts that make quality checking hard -
  Student-t tails, GARCH volatility clustering, market and sector factors, one
  exchange calendar per instrument - and a fault injector that damages it in the nine
  ways real feeds fail.
- Thirteen quality rules across the five DAMA dimensions. The statistical ones score
  event-adjusted returns net of a leave-one-out market proxy, over trailing
  median/MAD windows that never look ahead. Measured against planted faults: recall
  100%, precision 97%.
- Corporate actions - dividends, splits, stock dividends, spin-offs, rights, cash and
  stock mergers, symbol changes - applied to the history as a derived view, and to
  tax lots with the basis conserved and the holding period tacked.
- A golden copy built by ranked consensus across three sources, with price challenges
  recorded, stale sources set aside, and every published price naming its source.
- A security master with identifiers resolved by date and golden records with
  lineage, and the end-of-day pricing run that ties it all together.

**Charts:** thirteen, including the quality dashboard, the robust-against-classical
comparison, the detection scorecard, the coverage calendar, point-in-time revisions,
vendor consensus and the FX triangle.

**Notes:** [market data quality](notes/market-data-quality.md),
[corporate actions](notes/corporate-actions.md),
[point-in-time data](notes/point-in-time-data.md),
[the security master](notes/security-master.md).

## Day 3 - Portfolio accounting ✅

**Issue #3.** The book of record: if this is wrong, everything downstream is wrong.

- A double-entry general ledger at cost, balanced in base and in each local currency,
  with a chart of accounts a fund accountant would recognise. Market value is a
  valuation of the ledger, never an entry in it.
- Trade capture with a versioned blotter: amendments and cancellations are new
  versions, the book is a replay of the blotter as known at a moment, and a
  restatement is the difference between two replays. Settlement cycles are dated -
  US equities moved to T+1 on 28 May 2024 - and settlement fails are tracked.
- Posting rules for purchases and sales against payables and receivables, currency
  results on settlement and conversion, dividends from ex-date to pay date with
  withholding split into reclaimable and lost, bond accrued interest bought and
  recovered, transfers in kind, and every corporate action in the Day 2 feed.
- Tax lots carrying their holding period start, opening FX rate and wash sale
  adjustment apart from book cost; the US wash sale rule with its 30-day look-ahead;
  Schedule D netting, loss carryforward and Form 8949; lot choice priced under FIFO,
  LIFO, highest cost and a provably minimal-tax order; UK same-day, 30-day and
  section 104 matching in sterling.
- Daily valuation in local and base currency, unrealised gain split per lot into
  price and currency, and a value bridge - flows, price, currency, income, costs -
  whose residual is zero on every day.
- Reconciliation against a custodian on settled terms, with breaks classified by
  cause and measured against breaks planted where the answer is known.

**Charts:** sixteen, including the valuation waterfall, the NAV history by currency
family, the wash sale, one book under two tax codes, the restatement, the trial
balance and the reconciliation dashboard.

**Notes:** [portfolio accounting](notes/portfolio-accounting.md),
[tax lots and wash sales](notes/tax-lots-and-wash-sales.md),
[UK share matching](notes/uk-share-matching.md),
[valuation and the value bridge](notes/valuation-and-the-value-bridge.md),
[reconciliation](notes/reconciliation.md).

## Day 4 - Performance and attribution ✅

**Issue #4.** What the return was, and where it came from.

- Time-weighted return chained daily from the value bridge's own result, flows at the
  start of the day, so every return reconciles to the ledger; money-weighted return by
  XIRR; Modified Dietz as the comparison it historically replaced.
- Holding contributions, with price, currency and income per holding and costs apart,
  linked so they add up to the portfolio's return exactly.
- A benchmark built the way an index provider builds one: Meridian World Equity, a
  synthetic cap-weighted index of 36 stocks generated in the same market as the book,
  inside an 80/15/5 policy blend rebalanced monthly.
- Brinson-Fachler attribution on local returns, by sector and by region, with currency
  and costs as their own effects and index funds looked through to the benchmark.
- Cariño linking, so the effects sum to the compounded active return with nothing
  left over, stored per report period.
- Risk against the benchmark: volatility, Sharpe, Sortino, tracking error, information
  ratio, beta, capture, drawdown episodes, VaR and expected shortfall, rolling windows.

**Charts:** fifteen, including the attribution bridge, attribution by sector and by
region, the monthly attribution calendar, why effects have to be linked, three return
methods, rolling risk and a one-page factsheet.

**Notes:** [performance measurement](notes/performance-measurement.md),
[performance attribution](notes/performance-attribution.md),
[benchmark construction](notes/benchmark-construction.md).

## Day 5 - Risk ✅

**Issue #5.** Risk is a forecast, and a forecast has to be validated.

- A fundamental multi-factor model: world, eleven GICS industries, beta, size, value,
  momentum and quality, and four currencies; exposures from standardised descriptors;
  factor returns from a daily weighted, industry-constrained cross-sectional regression.
- An estimation universe of 500 synthetic stocks over ten years whose true risk is
  recorded - crisis regimes, GARCH Student-t dynamics - that replays the Day 2 market
  over the demonstration window, so every forecast can be scored against the truth.
- Covariance: why a sample covariance on 500 stocks and 252 days is singular
  (Marchenko-Pastur) and what an optimiser does with it; Ledoit-Wolf shrinkage matched
  to scikit-learn; EWMA with separate half-lives; GARCH(1,1) through `arch`.
- Specific risk by EWMA, with Bayesian shrinkage tested and rejected on two
  independent tests; index funds looked through with their basis as its own risk.
- Portfolio volatility, tracking error, marginal and Euler contributions by factor,
  group and holding; VaR and expected shortfall four ways; historical and hypothetical
  stress tests.
- Validation: bias statistics with their band and a truth yardstick on the universe
  and on the account's own daily forecasts; Kupiec, Christoffersen and the Basel
  traffic light. The backtest found and fixed three mis-specifications.

**Charts:** sixteen, including the risk decomposition, the bias statistics with their
band, the eigenvalue spectrum against Marchenko-Pastur, minimum-variance portfolios by
estimator, the VaR backtest and a one-page risk report.

**Notes:** [the factor risk model](notes/factor-risk-model.md),
[covariance estimation](notes/covariance-estimation.md),
[validating a risk model](notes/risk-validation.md).

## Day 6 - Compliance ✅

**Issue #6.** A mandate is a contract, and it has to be machine-checkable.

- A mandate language - weights with filters, the heaviest issuer or sector, UCITS-style
  concentration sums, counts, exclusions, risk metrics; hard and soft limits with
  warning levels - parsed by a Lark LALR grammar into typed rules with exact decimal
  limits, errors reported by line and column, and printed back exactly (a Hypothesis
  property test).
- The account's eighteen investment restrictions, and the UCITS diversification rules
  as a four-line what-if.
- Look-through to index-fund constituents as a clause of each rule: Microsoft is 10.3%
  directly and 15.6% counting the funds; an excluded tobacco company is found inside
  the world fund.
- Pre-trade checks on the portfolio an order would leave: blocked, override, warning or
  allowed; trades that reduce a breach always allowed; the largest permissible order by
  bisection; baskets judged as a whole; risk metrics re-forecast by the Day 5 model.
- Post-trade checks every day, and a breach register: active or passive by what traded
  since the previous check, deadlines, overdue, resolved by trading or by the market.
- The book's own history replayed through the pre-trade check it never had.

**Charts:** twelve, including the limit-utilisation panel, the breach timeline, one
issuer against two limits, what the index funds hide, pre-trade decisions, the history
replayed, the parse tree of a rule and a one-page compliance report.

**Notes:** [the mandate language](notes/mandate-language.md),
[pre-trade and post-trade compliance](notes/pre-and-post-trade-compliance.md).

## Day 7 - Tax-aware optimisation ✅

**Issue #7.** The after-tax return is the only one the client spends.

- A rebalance that sells by the lot. It is a conic programme (cvxpy, Clarabel) that
  weighs:
  - tracking error from the Day 5 factor model;
  - tax at each lot's own rate, a loss as a saving;
  - commission, spread and square-root impact.
  The Day 6 mandate is compiled into its constraints.
- Lot selection: specific identification against FIFO, LIFO and highest cost first, on
  the same trades.
- Rules that are not convex, met in rounds: wash-sale repair, and an active-share floor
  held by the convex-concave procedure.
- Orders rounded to board lots and minimum tickets by a mixed-integer programme (HiGHS),
  checked by the compliance engine as one basket.
- The frontier of tracking error against tax, as the lower envelope of two sweeps.
- Tax alpha over simulated years: four managers through the same markets, the US tax
  ledger with carryforward and wash-sale deferral, and the value on liquidation.

**Charts:** fourteen, including:
- the efficient frontier with the proposal marked;
- the lots relieved four ways;
- the harvesting map;
- the rounds;
- the orders;
- the mandate after the trades;
- tax alpha across paths;
- after-tax wealth;
- the harvest calendar;
- the one-page proposal.

**Notes:** [tax-aware rebalancing](notes/tax-aware-rebalancing.md).

## Day 8 - Execution and reporting ✅

**Issue #8.** From a target portfolio to a filled order to a statement.

- Order management: parent and child orders in FIX states, a checked audit trail, block
  orders across the accounts that follow one model, allocation at one average price.
- Execution: a minute-by-minute market simulated from the Day 2 profiles, with the price
  path without our trades kept. The algorithms are TWAP, VWAP, POV, IS (Almgren-Chriss)
  and Close, and an algorithm wheel routes the orders.
- Transaction cost analysis: implementation shortfall decomposed exactly (delay, spread,
  impact, timing, opportunity, fees); VWAP slippage; pre-trade against post-trade; the
  impact model calibrated against known parameters.
- Client reporting: a nine-page PDF assembled from every module's objects.

**Charts:** fourteen, including:
- the shortfall waterfall;
- five algorithms on one order;
- the Almgren-Chriss frontier;
- one block's day with and without its impact;
- the algorithms compared;
- the impact calibration;
- block allocation;
- an order's life in FIX states;
- the client report's pages.

**Notes:** [execution and transaction costs](notes/execution-and-transaction-costs.md).

## Day 9 - Platform ✅

**Issue #9.** Making it something a team could run.

- A FastAPI service over the same domain objects: 21 endpoints, an OpenAPI 3.1 contract
  in which every endpoint records its permission.
- Access control:
  - PBKDF2 passwords and JWT access tokens;
  - roles as bundles of permissions;
  - client entitlements that answer as if absent;
  - separation of duties;
  - a token-bucket rate limit.
- A hash-chained audit log of every request, verified by the readiness probe;
  idempotent writes; orders checked pre-trade and approved by a second person above a
  threshold.
- Prometheus metrics, a provisioned Grafana dashboard, a multi-stage non-root image,
  and Docker Compose for the whole stack, built and smoke-tested in CI.
- The project measured: its growth over the release tags, its package graph (every
  import points down, checked by a test), and a working day driven over HTTP.
- Release v1.0.0.

**Charts:** fifteen, including:
- the architecture;
- the seven layers a request crosses;
- the role matrix;
- the API surface;
- latency by endpoint;
- the operations dashboard;
- the audit chain;
- four eyes;
- the deployment;
- the package graph;
- the growth over nine days.

**Notes:** [the web platform](notes/the-web-platform.md).

---

## Revisits

After the nine days, each day is revisited in order and held to a stricter standard:
independent references, real data where it exists, and every disagreement either fixed
or explained in writing. Each revisit is an issue, a branch, a pull request and a
release, like the days themselves.

### Day 1, revisited - the rates engine, validated ✅

**Issue #20, release v1.1.0.**

- Reconciled against **QuantLib**, 27 checks:
  - six calendars over 106,451 weekdays;
  - eight day counts;
  - bond and gilt analytics;
  - a SOFR curve.
  72 calendar breaks remain, down from 309, each explained with its evidence.
- **Calendars with history**:
  - rules with the years they apply to;
  - special closures and openings as named data;
  - the equinoxes computed by Meeus's algorithm;
  - a *scheduled* view, so the simulation is not reshuffled when history is added.
- **30/360 US** with SIFMA's February rules, and the street convention for 30/360 bond
  prices.
- **Curves from dated instruments**: deposits and SOFR OIS, a Jacobian, and bucketed
  DV01 with its hedge.
- **Monotone convex** interpolation, and an iterative bootstrap for non-local methods.
- **36 years of the real Treasury curve** and the Federal Reserve's GSW curve,
  packaged.
- **Analysis on real data**: Nelson-Siegel-Svensson against the Fed, and PCA into
  level, slope and curvature.
- **UK gilts**, ex-dividend.

**Charts:** fifteen, including:

- the reconciliation;
- the calendar breaks before and after;
- the equinox arbiter;
- the SOFR curve;
- four interpolators;
- the Jacobian;
- bucketed DV01;
- the Treasury curve since 1990 as a heatmap and a surface;
- the principal components;
- the fits beside the Fed's.

**Notes:** [the rates engine, validated](notes/the-rates-engine-validated.md).

### Day 2, revisited - market data on real FX ✅

**Issue #22, release v1.2.0.**

- **Four faults found by reading the code again:**
  - the pence trap;
  - events on ex-dates with no print;
  - gaps measured against one day of market;
  - the rounded MAD constant.
- **27 years of real FX:** the ECB's 41 euro reference rates and the Federal
  Reserve's noon rates, packaged.
- **The quality engine on real data.** 1,282 findings, cut to 53 by teaching the rules:
  - the resolution of a quote;
  - each currency's lifecycle;
  - each currency's regime;
  - a register of 31 market events.
  The 53 open ones include a genuine fault in the ECB's own history.
- **Two central banks, one rate:** the ECB and the Fed fix 18 bp apart. The golden
  copy now compares sources only at the same moment.

**Charts:** eleven, including:

- the waterfall from 1,282 findings to 53;
- the lifecycles of 41 currencies;
- pegs and bands;
- the staleness model against the data;
- six real events;
- the ECB against the Fed;
- the world's fixes on one clock.

**Notes:** [market data on real FX](notes/market-data-on-real-fx.md).

### Day 3, revisited - the book against the tax authorities ✅

**Issue #24, release v1.3.0.**

- **The authorities' own worked examples, reproduced:** 12 cases and 42 figures from
  IRS Publication 550 and HMRC CG51560, CG51590 and HS284. The IRS figures agree to
  the cent and HMRC's to the pound. One HMRC figure is an arithmetic slip, recorded as
  an erratum.
- **UK matching brought in line with the statute:**
  - one day is one transaction (s105);
  - rights taken up join the pool (s127);
  - a shortfall is matched with later purchases.
- **The book property-tested:** Hypothesis writes random histories and checks the
  trial balance, the sub-ledger tie, the quantities and the conservation of
  disallowed losses. Two bugs were found and fixed:
  - shares sold together replaced each other;
  - an intraday round trip was refused.
- **The demonstration Treasury accrues actual/actual (ICMA)**, as Treasuries do.

**Charts:** six:

- every published figure against the engine;
- the wash sale timelines;
- the UK identification rules;
- the section 104 pool;
- the property-tested book;
- the Treasury day count.

**Notes:** [the book against the tax authorities](notes/the-book-against-the-tax-authorities.md).

### Day 4, revisited - performance against the references ✅

**Issue #26, release v1.4.0.**

- **Six faults found in a second reading:**
  - a trailing year three days too long;
  - short-period ratios mixing units;
  - relative measures annualised over the wrong span;
  - XIRR on 365.25-day years;
  - capture ratios of totals;
  - Modified Dietz flows outside the period.
- **Reconciled against empyrical and scipy:**
  - 22 of 30 measures agree to 1e-10;
  - 8 differ by four conventions, each recombined exactly;
  - Microsoft's XIRR and XNPV examples reproduced.
- **Four linking methods:** Cariño, Menchero, GRAP and Frongello, all exact.
- **A century of real returns** from Kenneth French's library:
  - the market rebuilt from twelve industries to 11 bp a month;
  - equal weight attributed against cap weight by decade;
  - drawdowns and Sharpe ratios since 1926.

**Charts:** eight:

- every measure against empyrical;
- the market rebuilt;
- a century of industry weights;
- decade attribution;
- the four linking methods;
- a century of drawdowns;
- the rolling Sharpe ratio;
- the review fixes.

**Notes:** [performance against the references](notes/performance-against-the-references.md).

### Days 5 to 9, revisited - next

---

## Working method

- One issue per day, closed by one pull request.
- Small conventional commits (`feat(core): ...`, `fix(domain): ...`), each of which leaves
  the suite green.
- CI runs lint, format, types, the suite on Python 3.10, 3.11 and 3.12, and the
  integration suite against PostgreSQL 16.
- Architecture decisions are written down in `docs/adr` at the moment they are taken, not
  reconstructed afterwards.
