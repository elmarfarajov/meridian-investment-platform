# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-09-26

Day 5: risk. A fundamental factor model estimated on a universe whose true risk is
known, applied to the demonstration account, and validated - on ten years of the
universe and on every morning's forecast for the account.

### Added

- **The estimation universe.** Five hundred synthetic stocks over ten years with GARCH
  Student-t factors and residuals, crisis regimes whose factor totals are fixed (the 2020
  crash, the 2022 bear market, a momentum crash), and every true factor return,
  exposure and conditional variance recorded. Over the demonstration window it replays
  the Day 2 market through `SyntheticMarket.factor_draws`.
- **The factor model.** Twenty-one factors - world, eleven industries, beta, size,
  value, momentum, quality, four currencies. Descriptors (Vasicek-shrunk historical
  beta, log size, log book-to-price, 12-1 momentum, return on equity) standardised to
  cap-weighted mean zero and unit spread; a daily square-root-cap WLS regression with
  cap-weighted industries constrained to sum to zero.
- **Covariance.** Sample, EWMA with separate volatility and correlation half-lives
  (42 and 200 days), Ledoit-Wolf towards the identity (matched to scikit-learn) and
  towards constant correlation, Marchenko-Pastur bounds and density, the riskless
  portfolio of a singular sample, Woodbury minimum variance. GARCH(1,1) via `arch`.
- **The model and its decomposition.** `V = X F X' + D`; Euler contributions to
  volatility and tracking error by factor, group and holding; marginal risk.
- **Coverage.** The account's stocks and the benchmark's on the universe's scale; index
  funds looked through with their basis as its own risk; the bond by time-series beta;
  cash by currency.
- **VaR and ES** parametric, Cornish-Fisher, historical and factor Monte Carlo with
  multivariate Student-t; **stress tests** from historical replays and hypothetical
  factor shocks.
- **Validation.** A forward-only rolling forecaster; bias statistics with their band,
  MRAD and a truth yardstick; Kupiec, Christoffersen and the Basel traffic light; the
  minimum-variance experiment across estimators.
- **Persistence**: `risk_factor_returns`, `risk_forecasts`, `risk_exposures` and
  migration 0005. The risk run checks its controls before writing; the backtest and
  factor volatilities are recounted in SQL on SQLite and PostgreSQL.
- **`meridian risk`**: `model`, `portfolio`, `contributions`, `var`, `stress`,
  `backtest`, `validate`, `report`, `run` and `stored`.
- **Sixteen charts** (seventy-seven in the gallery), three methodology notes and ADRs
  0023 to 0026. `scipy` and `arch` join the dependencies, `scikit-learn` the
  development tools.

### Found by the backtest

- Index funds deviate from their look-through by about 12% a year; without a basis
  line the tracking error was under-forecast (bias 1.18).
- The universe's beta factor was at first only loosely tied to the world factor, so
  the Day 2 stocks' market betas (0.57 to 1.20) could not flow through the model.
- Bayesian shrinkage of specific risk widened the spread of the stocks' own biases
  fourfold on the universe and pulled the account's tracking error a fifth too low;
  it is off by default.
- A drift cannot make a crash: with volatility four times normal, the first "2020
  crash" window ended up. Regimes now fix their factors' totals.

## [0.5.0] - 2026-09-25

Day 4: performance and attribution. What the return was, measured three ways; a
benchmark that can be taken apart; and an attribution that explains the active return
to the last basis point, with currency and costs kept apart and the days linked.

### Added

- **Returns.** Daily time-weighted returns chained from the value bridge's own
  investment result, with flows at the start of the day; money-weighted returns by
  XIRR on actual days; Modified Dietz; factsheet periods (MTD, QTD, YTD, one year,
  since inception), annualised only beyond a year; monthly and yearly tables.
- **Holding contributions.** Every day taken apart into one exposure per holding
  (opening value, local result with dividends and coupons from the ledger, currency
  result) and one per currency for cash, with costs apart. Largest daily residual on
  the demonstration: 9e-11 dollars. Linked by Cariño, the contributions sum to the
  time-weighted return.
