# The rates engine, validated

Day 1 built Meridian's rates arithmetic:

- calendars, day counts and schedules;
- a par-yield bootstrap;
- vanilla bond analytics.

It was tested against worked examples. Those examples were written by the same hand
as the code, so they share its misunderstandings. This note records what happened
when the engine was held to three independent standards:

1. **QuantLib**, the open-source library that banks, vendors and regulators use as
   the reference implementation of fixed income conventions;
2. **the real US Treasury curve**, every business day since 1990;
3. **the Federal Reserve's own fitted curve** (Gurkaynak, Sack and Wright), published
   daily since 1961.

It also records what was built so the engine could meet those standards:

- curves from dated instruments;
- monotone convex interpolation;
- Nelson-Siegel-Svensson fitting;
- principal components of curve moves;
- UK gilt conventions.

Every number below is produced by the code and drawn in the gallery.

---

## 1. Reconciliation, not agreement

A comparison with a reference library is run like a reconciliation. Every
difference is a *break*, and every break is resolved in one of two ways:

- **fixed**, when Meridian was wrong; or
- **explained**, when QuantLib is wrong or answers a different question. The
  explanation is written into
  [`meridian.devtools.reference.KNOWN_DIFFERENCES`](../../src/meridian/devtools/reference.py)
  with the reason and the evidence.

A test then asserts that the set of breaks is *exactly* the documented set. A new
break fails the build, and so does the disappearance of a documented one, which
would mean the explanation had gone stale.

![Meridian against QuantLib](../images/quantlib-reconciliation.png)

| Area | What is compared | Cases | Largest difference |
| --- | --- | ---: | ---: |
| Calendars | every weekday 1990-2060, six markets | 106,451 | 0 unexplained |
| Day counts | eight conventions on generated date pairs, month ends oversampled | 8 x 19,884 | 1.8e-15 |
| Bonds | accrued, clean price, duration, convexity, ACT/ACT ICMA and 30/360 US | 1,591 | 2e-12 |
| Gilts | a conventional gilt through two ex-dividend periods | 3 x 188 | 2.3e-13 |
| Curves | a 20-swap SOFR strip, at pillars and every 13 days between | 2,851 | 2.4e-13 |

---

## 2. What QuantLib found

### 2.1 Calendars that did not know their own history

Version 1.0.0 disagreed with QuantLib on **309 weekdays** between 1990 and 2060.
Every one was traced to a cause.

![What QuantLib found in the calendars](../images/calendar-breaks.png)

**Rules applied before they existed.**

- **NYSE.** Martin Luther King Jr. Day became a federal holiday in 1986, but the
  exchange first closed for it in **1998**.
- **TARGET.** It opened in 1999, closing only on New Year's Day and Christmas.
  Good Friday, Easter Monday, 1 May and 26 December were added **in 2000**.
- **Japan.**
  - The *Happy Monday* reforms moved Coming of Age Day and Sports Day to Mondays in
    2000, and Marine Day and Respect for the Aged Day in 2003.
  - Marine Day began in 1996 and Mountain Day in 2016.
  - The 2020 and 2021 Olympic special measures moved three holidays.
  - The Emperor's Birthday moved with the accession, and 2019 had none.

**Closures no rule predicts.**

| Market | Special closures |
| --- | --- |
| NYSE | the week of 11 September 2001; Hurricane Sandy (29-30 October 2012); days of mourning for Presidents Nixon (1994), Reagan (2004), Ford (2007), George H. W. Bush (2018) and Carter (9 January 2025) |
| London | the millennium; the royal wedding of 2011; the Golden, Diamond and Platinum Jubilees; the state funeral of Queen Elizabeth II; the coronation. The early May and spring bank holidays were *moved* in 1995, 2002, 2012, 2020 and 2022 |
| Tokyo | the enthronement ceremonies of 1990 and 2019, the Crown Prince's wedding in 1993, and the accession holiday that made 30 April to 2 May 2019 a ten-day Golden Week |

**Decisions made year by year.**

- **Good Friday.** SIFMA recommends a full close, *except* when the monthly
  employment report is published that day. Then it recommends an early close and
  the bond market is open. That happened in 1996, 1999, 2007, 2010, 2012, 2015,
  2021, 2023 and on 3 April 2026. Years not yet decided are projected by the
  pattern those decisions follow: Good Friday on the first Friday of the month.
- **Veterans Day.** On a Saturday, SIFMA does not move it to the Friday.

