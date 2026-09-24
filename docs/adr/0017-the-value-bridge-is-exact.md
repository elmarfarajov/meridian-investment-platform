# 17. The value bridge is exact: local at the opening rate, currency on the closing local value

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

A client asks why their portfolio is worth less than last quarter. The honest answer
separates money they moved from money the portfolio earned, and within what it earned,
the market from the currency from the income from the costs. Most bridges end with an
"other" or "residual" line that absorbs whatever the method could not explain, and
that line is where errors hide.

For a foreign holding the split between price and currency is a convention, because
the cross term - the price move times the rate move - belongs to neither.

## Decision

- For one holding over one day, with quantity `Q`, price `P`, scale `s` and rate `X`:

  ```
  price    = (Qa P1 - Q0 P0) s X0  +  sum over trades (dQ P1 s - consideration) X1
  currency =  Qa P1 s (X1 - X0)
  ```

  where `Qa` is the quantity after corporate actions and before the day's trades. The
  local move is measured at the **opening** rate and the currency move on the
  **closing** local value, so the cross term falls into currency.
- The same identity is written for accrued interest (currency on the opening balance,
  the rest income) and for every cash-like balance (currency on the opening balance;
  flows, income and costs at the closing rate; conversions at their own rates).
- Transfers in kind are flows at market value. Dividends are income on the ex-date;
  withholding that cannot be reclaimed is a cost.
- The bridge carries a **residual**, and the residual must be zero.

## Consequences

- Measuring price on `Qa` means a 4-for-1 split is not a 75% loss and a dividend's
  ex-date drop is offset by the income it creates - both tested.
- A property test builds random multi-currency books - equities, a bond with accrued
  interest, conversions, fees, sales and a dividend over random price and FX paths -
  and requires every day's residual to be zero. On the demonstration history the
  largest daily residual over 620 days is 1.8e-21 dollars, the last digit of a
  28-digit decimal context.
- The other ordering (local at the closing rate) would move the cross term into price.
  Either is defensible; this one is written down so every report uses the same one,
  and the split of realised and unrealised gains uses the same convention so a gain
  does not change character when it is realised.