- **The benchmark.** `SyntheticMarket.companion` generates new instruments in the same
  market, replaying its market and sector factors without changing any existing
  price. Meridian World Equity: a cap-weighted, total-return index of 36 stocks with
  drifting weights and returns split into local and currency. A policy benchmark of
  80% equity, 15% the Treasury bond (total return from dirty prices and coupons) and
  5% cash, rebalanced monthly.
- **Brinson-Fachler attribution** by sector and by region: allocation against the
  benchmark's total return, selection, interaction as the exact remainder; currency
  per currency and costs as their own effects; index funds looked through to the
  benchmark's constituents. Daily residual around 1e-17.
- **Cariño linking** of daily effects over any period, with the unlinked gap
  reported; linked monthly attribution.
- **Risk statistics**: volatility, downside deviation, Sharpe, Sortino, tracking error,
  information ratio, beta, Jensen's alpha, correlation, up and down capture, hit rate,
  historical VaR and expected shortfall, skewness and kurtosis, drawdown episodes with
  recovery dates, and rolling 63-day windows.
- **Persistence**: `performance_returns` (one row per day) and `attribution_effects`
  (linked effects per period, dimension and segment), migration 0004. The
  performance run refuses to write a period whose residual exceeds 1e-10.
- **`meridian perf`**: `run`, `returns`, `attribution`, `risk`, `contributions`,
  `factsheet` and `stored`.
- **Fifteen charts** (sixty-one in the gallery), three methodology notes and ADRs 0019
  to 0022.

### Changed

- The data model diagram now includes the two performance tables.

## [0.4.0] - 2026-09-24

Day 3: portfolio accounting. A double-entry book of record at cost, tax lots that know
their holding period and their wash sales, the same disposals under two tax codes, a
value bridge with no residual, and a reconciliation that is measured rather than
asserted.

### Added

- **The general ledger.** A chart of accounts numbered by class, journal entries with
  one sign convention (debit positive), postings in local and base currency, entries
  that must balance in base and in each local currency, and a ledger answering
  balances, activity and the trial balance by date - also computed in SQL and held
  equal to it account by account on SQLite and PostgreSQL.
- **The trade blotter.** Bookings, amendments and cancellations as versions with their
  knowledge time; the book as known at any moment is a replay. Settlement fails with
  contractual and actual dates.
- **Settlement cycles by market and date**, including the US move to T+1 on 28 May
  2024 and the announced European move in 2027, counted on the joint calendar of the
  exchange and the settlement currency.
- **The accounting engine**: purchases and sales against payables and receivables,
  currency results on settlement and conversion, commission capitalised, dividends
  with withholding split into reclaimable and lost, bond accrued interest bought and
  recovered, transfers in kind with carried cost and acquisition date, and splits,
  stock dividends, spin-offs and mergers from the corporate action feed.
- **Tax lots with tax attributes** - holding period start, opening FX rate, wash sale
  adjustment - kept apart from book cost; realised lots with the gain split exactly
  into price and currency.
- **The US wash sale rule** with its 30-day look-ahead, replacement capacity per
  purchase and deferred matches; Schedule D netting with the $3,000 limit and
  carryforward; Form 8949 rows; lot choice under four methods with a minimum-tax
  order proved optimal by a property test.
- **UK share matching**: same-day, 30-day and section 104 pool, in sterling, with tax
  years, the exempt amount and the October 2024 rate change.
- **Daily valuation** in local and base currency with a staleness limit, and a
  **value bridge** whose residual is zero on every day of the demonstration and of
  random books generated by a property test.
- **Custodian reconciliation** on settled terms, with breaks classified into eight
  causes, a break register that ages them, and a synthetic custodian that plants
  breaks to measure it: recall 100%, precision 100%, and nothing raised on clean
  statements.
