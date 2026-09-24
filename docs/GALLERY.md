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
from that account measured against its policy benchmark.

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

### Cashflows

**Payment schedule** - Accrual periods, the stub, and the payments moved by the business-day rule.

![Payment schedule](images/bond-schedule.png)

**Cash flows and their present value** - What the bond pays, and what each payment is worth on the curve today.

![Cash flows and their present value](images/bond-cashflows.png)

**Accrued interest** - The sawtooth the buyer pays the seller, resetting at every coupon.

![Accrued interest](images/accrued-interest.png)

**Where a bond's value comes from** - Coupons against the return of principal, discounted on the curve.

![Where a bond's value comes from](images/value-composition.png)

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

### Platform

**The data model** - Every table, column and foreign key, drawn from the live SQLAlchemy metadata.

![The data model](images/data-model.png)