Each of these is now data, with a name. `holiday_name(date(2025, 1, 9))` answers
"National Day of Mourning for President Carter".

**72 breaks remain, and QuantLib is the side that is wrong or less specific.**

- **Xetra, 45 days.** Meridian closes on 31 December, as Deutsche Boerse's published
  trading calendar does; QuantLib's Xetra calendar trades.
- **Tokyo, 27 days.** Two causes:
  - QuantLib applies Japan's 2007 substitute-holiday rule to earlier years. Before
    2007 a Sunday holiday was substituted only by the Monday, so 6 May was a
    business day in 1992, 1997, 1998 and 2003.
  - QuantLib's equinox formula for 1980-1999 runs a day early. The next section
    settles it.

### 2.2 When two references disagree, the astronomy decides

Japan's Vernal and Autumnal Equinox Days are whatever calendar day, in Tokyo, the
Sun crosses the equator. The Cabinet announces them a year ahead from the National
Astronomical Observatory's ephemeris, so they cannot be looked up for 2060.

Most libraries, Meridian's version 1.0.0 among them, use a linear formula such as
`int(20.8431 + 0.242194 (y - 1980) - (y - 1980) // 4)`. QuantLib's constant for
the years before 2000 differs, and it lands a day early.

Neither formula can arbitrate, so Meridian now computes the equinox:

- **the algorithm:** Meeus, *Astronomical Algorithms* (1998), chapter 27, a mean
  equinox corrected by 24 periodic terms and good to about a minute;
- **the time scale:** Espenak and Meeus's polynomials for the difference between
  terrestrial and universal time;
- **the check:** the result matches the published instants to the minute. The 1990
  March equinox came at 21:19 UTC on 20 March, which was 06:19 on **21 March** in
  Tokyo, the day Japan observed.

![The astronomy decides](../images/equinox-arbiter.png)

The chart shows the time of day in Tokyo of every equinox from 1990 to 2060. The
dots fall in four diagonal lines because the equinox comes about six hours later
each year and resets with each leap day. The disputed years are all before 2000,
at every hour of the day: a constant offset in the formula, not an edge case at
midnight.

### 2.3 30/360 US had no February rule

The code called "30/360 US" was the ISDA 2006 *Bond Basis*, which has no rule for
February. SIFMA's 30/360 US adds two:

- the last day of February counts as the 30th when it starts a period;
- it also counts as the 30th when it ends a period that started on a last day of
  February.

Take 28 February 2025 to 31 August 2025:

- 30/360 US counts **180** days;
- the Bond Basis counts **183**.

Both conventions now exist under their own names. Both match QuantLib on every
one of 19,884 generated date pairs.

### 2.4 The street convention on 30/360 bonds

A bond priced from a yield discounts its first coupon over a fraction *w* = DSC/E
of a period. DSC is the days from settlement to the next coupon, and E the days in
the coupon period. SIFMA's *Standard Securities Calculation Methods* count both on
the bond's own basis, so a 30/360 bond uses 30/360 days, not calendar days.
Meridian used calendar days. It no longer does.

The demonstration Treasury carried a 30/360 day count. That was a second error: US
Treasuries accrue ACT/ACT. The fix moved its prices by at most 1.7 cents per 100.
It also moved the largest Microsoft purchase the Day 6 hard limits allow from
$85,976 to $85,978, and the documentation says so. Moving the Treasury to ACT/ACT
changes the whole demonstration book, so it is deferred to the Day 3 revisit and
recorded there.

One break is explained rather than fixed. 30/360 is not additive. QuantLib times
the first coupon as (last coupon to next coupon) minus (last coupon to
settlement). That treats a settlement on the 31st as the 31st when it ends a
period and as the 30th when it starts one. SIFMA counts DSC from settlement.
Summing QuantLib's own day counter from settlement reproduces Meridian's price
exactly, so the three generated bonds settling on a 31st are counted as explained.

### 2.5 What the validation could not see

QuantLib discounts to *payment* dates, and the street convention discounts to
*nominal* coupon dates. When a coupon falls on a weekend the two differ by a day
or two of discounting. That is a convention, not an error, so the comparison sets
QuantLib to unadjusted payments.

---

## 3. A simulation that history cannot reshuffle

Fixing the calendars broke 19 tests in Days 3 to 9. The fix was right; the tests
exposed a design fault.