- **The demonstration book**: two and a half years of a four-currency account,
  including a transfer in kind, two tax-loss harvests (one a wash sale), a failed
  settlement and a trade corrected at month-end.
- **Persistence**: six tables and migration 0003; the accounting run checks its
  controls before writing anything.
- **`meridian book`**: `run`, `positions`, `lots`, `cash`, `gains`, `lot-choice`,
  `nav`, `bridge`, `trial-balance`, `journal`, `reconcile` and `wash-sales`.
- **Sixteen charts** (forty-six in the gallery), five methodology notes and ADRs 0014
  to 0018.

### Changed

- `TaxLot` gains `holding_period_start`, `open_fx_rate` and `wash_sale_adjustment`;
  corporate action entitlements carry them through splits, spin-offs and mergers.

### Fixed

- A wash sale replacement matched to two sold lots was tacked twice. Drawing the
  Bayer wash sale showed a holding period 598 days longer than the replacement's own;
  each replacement share is now used once and tacked with its own sold shares' period.
- A split's per-share cost was rounded to 1e-10 by the entitlement rules, leaving the
  lots 7e-8 dollars away from the ledger. Found by the control that ties the
  sub-ledger to the lots; the engine now rescales exactly.

## [0.3.0] - 2026-09-22

Day 2: market data. Prices with a memory of what was known and when, quality rules
that are measured rather than asserted, corporate actions applied to both the history
and the book, and one published price built from several disagreeing sources.

### Added

- **Bitemporal market data.** Every observation carries its value date and the
  moment the platform learned it; corrections are new records, never edits, so the
  series as known at any past moment can be rebuilt and the look-ahead in a restated
  history can be measured. The same "as known at" query is implemented in memory and
  in SQL and tested case for case against each other.
- **A synthetic market** with the stylised facts a quality rule has to survive:
  Student-t innovations, GARCH(1,1) volatility clustering, market and sector factors,
  one exchange calendar per instrument, and splits and dividends that move the quoted
  price. Its economic value is kept as ground truth for the adjustment code.
- **A fault injector** that damages clean data in the nine ways real feeds fail and
  records exactly where, so the rules can be scored.
- **Thirteen quality rules** across the five DAMA dimensions, with robust (median and
  MAD) statistics on event-adjusted returns net of a leave-one-out market proxy, an
  engine that scores each series and decides what may be published, and detection
  measured at 100% recall and 97% precision over 126 planted faults.
- **Corporate actions**: dividends, splits, stock dividends, spin-offs, rights, cash
  and stock mergers and symbol changes - with CRSP-style back-adjustment as a derived
  view, and entitlement rules that conserve cost basis, tack holding periods, pay
  cash in lieu of fractional shares and tax merger boot under IRC 356/358.
- **A golden copy** built by ranked consensus with price challenges recorded, and
  **FX history** with as-of lookup, cross rates and staleness limits.
- **A security master**: identifiers mapped to instruments over validity intervals
  and resolved by date, and golden records built field by field with lineage,
  conflicts and check-digit validation.
- **The end-of-day pricing run** - collect, record, validate, reconcile, publish -
  with five new tables, migration 0002, and batch upserts.
- **`meridian market`**: `rules`, `quality`, `price --persist`, `history --known-at`,
  `actions`, `adjust` and `xref --on`.
- **Thirteen charts** (thirty in the gallery), four methodology notes and ADRs 0009
  to 0013.

### Changed

- `PriceRepository` and `FxRateRepository` gained batch upserts, and observations are
  written with one insert rather than one merge per row: the demonstration load fell
  from 24 s to 2.8 s.
- The market proxy used by the outlier rules is exposed as `attach_market_proxy`.
- The demonstration book gains one clearly labelled synthetic instrument, so the
  history contains a 4-for-1 split to adjust for.

### Fixed

- A stale source can no longer outvote the source that moved. Two vendors resending
  yesterday's close agreed with each other, formed the median and excluded the one
  vendor with the right price; the worst golden-copy error fell from 254 bp to 13 bp
  once unchanged values were set aside on days when other sources moved.
