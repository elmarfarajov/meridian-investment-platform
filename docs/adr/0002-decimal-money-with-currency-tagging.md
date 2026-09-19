# 2. Money is a tagged Decimal, never a float

- **Status:** Accepted
- **Date:** 2026-09-19

## Context

A platform that keeps a book of record has to reconcile to the cent across thousands of
transactions. Binary floating point cannot represent 0.1 exactly, so `0.1 + 0.2 != 0.3`,
and the error accumulates in exactly the place it is least acceptable: the cash ledger.

Floats are not the only hazard. Adding 100 USD to 100 EUR is a programming error that a
plain number cannot catch, and splitting a management fee three ways produces three
amounts that must add back to the original to the cent - a naive division does not.

The counter-argument is real: `Decimal` is slower than `float`, and analytics such as
covariance estimation or an optimiser have no use for exact decimal arithmetic.

## Decision

Every monetary amount, quantity, price and rate is a `decimal.Decimal`. Money is
represented by an immutable `Money` value object carrying an amount and a `Currency`;
arithmetic between different currencies raises `CurrencyMismatchError` rather than
producing a number. Rounding is `ROUND_HALF_EVEN` (banker's rounding), which is what
accounting systems and IEEE 754 use because it does not bias a long run of roundings
upwards. `Money.allocate` distributes an amount by weights using Martin Fowler's
algorithm, handing out the remainder pennies so the parts always sum back to the whole.

Database columns for amounts and quantities are fixed-scale `NUMERIC`, never floating
point, so the database cannot be the place where a cent goes missing.

Floats remain fine inside the analytics layers - a tracking error of 4.13% does not care
about the fifteenth digit - but they never cross back into the ledger.

## Consequences

- Reconciliation is exact, and the conservation property is enforced by a property-based
  test over arbitrary amounts and weights.
- Currency mixing fails loudly at the point of the mistake.
- Accounting code is slower than it would be with floats. This has not mattered; where it
  ever does, the fix is to work in integer minor units inside a hot loop, not to move the
  ledger to floats.
