# Chart gallery

Every figure the platform produces, rebuilt from the current source with one
command:

```bash
meridian charts gallery --out docs/images
```

The valuation date is fixed at 2026-09-18 and the reference instruments are defined
in [`meridian.gallery`](../src/meridian/gallery.py), so these images are
reproducible and cannot drift from the code that draws them. The market data figures
are drawn from the seeded demonstration market in `meridian.services`, planted faults
and all. The book of record, tax and reconciliation figures are drawn from the
demonstration account booked on top of that market, and the performance figures
from that account measured against its policy benchmark. The risk figures come from a
factor model estimated on a synthetic 500-stock universe whose true risk is known, and
applied to the same account. The compliance figures come from the account's mandate,
written in the Meridian mandate language and checked on every day of its history. The
optimisation figures come from the same account rebalanced by the tax-aware optimiser, and
from a tax-alpha simulation on the factor model's universe. The execution figures come from
that rebalance traded the next day through a simulated intraday market, and the reporting
figures are pages of the client report assembled from all of it. The web platform figures
are drawn from the application itself (its role matrix and OpenAPI document), from a
working day driven over HTTP, from the source's import graph and from the release tags. The
validation and rates figures come from QuantLib, from 36 years of the US Treasury's published
par curve and the Federal Reserve's GSW curve, packaged with the code, and from illustrative
SOFR quotes built on the Treasury curve.

---
### Calendars

**Exchange trading calendars** - A year of NYSE, London and TARGET, and the days on which they disagree.

![Exchange trading calendars](images/trading-calendar-2026.png)

**Where the markets disagree** - Pairwise count of weekdays when one market trades and another is shut.

![Where the markets disagree](images/calendar-divergence.png)

**Settlement ladder** - Where T+0 to T+3 land in each market, and in the joint settlement calendar.

![Settlement ladder](images/settlement-ladder.png)

### Rates

**Yield curve, three ways** - Zero, par and forward curves from one set of quoted par yields.

![Yield curve, three ways](images/yield-curve.png)

**Interpolation is a modelling choice** - Three methods that agree at the pillars and disagree everywhere else.

![Interpolation is a modelling choice](images/curve-interpolation.png)

**Curve scenarios** - Parallel shifts and key-rate twists applied to the pillars.

![Curve scenarios](images/curve-scenarios.png)

**Duration is a straight line** - The price-yield curve against its first- and second-order approximations.

![Duration is a straight line](images/price-yield.png)

**Key rate durations** - Where on the curve a bond's interest rate risk actually sits.

![Key rate durations](images/key-rate-durations.png)

**Compounding conventions** - The same quoted rate, four conventions, materially different money.

![Compounding conventions](images/compounding.png)

**A SOFR curve from twenty swaps** - Zero and forward curves bootstrapped from dated OIS instruments, each repriced exactly.

![A SOFR curve from twenty swaps](images/sofr-curve.png)

**Four interpolators, one set of quotes** - What linear, log-linear, monotone cubic and monotone convex say about forwards.

![Four interpolators, one set of quotes](images/interpolation-forwards.png)

**Locality** - How far a one basis point bump in the 5-year quote travels along the forward curve.

![Locality](images/interpolation-locality.png)

**The Jacobian** - How each quote moves each point of the zero curve, local and non-local.

![The Jacobian](images/curve-jacobian.png)

**Bucketed DV01 and its hedge** - A swap book's risk in the quoted instruments, and the swaps that flatten it.

![Bucketed DV01 and its hedge](images/bucketed-dv01.png)

**The Treasury curve since 1990** - Every published par curve, 1990-2026, with the events that moved it.

![The Treasury curve since 1990](images/treasury-history.png)

**The yield curve as a landscape** - Month-end par yields since 1990 as a surface.

![The yield curve as a landscape](images/treasury-surface.png)

**Level, slope and curvature** - Principal components of 36 years of daily Treasury curve changes.

![Level, slope and curvature](images/curve-pca.png)

**The factors through time** - Rolling variance explained, and the cumulative level and slope factors.

