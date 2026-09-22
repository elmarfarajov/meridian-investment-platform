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
and all.

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

### Platform

**The data model** - Every table, column and foreign key, drawn from the live SQLAlchemy metadata.

![The data model](images/data-model.png)