The synthetic market draws one random shock per business day. When 9 January 2025
became a holiday (President Carter's day of mourning), every draw after it moved
along by one. Every price, trade, return, risk number and compliance result from
Days 2 to 9 changed with it.

The fix separates two calendars that every market has:

- the **scheduled** calendar: the rules, as published in advance;
- the **actual** calendar: the scheduled one, less the special openings, plus the
  special closures.

Settlement, valuation and data quality use the actual calendar. The simulation
steps through the scheduled one, because a state funeral closes the market but not
the world: news keeps arriving, and the next open prices all of it.
`calendar.scheduled()` gives the view.

With it, 18 of the 19 failures return to their original values bit for bit. The
nineteenth is the $2 change from the street-convention fix, which is correct.

---

## 4. Curves from instruments on their real dates

`bootstrap_par_curve` works on a grid of year fractions. That is the right
abstraction for a constant-maturity series like the Treasury's par curve. A desk's
curve is different: it is built from *instruments*, and each instrument's dates
follow a convention.

| Convention | SOFR OIS |
| --- | --- |
| Spot lag | T+2 business days |
| Calendar | US government securities (SIFMA) |
| Roll | modified following, periods counted back from maturity |
| Fixed leg | annual, ACT/360 |
| Floating leg | daily SOFR compounded, paid with the fixed leg |
| Payment lag | 2 business days for a cleared swap; 0 in the textbook form |
| Curve clock | ACT/365F from the valuation date |

The floating leg of an OIS telescopes. Compounding the overnight rate from the
start of a period to its end gives `DF(start) / DF(end)` on the curve that
forecasts it. The par rate of a swap is therefore a ratio of discount factors, and
each pillar is a one-dimensional solve.

![A SOFR curve from twenty swaps](../images/sofr-curve.png)

Twenty instruments, from one week to fifty years, each reprice to their quote
within 1e-10 basis points. Built by QuantLib's `PiecewiseLogLinearDiscount` with
`OISRateHelper`, the same strip agrees:

- **pillar dates:** identical, day for day;
- **discount factors:** within 2.4e-13, at every pillar and every 13 days between;
- **payment lag:** both with no lag and with the cleared two-day lag.

The quotes are **illustrative**. Cleared SOFR swap quotes are not free to
publish. They are built from the real Treasury par curve of 30 September 2026 plus
typical swap spreads, which have been negative at the long end since 2015. The
curve therefore has a realistic level and shape, and nothing in the validation
depends on the quotes being real.

### 4.1 Four interpolators, one set of quotes

Every interpolator below reprices every instrument exactly. They differ only in
what they assume between pillars, and the instantaneous forward curve is where
that shows.

![Four interpolators](../images/interpolation-forwards.png)

| Method | Forward curve | Local? |
| --- | --- | --- |
| Linear on zero rates | kinks at every pillar; the forward jumps | yes |
| Log-linear on discount factors | flat between pillars, a staircase | yes |
| Monotone cubic on zero rates | smooth zeros, but the forward still kinks | no |
| **Monotone convex** (Hagan-West) | continuous and positive | nearly |

Hagan and West (2006) list what a curve builder should demand of an interpolator:

1. it reprices the inputs;
2. the forward curve is continuous;
3. it is local;
4. the forwards stay positive;
5. it is monotone where the inputs are.

Their *monotone convex* method meets all five. Node forwards are weighted averages
of neighbouring discrete forwards. Within each interval a correction that
integrates to zero is chosen from four quadratic shapes, according to the signs at
its ends. The integral is known in closed form, so discount factors need no
quadrature. The US Treasury has used the method for its official par curve since
December 2021.

Property tests (Hypothesis) check these properties on thousands of generated
curves. They found two degenerate cases in the first implementation, both now
fixed:

- **A node forward exactly equal to the discrete forward.** The monotone shapes
  divide by zero there, or collapse into a jump. The plain quadratic is the only
  continuous choice with zero integral, so the axes take it.
- **A difference that should be zero but arrives as 1e-17 of rounding.** It
  produced a transition 1e-15 wide, which is a jump in all but name. Differences
  within 1e-9 (relative) of the discrete forward now count as zero.

Hagan-West's *positivity collar* matters in practice. Of 3,000 generated curves
with positive discrete forwards, 1,212 produced negative instantaneous forwards
without it, and none with it.

QuantLib's `ConvexMonotone` is a variant, not the same method:

- **The blend.** By default QuantLib mixes Hagan-West with a quadratic
  (quadraticity 0.3, monotonicity 0.7). On this strip its forwards sit within
  8.1 bp of pure Hagan-West, and 1.1 bp on average.
- **Convergence.** With quadraticity set to zero, pure Hagan-West, QuantLib's
  iterative bootstrap did not converge in 99 iterations. Meridian's converges in
  six passes.

### 4.2 Non-local interpolators need an iterative bootstrap

A sequential bootstrap solves the pillars in order and never returns to one. That
is exact only for local interpolators. Under monotone cubic or monotone convex, a
later pillar moves the curve before it.

Version 1.0.0's par bootstrap left monotone cubic curves up to **0.86 bp** off
their own quotes. Both bootstraps now repeat the pass until no pillar moves by more
than 1e-13, and every method reprices to 1e-14.

### 4.3 Locality, the Jacobian and risk in the hedge instruments

Locality has a practical meaning. It decides whether the hedge for a 5-year risk
is a 5-year swap, or a 5-year swap plus small amounts of everything else.

![Locality](../images/interpolation-locality.png)

The Jacobian makes that exact. Each quote is bumped by a basis point, the curve
rebuilt, and the zero curve's response read at every pillar.

- **Log-linear:** everything sits on or below the diagonal, because a quote cannot
  move the curve before its own maturity.
- **Monotone convex:** it leaks a little upwards. The largest effect of a quote on
  an earlier pillar is small but not zero.

![The Jacobian](../images/curve-jacobian.png)

Risk is reported in the instruments that hedge it. The book is four swaps at
maturities *between* the quoted pillars (8, 13 and 27 years, and 42 months). Its
DV01 spreads across the neighbouring buckets. The buckets sum to the parallel
DV01, and dividing each bucket by the DV01 of the quoted swap gives the notional
that flattens it.

![Bucketed DV01](../images/bucketed-dv01.png)

---

## 5. Thirty-six years of the Treasury curve

Two public-domain datasets now ship with the package, so every chart and test runs
offline. `python -m meridian.devtools.fetch_rates` rebuilds them from source.

- **The US Treasury's daily par yield curve.** 9,194 days from 2 January 1990 to
  30 September 2026, at constant maturities from 1 month to 30 years, where
  published:
  - the 1-month bill column starts in 2001;
  - the 20-year returns in 1993;
  - the 30-year paused from 2002 to 2006.
- **The Gurkaynak-Sack-Wright curve** (Federal Reserve Board, FEDS 2006-28). The six
  daily parameters of a Svensson curve fitted to off-the-run Treasuries, with the
  zero yields they imply: 9,171 days. On Good Friday 2008 the Fed published
  parameters but no yields, and a test pins that date.

![The Treasury curve since 1990](../images/treasury-history.png)

![The yield curve as a landscape](../images/treasury-surface.png)

### 5.1 Level, slope and curvature

Litterman and Scheinkman (1991) found that three factors explain nearly all of the
variation in Treasury returns. Meridian's PCA of 9,189 daily changes in par yields
(3 months to 10 years) reproduces the finding:

| Factor | Variance explained | Volatility |
| --- | ---: | ---: |
| Level | 79.4% | 215 bp a year |
| Slope | 12.7% | 86 bp a year |
| Curvature | 4.1% | 49 bp a year |
| **First three** | **96.2%** | |

Eigenvectors have no sign of their own, so each is oriented to read as its name:

- **level:** positive on average;
- **slope:** rising from the short end to the long end;
- **curvature:** positive in the belly against the wings.

Without the orientation, a chart of the history would flip sign at random.

![Level, slope and curvature](../images/curve-pca.png)

In rolling two-year windows the level factor's share is not constant. It fell to
about two-thirds in the 2008 crisis, when the Federal Reserve cut the short end to
zero while the long end moved on its own. It dipped below 80 per cent around 2000
and again from 2019 to 2022. Those are the years a duration hedge alone would have
left the most risk behind.

![The factors through time](../images/curve-pca-history.png)

### 5.2 Nelson-Siegel and Svensson, beside the Fed's own fit

A parametric curve describes the whole term structure in four or six numbers:

- **level:** what the curve tends to at long maturities;
- **slope:** the short end sits at level plus slope;
- **one or two humps.**

Meridian fits it to **par yields**, the quoted quantity, in two stages:

1. a grid over the decay parameters, with the betas by linear least squares;
2. a bounded trust-region refinement.

The Svensson fit is notorious for local minima, and the grid is what makes it
repeatable. Two checks keep it honest:

1. **The formula.** From the Fed's published parameters, Meridian's Svensson formula
   reproduces every published GSW yield on all 9,171 days to within 0.034 bp.
2. **The fit.** Meridian's fit to the Treasury's own par yields is set beside the
   Fed's fit of the same market on the same day.

![Nelson-Siegel and Svensson on real curves](../images/nss-fits.png)

| Day | Nelson-Siegel RMSE | Svensson RMSE |
| --- | ---: | ---: |
| 19 May 2000, inverted before the 2001 recession | 13.0 bp | 10.2 bp |
| 31 December 2008, after Lehman | 5.6 bp | 4.2 bp |
| 28 August 2019, the 2019 inversion | 2.2 bp | 0.9 bp |
| 25 September 2026 | 8.2 bp | 3.3 bp |

Fitted every quarter since 1990, each fit started from the one before, the two
curves differ by a median of:

- **2.9 bp** in the 2-year zero rate;
- **5.9 bp** in the 10-year;
- **10.5 bp** in the 30-year.

That gap is two fits of different bonds, not an error in either. The Treasury's
curve includes bills and on-the-run issues; the Fed's excludes both. The gap widens
when on-the-run premiums do: in the late 1990s, and in the 2008 crisis.

![Our fit against the Fed's](../images/nss-vs-gsw.png)

### 5.3 A bug the fit exposed

The first chart of fitted par yields was a sawtooth. Par yields at maturities
between coupon dates (0.8 years, say) ignored the accrued interest of the short
first period. A bond priced at par *clean* satisfies

$$\frac{c}{f}\Big(\sum_i DF(t_i) - a\Big) + DF(T) = 1,$$

where *a* is the elapsed share of the first period. `YieldCurve.par_rate` had the
same omission. It never touched a bootstrap, whose tenors fall on coupon dates,
but every par curve drawn between them was wrong. Both are fixed.

---

## 6. UK gilts go ex-dividend

A conventional gilt pays semi-annually and accrues ACT/ACT (ICMA). For the **seven
business days** before each coupon it trades *ex-dividend*: the buyer settles
without that coupon, which stays with the seller. The rules follow the UK Debt
Management Office's formulae and QuantLib's `exCouponPeriod`:

- the ex-dividend date is counted back from the **nominal** coupon date, not from
  the day it is paid when that is later;
- in the ex period, accrued interest is **negative**: the buyer is owed interest for
  the days to a coupon it will not receive;
- the price from a yield leaves the kept coupon out.

![A gilt goes ex-dividend](../images/gilt-ex-dividend.png)

On the 4 5/8% Treasury Gilt 2034:

- 21 January 2026 is the last day cum-dividend, with accrued interest of +2.19;
- on 22 January it is -0.11;
- the dirty price drops by about a coupon;
- the clean price barely moves.

Across nine months of settlement dates, 14 of them ex-dividend, Meridian matches
QuantLib to 2.3e-13 in price.

---

## References

- P. S. Hagan and G. West, "Interpolation Methods for Curve Construction", *Applied
  Mathematical Finance* 13(2), 2006; and "Methods for Constructing a Yield Curve",
  *Wilmott Magazine*, May 2008.
- R. Litterman and J. Scheinkman, "Common Factors Affecting Bond Returns", *Journal of
  Fixed Income* 1(1), 1991.
- R. Gurkaynak, B. Sack and J. Wright, "The U.S. Treasury Yield Curve: 1961 to the
  Present", *Journal of Monetary Economics* 54(8), 2007 (FEDS 2006-28).
- C. Nelson and A. Siegel, "Parsimonious Modeling of Yield Curves", *Journal of
  Business* 60(4), 1987; L. Svensson, "Estimating and Interpreting Forward Interest
  Rates", NBER Working Paper 4871, 1994.
- J. Meeus, *Astronomical Algorithms*, 2nd edition, Willmann-Bell, 1998, chapter 27.
- SIFMA, *Standard Securities Calculation Methods*; ISDA, *2006 ISDA Definitions*,
  section 4.16.
- UK Debt Management Office, *Formulae for Calculating Gilt Prices from Yields*.
- US Department of the Treasury, *Daily Treasury Par Yield Curve Rates*, and its note
  on the monotone convex methodology (December 2021).
