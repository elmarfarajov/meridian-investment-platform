# Fixed income mathematics as implemented in Meridian

This note sets out the mathematics behind `meridian.analytics`, the conventions
chosen where the market offers more than one, and the properties the test suite
uses to verify the implementation. It is written to be read alongside the code in
[`src/meridian/analytics`](../../src/meridian/analytics) and
[`src/meridian/core`](../../src/meridian/core).

---

## 1. Discounting

The present value of one unit paid in *t* years at rate *r* depends on the
compounding convention the rate is quoted on:

| Convention | Discount factor |
| --- | --- |
| Simple | $1 / (1 + rt)$ |
| Compounded *m* times a year | $(1 + r/m)^{-mt}$ |
| Continuous | $e^{-rt}$ |

These are not cosmetic alternatives. At 5% over ten years the discount factor
ranges from 0.6667 under simple interest to 0.6065 under continuous compounding -
a difference of six cents in the dollar, or six hundred thousand on a hundred
million.

A rate is restated from one convention to another by going through the discount
factor, never by a shortcut:

$$r_{\text{target}} = f^{-1}\big(d(r_{\text{source}}, t)\big)$$

which is what `convert_rate` does. The test suite asserts the round trip for
arbitrary rates and horizons using Hypothesis, because a conversion that is not
exactly invertible will accumulate error wherever rates cross a boundary.

**Implementation:** [`core/compounding.py`](../../src/meridian/core/compounding.py)

---

## 2. The yield curve

### 2.1 Three curves, one set of quotes

The market quotes **par yields**: the coupon a bond of that maturity would need in
order to trade at 100. Valuation needs **zero rates**: the rate applying to a
single payment at one date. Anything forward-looking needs **forward rates**: the
rate the curve implies between two future dates.

These are three views of the same information, and confusing them is a classic
source of misvaluation. When the curve slopes upward, at any maturity

$$r_{\text{par}} < r_{\text{zero}} < r_{\text{forward}}$$

because the par yield is an average over all the coupon dates, the zero rate
applies only at the end, and the forward must exceed the zero rate to pull that
average up. The relationship inverts when the curve slopes downward. The
[curve chart](../images/yield-curve.png) shows all three from one set of quotes.

### 2.2 Bootstrapping

A par bond of maturity *T* with coupon *c* paid *m* times a year satisfies

$$1 = \frac{c}{m}\sum_{i=1}^{n} d(t_i) + d(T)$$

Given par yields at increasing maturities, the discount factors are solved one
instrument at a time: every coupon date except the last falls on a part of the
curve already built, so each step has exactly one unknown. That step is a small
root-find, which is why the bootstrapper sits on top of the solver.

Two details matter:

- **The short end is a deposit.** Inside the first coupon period there is no coupon
  to pay, so the quote is a money-market rate on a simple basis, $d = 1/(1+rt)$.
  Treating it as a coupon bond produces a rate that is wrong by a factor of
  roughly *m*, which is a large and easily missed error.
- **Coupon dates are counted back from maturity**, so any stub lands at the front
  where it belongs.

The decisive test is the round trip: a curve bootstrapped from par yields must
return exactly those par yields when asked. The suite asserts this for all ten
tenors to within $10^{-10}$.

### 2.3 Interpolation

Between pillars the curve has to be interpolated, and the choice is a modelling
decision — see [ADR 0007](../adr/0007-log-linear-interpolation-on-discount-factors.md).
Log-linear interpolation on discount factors is equivalent to assuming a constant
forward rate between pillars:

$$\ln d(t) = \ln d(t_i) + \frac{t - t_i}{t_{i+1} - t_i}\big(\ln d(t_{i+1}) - \ln d(t_i)\big)$$

The [interpolation chart](../images/curve-interpolation.png) shows why: the three
methods agree at every quoted pillar and disagree everywhere else, most visibly in
the forward curve, where linear interpolation on rates produces a sawtooth.