![The factors through time](images/curve-pca-history.png)

**Nelson-Siegel and Svensson on real curves** - Four days of the Treasury curve, fitted, beside the Federal Reserve's own fit.

![Nelson-Siegel and Svensson on real curves](images/nss-fits.png)

**Our fit against the Fed's, since 1990** - Quarterly Svensson fits to the Treasury curve minus GSW, and how well six numbers fit.

![Our fit against the Fed's, since 1990](images/nss-vs-gsw.png)

### Validation

**Meridian against QuantLib** - Every check of the rates engine against the reference library, with its tolerance.

![Meridian against QuantLib](images/quantlib-reconciliation.png)

**What QuantLib found in the calendars** - Every weekday 1990-2060 the two disagreed, before and after the calendars learnt history.

![What QuantLib found in the calendars](images/calendar-breaks.png)

**The astronomy decides** - The time of Japan's equinoxes, and the years QuantLib's formula names the wrong day.

![The astronomy decides](images/equinox-arbiter.png)

### Cashflows

**Payment schedule** - Accrual periods, the stub, and the payments moved by the business-day rule.

![Payment schedule](images/bond-schedule.png)

**Cash flows and their present value** - What the bond pays, and what each payment is worth on the curve today.

![Cash flows and their present value](images/bond-cashflows.png)

**Accrued interest** - The sawtooth the buyer pays the seller, resetting at every coupon.

![Accrued interest](images/accrued-interest.png)

**Where a bond's value comes from** - Coupons against the return of principal, discounted on the curve.

![Where a bond's value comes from](images/value-composition.png)

**A gilt goes ex-dividend** - Negative accrued interest and the cum-to-ex drop, priced by the DMO's formula.

![A gilt goes ex-dividend](images/gilt-ex-dividend.png)

### Money

**Allocating an amount** - A conserving split against naive rounding, and the cash the naive one loses.

![Allocating an amount](images/allocation.png)

**Rounding error accumulates** - The same split repeated: one method stays on zero, the other walks away.

![Rounding error accumulates](images/rounding-drift.png)

**Day-count conventions** - Year fractions and accrued interest for one period under every convention.

![Day-count conventions](images/day-counts.png)

### Quality

**Market data quality dashboard** - Scores by series and dimension, findings by rule, and where in time the problems sit.

![Market data quality dashboard](images/quality-dashboard.png)

**Finding the bad prints** - One exchange feed with a stale run, a bad tick and a gap, and the robust score that caught them.

![Finding the bad prints](images/anomaly-detection.png)

**Why the median, not the mean** - Three bad ticks in one window defeat the classical z-score and not the robust one.

![Why the median, not the mean](images/robust-vs-classical.png)

**Measured, not asserted** - Recall by fault type and precision by rule, against faults planted in three seeded markets.

![Measured, not asserted](images/detection-scorecard.png)

**Expected against received** - Every weekday for every instrument, judged on that instrument's own exchange calendar.

![Expected against received](images/coverage-calendar.png)

### Market Data

**A split is not a crash** - Raw, capital-adjusted and total-return histories against the generator's economic truth.

![A split is not a crash](images/split-adjustment.png)

**Corporate actions on tax lots** - A split, a spin-off and a dividend applied to a three-lot holding, with basis conserved.

![Corporate actions on tax lots](images/corporate-actions-lots.png)

**What we knew, and when** - First prints against restated values: the look-ahead a backtest on restated data enjoys.

![What we knew, and when](images/point-in-time.png)

**Three vendors, one price** - Each vendor against the golden copy, and every source's error against the truth.

![Three vendors, one price](images/vendor-consensus.png)

**The triangle must close** - Cross rates against the rates implied by their USD legs, and the cross matrix on one day.

![The triangle must close](images/fx-triangle.png)

**The synthetic market behaves like a real one** - Fat tails and volatility clustering: the stylised facts every quality rule has to survive.

![The synthetic market behaves like a real one](images/return-distribution.png)

### Reference Data

**An identifier is not a name** - Ticker renames, a reused ticker and an ISIN change, resolved by date.

![An identifier is not a name](images/identifier-timeline.png)

**One security, three vendors** - Golden records built field by field, with lineage, conflicts and refused values.

![One security, three vendors](images/golden-record.png)

### Accounting

**Where the value went** - A year of NAV bridged exactly: flows, price, currency, income and costs, with each holding's share.

![Where the value went](images/valuation-waterfall.png)

**Two and a half years of the book** - NAV by holding, shaded by currency, with the cumulative investment result decomposed beneath it.

![Two and a half years of the book](images/nav-history.png)

**Price and currency, separated** - Each holding's unrealised result split at its own purchase rates, and the currencies behind it.

![Price and currency, separated](images/fx-separation.png)

**Cash by settlement date** - Settled against projected cash in four currencies while the account was funded, and what settles next.

![Cash by settlement date](images/cash-ladder.png)

**The day the settlement cycle changed** - Every trade's settlement lag by market, before and after US equities moved to T+1.

![The day the settlement cycle changed](images/settlement-cycles.png)

**Income: earned, paid, taxed** - Dividends and coupons from ex-date to pay date, with withholding split into reclaimable and lost.

![Income: earned, paid, taxed](images/income-calendar.png)

**The book balances** - The trial balance as a chart, and net assets = capital + net income at every month-end.

![The book balances](images/trial-balance.png)

**A correction is a replay** - NAV as reported each evening against NAV as now known, around a trade booked at the wrong price.

![A correction is a replay](images/restatement.png)

### Tax

**Every tax lot the account has held** - Lots from acquisition to disposal, with holding periods, tacking and wash sale adjustments.

![Every tax lot the account has held](images/tax-lot-map.png)

**A wash sale** - A harvested loss bought back inside 30 days: the loss moves into the replacement lots' tax basis.

![A wash sale](images/wash-sale.png)

**Which lots you sell is worth money** - One sale under FIFO, LIFO, highest cost and minimum tax: the gain of each term and the tax on it.

![Which lots you sell is worth money](images/lot-selection.png)

**One book, two tax codes** - The same disposals under US lot rules and UK same-day, 30-day and section 104 matching.

![One book, two tax codes](images/us-vs-uk.png)

**Realised gains by tax year** - Netted the way Schedule D nets them, with losses carried forward and the wash sale deferral shown.

![Realised gains by tax year](images/realised-gains.png)

**The long-term horizon** - Open lots by days held against unrealised gain, and each short-term lot's road to long-term.

![The long-term horizon](images/unrealised-horizon.png)

### Reconciliation

**Reconciliation against the custodian** - Breaks by day and cause, recall against planted breaks, and how long each stayed open.

![Reconciliation against the custodian](images/reconciliation-dashboard.png)

**One morning, line by line** - The book against the custodian's statement, with every difference and the reason given for it.

![One morning, line by line](images/reconciliation-statement.png)

### Performance

**Performance against the benchmark** - Growth of 100, the active return accumulating, and the drawdowns of both.

![Performance against the benchmark](images/cumulative-performance.png)

**From the benchmark's return to the portfolio's** - Allocation, selection, interaction, currency and costs, linked by Cariño, and by sector.

![From the benchmark's return to the portfolio's](images/attribution-bridge.png)

**Attribution by sector** - Average weights, local returns and the three Brinson-Fachler effects, sector by sector.

![Attribution by sector](images/sector-attribution.png)

**Attribution by region** - The same active return decomposed by region, index funds looked through.

![Attribution by region](images/region-attribution.png)

**Attribution, month by month** - Each month's effects by sector, linked within the month so the rows add up.

![Attribution, month by month](images/attribution-calendar.png)

**Why effects have to be linked** - The plain sum of daily active returns drifts from the compounded active return; Cariño closes the gap.

![Why effects have to be linked](images/attribution-linking.png)

**Which return?** - Time-weighted, money-weighted and Modified Dietz, year by year, with the client's flows.

![Which return?](images/return-methods.png)

**Returns by month** - A calendar of monthly returns and of active returns against the benchmark.

![Returns by month](images/monthly-returns.png)

**Risk, as it moved** - Rolling volatility, tracking error, information ratio and beta.

![Risk, as it moved](images/rolling-risk.png)

**Return against risk** - The portfolio, its benchmark and every holding, with lines of equal Sharpe ratio.

![Return against risk](images/risk-return.png)

**Drawdowns** - The deepest falls from peak, how long they lasted and whether they recovered.

![Drawdowns](images/drawdown-episodes.png)

**Currency, kept apart** - Currency weights against the benchmark's and the effect of each currency.

![Currency, kept apart](images/currency-attribution.png)

**Who drove the return** - Each holding's linked contribution to the time-weighted return.

![Who drove the return](images/contribution-to-return.png)

**Day by day against the benchmark** - The distribution of daily active returns, beta, and up and down capture.

![Day by day against the benchmark](images/active-days.png)

**The performance report** - The one page a client reads: returns by period, risk, attribution and contributions.

![The performance report](images/factsheet.png)

### Risk

**Risk decomposition** - Volatility and tracking error split into market, industries, styles, currencies and specific risk.

![Risk decomposition](images/risk-decomposition.png)

**Bias statistics** - Ten years of forecasts scored against outcomes, with the 95% band, for EWMA, the sample and the truth.

![Bias statistics](images/bias-statistics.png)

**Why a sample covariance fails** - Eigenvalues of 500 stocks over 252 days against the Marchenko-Pastur law of pure noise.

![Why a sample covariance fails](images/eigenvalue-spectrum.png)

**What an optimiser builds from each estimator** - Minimum-variance portfolios: the risk each covariance estimator promised, and delivered.

![What an optimiser builds from each estimator](images/minimum-variance.png)

**Factor returns** - What the market paid each style and each industry, from the daily cross-sectional regressions.

![Factor returns](images/factor-returns.png)

**Volatility forecasts against the truth** - GARCH, EWMA and an equal-weighted window forecasting the world factor's volatility.

![Volatility forecasts against the truth](images/volatility-forecasts.png)

**The factor covariance** - Correlations and volatilities of the twenty-one factors on the report date.

![The factor covariance](images/factor-correlation.png)

**Active exposures** - The account's industry, style and currency exposures against its benchmark's.

![Active exposures](images/active-exposures.png)

**Risk by holding** - Each holding's contribution to volatility and to tracking error.

![Risk by holding](images/risk-contributions.png)

**VaR backtest** - The account's daily returns against the morning's 99% VaR, with the Basel traffic light.

![VaR backtest](images/var-backtest.png)

**VaR four ways** - Parametric, Cornish-Fisher, historical and Monte Carlo VaR and expected shortfall.

![VaR four ways](images/var-methods.png)

**Stress tests** - Historical replays and hypothetical shocks applied to today's exposures.

![Stress tests](images/stress-tests.png)

**The account's forecasts, validated** - Rolling bias of the account's volatility and tracking error forecasts, against the truth's own score.

![The account's forecasts, validated](images/book-bias.png)

**Specific risk calibration** - Bias of specific-risk forecasts by size decile, with and without Bayesian shrinkage.

![Specific risk calibration](images/specific-risk.png)

**How much the factors explain** - Daily R-squared of the cross-sectional regressions and how often each factor is significant.

![How much the factors explain](images/regression-quality.png)

**The risk report** - The page the risk committee reads: risk by source, contributions, stress tests and the VaR backtest.

![The risk report](images/risk-report.png)

### Compliance

**Headroom against every rule** - Each rule of the mandate as the share of its limit in use, with its warning level.

![Headroom against every rule](images/limit-utilisation.png)

**The breach register over time** - Every breach from opening to close, active or passive, hard limits outlined.

![The breach register over time](images/breach-timeline.png)

**Utilisation month by month** - The highest utilisation of every rule in every month, breaches marked.

![Utilisation month by month](images/utilisation-heatmap.png)

**One issuer, two limits** - Microsoft held directly and including the index funds, against its hard and soft limits.

![One issuer, two limits](images/issuer-limits.png)

**What the index funds hide** - Issuer exposure direct and looked through, and excluded industries reached through funds.

![What the index funds hide](images/look-through.png)

**The breach register** - Breaches by rule and cause, how long they lasted, and how they ended.

![The breach register](images/breach-register.png)

**Pre-trade decisions** - Test orders against the mandate, and the largest size each limit allows.

![Pre-trade decisions](images/pretrade-decisions.png)

**The history, replayed** - The book's own trades through the pre-trade check, one at a time and as baskets.

![The history, replayed](images/pretrade-replay.png)

**The UCITS screen** - Issuers above 5% against the 40% ceiling, and each issuer against the 10% limit.

![The UCITS screen](images/ucits-screen.png)

**How a rule is read** - A rule of the mandate language and the tree the Lark parser builds from it.

![How a rule is read](images/rule-parse-tree.png)

**Asset allocation bands** - Equities, fixed income and cash against the mandate's bands, breaches shaded.

![Asset allocation bands](images/allocation-bands.png)

**The compliance report** - The page the compliance committee reads: utilisation, breaches and today's orders.

![The compliance report](images/compliance-report.png)

### Optimisation

**The efficient frontier of tracking error against tax** - Every point a full compliant rebalance; the proposal, the tax-blind trade and today's portfolio placed on it.

![The efficient frontier of tracking error against tax](images/tax-frontier.png)

**The proposed rebalance** - Weights before and after against the target, and the tax each sale realises or saves.

![The proposed rebalance](images/rebalance-trades.png)

**Which lots to sell** - Tax per dollar sold, lot by lot, and the same trades relieved first in, last in and highest cost first.

![Which lots to sell](images/lot-relief.png)

**The harvesting map** - Every open lot by days held and gain, the one-year line, the wash-sale window, and the lots sold.

![The harvesting map](images/harvesting-map.png)

**Non-convex rules met in rounds** - Wash-sale repairs and the convex-concave rounds that hold active share above its floor.

![Non-convex rules met in rounds](images/solve-rounds.png)

**Trading costs** - Commission, half-spread and square-root market impact for every trade, and the impact law.

![Trading costs](images/trading-costs.png)

**From weights to orders** - The optimiser's trades rounded to board lots and minimum tickets by a mixed-integer programme.

![From weights to orders](images/order-rounding.png)

**Three managers, one account** - Tax-blind, tax-aware and harvesting rebalances of the same account on the same day.

![Three managers, one account](images/three-managers.png)

**The mandate after the trades** - The Day 6 engine on the proposal as one basket: every limit's utilisation before and after.

![The mandate after the trades](images/post-trade-compliance.png)

**Tax alpha across simulated paths** - Annual after-tax return over the tax-blind manager, on liquidation and as held, for three managers.

![Tax alpha across simulated paths](images/tax-alpha.png)

**After-tax wealth** - Wealth against the tax-blind manager over three years, and the tax each manager paid.

![After-tax wealth](images/after-tax-wealth.png)

**The harvest calendar** - Losses harvested and gains realised month by month, the carryforward, and the dispersion behind them.

![The harvest calendar](images/harvest-calendar.png)

**Risk spent to save tax** - Ex-ante tracking error month by month for each manager against the tax-aware budget.

![Risk spent to save tax](images/tracking-error-budget.png)

**The rebalance proposal** - One page for the investment committee: numbers, orders, frontier and checks.

![The rebalance proposal](images/rebalance-proposal.png)

### Execution

**Implementation shortfall of the rebalance** - The day's cost against the decision prices, split into delay, spread, impact, timing, opportunity and fees.

![Implementation shortfall of the rebalance](images/implementation-shortfall.png)

**Five ways to work the same order** - TWAP, VWAP, POV, IS and Close: planned and realised completion against the volume curve.

![Five ways to work the same order](images/execution-trajectories.png)

**The Almgren-Chriss frontier** - Expected cost against its risk for one block, and the trajectories from risk-neutral to urgent.

![The Almgren-Chriss frontier](images/almgren-chriss-frontier.png)

**One block through the day** - The price with and without our trades, every fill, and the decision, arrival, average and VWAP.

![One block through the day](images/intraday-execution.png)

**The same blocks, five algorithms** - Every block re-run with each algorithm on the same simulated day: cost, risk, fill rate, VWAP slippage.

![The same blocks, five algorithms](images/algorithm-comparison.png)

**Calibrating the impact model** - The square-root coefficient recovered from the desk's history, measured and as observed, against the truth.

![Calibrating the impact model](images/impact-calibration.png)

**Pre-trade estimate against outcome** - The cost model's forecast against each order's realised spread, impact and fees, by order size.

![Pre-trade estimate against outcome](images/pre-post-trade.png)

**Block orders allocated to accounts** - Three accounts' orders traded as one block per stock and shared back at one price, pro rata.

![Block orders allocated to accounts](images/block-allocation.png)

**An order's life in FIX states** - A parent order and its child orders through new, partially filled, cancelled, filled and expired.

![An order's life in FIX states](images/order-lifecycle.png)

**Participation minute by minute** - Each block's share of the market's volume through the day, against the 25% cap.

![Participation minute by minute](images/participation-heatmap.png)

**The trading blotter** - Every block of the day: algorithm, fill, slippage against arrival and shortfall.

![The trading blotter](images/trading-blotter.png)

### Reporting

**The client report** - All nine pages of the quarterly client report, assembled from every module's numbers.

![The client report](images/client-report-pages.png)

**Client report: the summary page** - Value, returns, risk, the mandate and the tax position on one page, with the quarter in brief.

![Client report: the summary page](images/client-report-summary.png)

**Client report: trading and costs** - The account's share of the block orders, the prices it received and what trading cost.

![Client report: trading and costs](images/client-report-trading.png)

### Web Platform

**The architecture** - Users, the API and its seven controls, the nine modules, storage and operations.

![The architecture](images/platform-architecture.png)

**Seven layers between a request and the data** - A working day's requests, and what each layer stopped.

![Seven layers between a request and the data](images/request-pipeline.png)

**Role-based access control** - Permissions by role, with separation of duties.

![Role-based access control](images/rbac-matrix.png)

**The API surface** - Every endpoint and the permission it requires, read from the OpenAPI document.

![The API surface](images/api-surface.png)

**Latency, endpoint by endpoint** - Every request of the working day, with its median and 95th percentile.

![Latency, endpoint by endpoint](images/api-latency.png)

**The operations dashboard** - Request rate by user, statuses, latency and the busiest routes.

![The operations dashboard](images/operations-dashboard.png)

**A tamper-evident audit trail** - The hash chain, an edited record caught, and the cost of verifying.

![A tamper-evident audit trail](images/audit-chain.png)

**Who was refused, and why** - Each person's requests by the platform's answer.

![Who was refused, and why](images/access-outcomes.png)

**Orders under four eyes** - Pre-trade checks, the approval threshold and the second person.

![Orders under four eyes](images/four-eyes.png)

**Deployment** - The Docker Compose topology: database, migrations, API, Prometheus, Grafana.

![Deployment](images/deployment-topology.png)

**The package graph** - Which package imports which, parsed from the source.

![The package graph](images/package-graph.png)

**The tests** - Test functions by area, property-based among them, and what CI runs.

![The tests](images/test-landscape.png)

**Security controls** - The OWASP API Security Top 10 mapped to controls and the tests that prove them.

![Security controls](images/security-controls.png)

**Nine days, ten releases** - Code, tests, figures and decisions at every release tag.

![Nine days, ten releases](images/codebase-growth.png)

**Nine days, one platform** - Each day's module and its headline chart.

![Nine days, one platform](images/nine-days.png)

### Platform

**The data model** - Every table, column and foreign key, drawn from the live SQLAlchemy metadata.

![The data model](images/data-model.png)
