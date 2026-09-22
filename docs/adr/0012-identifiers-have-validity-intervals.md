# 12. Identifiers are mapped to instruments with validity intervals

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Day 1 stored identifiers as columns on the instrument, which answers "what is this
instrument's ISIN today". It cannot answer "which instrument did this ticker mean on
this date", and that is the question every historical file asks. Tickers change
(Facebook's `FB` became `META` in June 2022) and are reused by unrelated companies;
ISINs change when a company redomiciles. A lookup without a date resolves an old
trade to whoever holds the identifier now.

## Decision

- A separate `identifier_xref` table maps (scheme, value) to an instrument over a
  half-open interval `[valid_from, valid_to)`. Every lookup takes a date.
- Two ambiguities are refused when a mapping is added: one identifier pointing at two
  instruments over overlapping dates, and one instrument holding two values of the
  same scheme at once.
- Check-digit schemes (ISIN, CUSIP, SEDOL, FIGI, LEI) are validated on entry.
- A symbol change is applied as a corporate action: the old ticker closes on the
  ex-date and the new one opens.
- The table has no foreign key to `instruments`. It must remember identifiers of
  securities that have left the book - a delisted company's ticker is exactly the one
  most likely to be reused.

## Consequences

- Historical files resolve correctly, and reuse is reported (`CrossReference.reused`)
  so an operator can see which identifiers are dangerous to resolve without a date.
- The identifier columns on `instruments` remain as the current snapshot for
  convenience; the cross-reference is the source of truth for anything dated.
- Without the foreign key, an orphan mapping is possible. That is the intended
  trade-off, and the xref is validated as a whole in memory before it is saved.
