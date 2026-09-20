# 8. Decimal in the ledger, float in the analytics

- **Status:** Accepted
- **Date:** 2026-09-20

## Context

[ADR 0002](0002-decimal-money-with-currency-tagging.md) established that money is a
`Decimal`. The analytics layer added in this iteration - root finding, curve
bootstrapping, duration and convexity - puts that rule under pressure.

Yield to maturity has no closed form. It is solved iteratively, and every iteration
evaluates an exponential. `Decimal` supports exponentiation, but at arbitrary
precision it is one to two orders of magnitude slower than `float`, and a curve
bootstrap performs thousands of evaluations. A portfolio-level risk calculation
would perform millions.

The precision argument does not favour `Decimal` here either. A discount factor is
the output of a transcendental function; it is irrational, and rounding it to two
decimal places would be meaningless. The number that matters is not the discount
factor but the cash amount it eventually produces, and that is a single
multiplication away from the ledger.

Mixing the two silently is the real danger: a `Decimal` multiplied by a `float`
raises in Python, which is a blessing, but a value that quietly becomes a float and
then gets posted as cash is exactly the bug ADR 0002 exists to prevent.

## Decision

The boundary is the package boundary.

- `meridian.core` and `meridian.domain` are `Decimal`. Money, quantities, prices as
  booked, accrued interest as posted.
- `meridian.analytics` is `float`. Discount factors, zero rates, durations,
  convexities, solver iterates and everything computed from them.
- Values crossing from analytics into the ledger are converted explicitly, at the
  point of crossing, and rounded to the currency's precision there - never earlier,
  so the rounding happens once. `CashFlow.as_money()` is that conversion for bond
  cash flows.
- Nothing in `analytics` imports `Money`, and nothing in `domain` imports a solver.

The rule is stated in the docstring of `meridian.analytics` so it is visible to
anyone adding to the package.

## Consequences

- Pricing is fast enough to run a curve bootstrap inside a test suite, and the
  suite stays under twenty seconds.
- Reconciliation is unaffected: the ledger never sees a float.
- The boundary has to be respected by hand; there is no type-level enforcement that
  a float has not leaked into a posting. The mitigation is that `Money` only
  accepts `Decimal`, `int` or `str` through `to_decimal`, and converting a float
  goes through `repr` so the value is at least the one that was printed.
- Analytics results are reproducible to roughly fifteen significant figures rather
  than exactly. Tests assert relationships and tolerances rather than exact
  equality - which is the right way to test numerical code in any case.