- The synthetic market's GARCH parameters now satisfy the fourth-moment condition.
  With Student-t(4) innovations it failed, and a two-year sample came out 56% more
  volatile than specified.

## [0.2.0] - 2026-09-20

Day 1, continued: the financial mathematics the rest of the platform will be built on,
and the charts that argue for it.

### Added

- **Analytics layer.** Safeguarded Newton root finding with a bisection fallback;
  yield curves bootstrapped from par yields with the round trip asserted at every
  tenor; bond pricing, accrued interest, yield to maturity, Macaulay and modified
  duration, convexity, DV01, z-spread and key rate durations.
- **Payment schedules.** Rolled backwards from maturity, with the sticky end-of-month
  rule, four stub conventions, payment lags, and adjusted or unadjusted accrual.
- **Five more calendars** - the US bond market, Xetra, SIX, Tokyo and the weekend
  base - with holiday names, and `JointCalendar` for cross-border settlement.
- **Four more day-count conventions**: ACT/ACT ICMA, BUS/252, 30E/360 ISDA and
  ACT/365.25, including the context each one needs.
- **Compounding conventions** with exact conversion between them, and three
  interpolation methods including Fritsch-Carlson monotone cubic.
- **LEI validation** by ISO 7064 MOD 97-10, identifier scheme detection, and
  expected-check-digit reporting for near misses.
- **Eleven more charts**, an entity-relationship diagram generated from the live
  SQLAlchemy metadata, and one gallery definition behind the docs, the CLI and the
  tests.
- **`meridian rates` and `meridian charts`** command groups; `calendar matrix`,
  `calendar ladder` and named holidays.
- **Two methodology notes** - fixed income mathematics and calendar conventions -
  and ADRs 0006 to 0008.

### Changed

- Chart title blocks scale with the figure, so a tall multi-panel page and a single
  wide chart look the same.
- Repository queries return `Sequence` rather than `list`: a query result is a
  snapshot, not a collection to mutate.

## [0.1.0] - 2026-09-19

The foundation: the vocabulary every later module is written in.

### Added

- **Core value objects.** `Money` on `Decimal` with banker's rounding, currency tagging
  and a remainder-conserving `allocate`; 22 currencies with correct minor units; FX rates
  with inversion and pivot cross rates.
- **Security identifiers.** ISIN, CUSIP, SEDOL and FIGI with their real check-digit
  algorithms, CUSIP-to-ISIN conversion, and tests against published identifiers.
- **Trading calendars.** NYSE, LSE and TARGET generated from statutory rules, business-day
  conventions, T+n settlement arithmetic, and ACT/360, ACT/365F, 30/360 and ACT/ACT ISDA
  day counts.
- **Domain model.** Instruments (equity, fund, bond, cash), clients, households, accounts,
  portfolios with an investment policy, transactions with fixed sign conventions, and
  positions as tax lots with FIFO, LIFO, HIFO, average-cost and specific identification.
- **Persistence.** Typed SQLAlchemy 2.0 schema with fixed-scale `NUMERIC` columns,
  explicit domain-to-row mappers, repositories returning domain objects, a unit of work,
  and Alembic migrations with a drift check.
- **Visualisation.** A house chart style, and the exchange trading calendar chart showing
  the weekdays on which markets disagree.
- **CLI.** `meridian info`, `db init|seed|status`, `calendar list|holidays|settle|chart`
  and `security validate|to-isin`, with structured logging.
- **Demonstration book.** Twelve instruments across four currencies, a taxable account and
  a pension, and eight trades spanning short and long holding periods.
- **Project infrastructure.** CI running lint, format, types, the suite on Python 3.10 to
  3.12, and integration tests against PostgreSQL 16; architecture decision records
  0001-0005.

[0.6.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.6.0
[0.5.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.5.0
[0.4.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.4.0
[0.3.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.3.0
[0.2.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.2.0
[0.1.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.1.0
