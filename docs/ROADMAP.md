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

## Day 6 - Compliance

**Issue #6.** A mandate is a contract, and it has to be machine-checkable.

- A small rule DSL: `max weight of issuer <= 5% of NAV`, `no holdings rated below BBB-`,
  `cash between 1% and 10%`, UCITS 5/10/40, concentration and liquidity limits.
- Pre-trade checks on a proposed order, post-trade checks on the book, and passive-breach
  handling when a limit is broken by market movement rather than by a trade.
- A breach register with severity, age and remediation state.

**Chart:** a limit-utilisation panel showing headroom against every rule.

## Day 7 - Tax-aware optimisation

**Issue #7.** The after-tax return is the only one the client spends.

- Rebalancing towards a target with transaction costs, round lots and minimum trade sizes.
- Tax-aware lot selection, loss harvesting and the wash-sale constraint.
- The trade-off surface: tracking error against realised tax cost.

**Chart:** the efficient frontier of tracking error versus tax cost, with the chosen
rebalance marked.

## Day 8 - Execution and reporting

**Issue #8.** From a target portfolio to a filled order to a statement.

- Order management: parent orders, allocation across accounts, partial fills, average
  price.
- Transaction cost analysis: implementation shortfall against arrival price, VWAP
  benchmarking, market impact.
- Client reporting: a multi-page PDF pack - holdings, performance, attribution, risk,
  costs and tax.

**Chart:** the implementation shortfall decomposition, and the client report itself.

## Day 9 - Platform

**Issue #9.** Making it something a team could run.

- A FastAPI service over the same domain layer, with role-based access control.
- Audit trail, idempotent endpoints, and OpenAPI documentation.
- Docker Compose for the whole stack, and release v1.0.0.

---

## Working method

- One issue per day, closed by one pull request.
- Small conventional commits (`feat(core): ...`, `fix(domain): ...`), each of which leaves
  the suite green.
- CI runs lint, format, types, the suite on Python 3.10, 3.11 and 3.12, and the
  integration suite against PostgreSQL 16.
- Architecture decisions are written down in `docs/adr` at the moment they are taken, not
  reconstructed afterwards.
