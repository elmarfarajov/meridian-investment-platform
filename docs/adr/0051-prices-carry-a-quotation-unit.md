# 51. Prices carry a quotation unit, and cash is restated in it before it meets a price

- **Status:** Accepted
- **Date:** 2026-10-02

## Context

London quotes most shares in pence (GBX), Johannesburg in cents (ZAc), Tel Aviv in
agorot (ILA). Dividends, trades and books are kept in the currency. Day 2 set a
dividend against a price with no notion of either's unit. A GBP 0.198 dividend on a
1,950p share is a 1.02% payout, but against the price as it stood it read as 0.01%,
and the total-return history barely moved.

## Decision

- `core.currency.QuoteUnit` names the unit a price is quoted in: its currency and its
  divisor. GBX (also written GBp), ZAc, ILA and USX are registered. Any other code is
  its own currency at par.
- `marketdata.adjustments.in_price_units` restates a cash dividend in the price's unit
  before its factor is taken:
  - by the divisor, when the currencies match;
  - through an exchange rate otherwise.
  The exchange rate is required: a USD dividend on a GBX price with no rate raises
  rather than guessing.
- The quality engine reads the unit from the quotes themselves, so its event
  adjustment makes the same restatement.

## Consequences

- A pence share's adjusted history moves by its real payout, and a test pins the
  1.02%.
- Adjustment takes `price_unit` and `fx`. Callers that know neither keep the old
  behaviour, which is correct whenever the price and the dividend share a currency.