**Implementation:** [`analytics/curves.py`](../../src/meridian/analytics/curves.py),
[`core/interpolation.py`](../../src/meridian/core/interpolation.py)

---

## 3. Bond pricing

### 3.1 Clean, dirty and accrued

Bonds are quoted **clean** and settle **dirty**:

$$P_{\text{dirty}} = P_{\text{clean}} + AI$$

Accrued interest compensates the seller for the part of the coupon period they
held the bond:

$$AI = F \cdot c \cdot \tau(t_{\text{start}}, t_{\text{settle}})$$

where $\tau$ is the year fraction on the instrument's own day-count convention.
Forgetting the accrued understates a valuation by up to a full coupon, and it does
so in a way that looks plausible. The [accrual chart](../images/accrued-interest.png)
shows the sawtooth it produces through time.

### 3.2 Yield to maturity

The yield is the single rate that reproduces the observed price:

$$P_{\text{dirty}} = \sum_{i=1}^{n} \frac{CF_i}{(1 + y/m)^{w + i - 1}}$$

where $w$ is the unexpired fraction of the current coupon period. Measuring time in
**coupon periods** rather than in ACT/365 years is the ISMA street convention, and
it is what makes a bond priced at its own coupon come out at exactly 100 on a
coupon date rather than at 99.97. The test suite asserts that identity for annual,
semi-annual and quarterly bonds.

There is no closed form, so *y* is solved numerically (§5). Note what the yield
assumes: that every coupon is reinvested at *y* itself. It is a quoting convention,
not a forecast of return.

### 3.3 Pricing off a curve, and the spread

Discounting at a single yield is not the same as discounting each cash flow at its
own point on the curve:

$$P = \sum_i CF_i \cdot d(t_i)$$

The difference between the two, expressed as the parallel shift *z* of the zero
curve that reproduces the market price, is the **z-spread**:

$$P_{\text{dirty}} = \sum_i CF_i \cdot e^{-(r(t_i) + z)\,t_i}$$

That is the bond's compensation for credit, liquidity and optionality over the
risk-free curve, and unlike a yield spread it does not depend on the shape of the
curve between the two bonds being compared.

**Implementation:** [`analytics/bonds.py`](../../src/meridian/analytics/bonds.py)

---

## 4. Interest rate risk

### 4.1 Duration and convexity

Macaulay duration is the present-value-weighted average time to the cash flows:

$$D_{\text{Mac}} = \frac{1}{P}\sum_i t_i \cdot \frac{CF_i}{(1+y/m)^{m t_i}}$$

Modified duration converts that into a price sensitivity:

$$D_{\text{mod}} = \frac{D_{\text{Mac}}}{1 + y/m}, \qquad \frac{\Delta P}{P} \approx -D_{\text{mod}}\,\Delta y$$

Convexity is the second-order term:

$$C = \frac{1}{P}\sum_i \frac{t_i(t_i + 1/m)\,CF_i}{(1+y/m)^{m t_i + 2}}, \qquad
\frac{\Delta P}{P} \approx -D_{\text{mod}}\Delta y + \tfrac{1}{2}C(\Delta y)^2$$

Because the price-yield relationship is convex, the tangent lies **below** the
curve on both sides. Duration alone therefore always overstates the loss from a
rise in yields and understates the gain from a fall. On the ten-year 4% bond used
throughout the documentation, a 300 basis point move is mis-estimated by more than
two points of face value by duration alone; adding convexity reduces the error by
roughly an order of magnitude. That is the entire content of the
[price-yield chart](../images/price-yield.png), and the suite asserts both the sign
and the improvement.

Three properties the tests use as checks:

- a zero-coupon bond's Macaulay duration equals its maturity, exactly;
- a lower coupon lengthens duration, because more of the value sits at the end;
- DV01 $\approx D_{\text{mod}} \cdot P_{\text{dirty}} \cdot 10^{-4}$.

