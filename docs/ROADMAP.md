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

**Chart:** exchange trading calendars, and the weekdays on which the markets disagree.

## Day 2 - Market data

**Issue #2.** Nothing downstream is better than the prices it is fed.

- Price and FX time series with a point-in-time view: what did we know, and when.
- Corporate actions - splits, dividends, spin-offs - applied to positions and to history.
- Data-quality rules: stale marks, outliers by robust z-score, missing days against the
  instrument's own trading calendar, and crossed FX quotes.
- A quality dashboard chart: coverage, staleness and the flagged points.

## Day 3 - Portfolio accounting

**Issue #3.** The book of record: if this is wrong, everything downstream is wrong.

- Trade capture, settlement ledger, cash and accrual accounting.
- Tax lot maintenance through buys, sells, splits and transfers; realised and unrealised
  gains split by holding period; the US wash-sale rule.
- Daily valuation in local and base currency, with FX revaluation separated from price
  return.
- Reconciliation: position and cash breaks against a custodian file.

**Chart:** a valuation waterfall - opening value, flows, price return, FX, income, costs,
closing value.

## Day 4 - Performance and attribution

**Issue #4.** What the return was, and where it came from.

- Time-weighted return with proper treatment of flows (Modified Dietz and true daily
  linking), money-weighted return by IRR.
- Brinson-Fachler attribution: allocation, selection and interaction against a benchmark,
  by sector and by region.
- Geometric linking of multi-period attribution by the Cariño method, so the effects
  actually sum to the excess return.
- Currency attribution separated from local return.

**Chart:** the attribution bridge from benchmark return to portfolio return.

## Day 5 - Risk

**Issue #5.** Risk is a forecast, and a forecast has to be validated.

- A fundamental multi-factor model: market, size, value, momentum, quality, plus
  sector and currency factors.
- Covariance estimation with EWMA and Ledoit-Wolf shrinkage; why a raw sample covariance
  on 500 assets and 250 days is unusable.
- Portfolio volatility, tracking error, marginal and component contribution to risk,
  parametric and historical VaR and expected shortfall.
- Model validation by bias statistics and rolling backtests - the part most toy risk
  models omit.

**Chart:** the risk decomposition, and the bias-statistic time series with its confidence
band.

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