### 4.2 Key rate durations

A parallel shift is a convenient fiction; curves twist. Key rate duration measures
the sensitivity to a bump at one pillar with the others held fixed:

$$KRD_j = -\frac{1}{P}\frac{\partial P}{\partial r_j}$$

The sum of the key rate durations approximates the modified duration, and their
distribution says *where* the risk sits — for a bullet bond, overwhelmingly at the
pillars adjacent to its maturity. The [key rate chart](../images/key-rate-durations.png)
shows the concentration, and the suite asserts both the sum and the concentration.

---

## 5. Numerical method

Yield to maturity, internal rate of return and the bootstrap are all the same
problem: find the rate at which a pricing function returns an observed value.

**Newton-Raphson** converges quadratically when it works:

$$x_{k+1} = x_k - \frac{f(x_k)}{f'(x_k)}$$

and diverges when the derivative is small or the function is not locally well
behaved — a deeply discounted bond, a cash flow stream that changes sign more than
once. **Bisection** cannot diverge but converges linearly.

The solver here is **safeguarded Newton**: a Newton step is accepted only while the
iterate stays inside a bracket known to contain a root, and is replaced by a
bisection step when it would leave. This gives Newton's speed with bisection's
guarantee. Failure raises `ConvergenceError` rather than returning the last
iterate, because a yield that silently did not converge is worse than no yield at
all.

**Implementation:** [`analytics/solvers.py`](../../src/meridian/analytics/solvers.py)

---

## 6. Day counts and schedules

The year fraction $\tau$ that appears in every accrual is not one number. Meridian
implements nine conventions; on a six-month period on ten million at 5%, the spread
between the highest and lowest is over five thousand currency units — see the
[day-count chart](../images/day-counts.png).

Three conventions need context beyond two dates:

- **ACT/ACT ICMA** divides by the length of the coupon period the dates sit inside,
  times the frequency, so a semi-annual period is exactly 0.5 whatever its actual
  length;
- **BUS/252** counts business days, so it needs a trading calendar;
- **30E/360 ISDA** treats a February month-end differently when it is the maturity.

Schedules are generated **backwards from maturity**, because the maturity is the
contractually fixed date and the irregular period belongs at the other end. The
end-of-month rule is sticky, stubs can be placed at either end, and payment dates
move onto business days while accrual dates stay put — which is what most bonds do,
and precisely the difference that produces a one-day interest discrepancy between
two systems.

**Implementation:** [`core/daycount.py`](../../src/meridian/core/daycount.py),
[`core/schedules.py`](../../src/meridian/core/schedules.py)

---

## 7. What is deliberately not here

- **Optionality.** Callable and putable bonds need an interest rate model and a
  lattice; the OAS that results is a different calculation from the z-spread.
- **Credit.** Default probability, recovery and survival curves.
- **Inflation linkage**, index ratios and real yields.
- **Multi-curve discounting.** Since 2008 a derivative is discounted on the
  collateral curve rather than on its own forecast curve; the structure here
  supports it (a curve is an object, not a global) but the calibration is not
  implemented.

Each is a deliberate boundary rather than an oversight, and each would be its own
module.

---

## References

The implementations follow standard market practice as described in:

- Fabozzi, *Bond Markets, Analysis and Strategies* — duration, convexity, pricing
- Hull, *Options, Futures and Other Derivatives* — compounding, curve construction
- Tuckman & Serrat, *Fixed Income Securities* — bootstrapping, key rate durations
- ISDA 2006 Definitions, Section 4.16 — day-count conventions
- ICMA Rule 251 — accrued interest and ACT/ACT ICMA
- Fritsch & Carlson (1980), *Monotone Piecewise Cubic Interpolation*, SIAM J. Numer. Anal.
- Fowler, *Patterns of Enterprise Application Architecture* — the allocation algorithm
