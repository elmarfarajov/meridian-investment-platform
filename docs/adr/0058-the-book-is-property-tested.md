# 58. The book of record is property-tested

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Example tests check the histories someone thought to write. The ledger, the lots and
the wash sale tracker interact in ways that grow with the number of trades, relief
methods and currencies, and the interesting failures sit in combinations nobody writes
by hand.

## Decision

`tests/accounting/test_book_invariants.py` lets Hypothesis write the histories: two
currencies, FIFO, LIFO and HIFO, and losses bought back inside the window. Every
history must satisfy these invariants:

- the trial balance is zero;
- the investment sub-ledger equals the open lots at historical cost, per instrument;
- the quantities held reconcile to the trades;
- disallowed losses equal the basis carried in replacement lots, open or closed;
- no replacement share is used twice;
- no holding period starts after its lot was opened.

## Consequences

- Two bugs were found and fixed:
  - shares closed by one sale could replace each other, and the disallowed loss
    vanished;
  - an intraday round trip was refused.
- Each invariant failure Hypothesis shrinks to a minimal history also becomes a plain
  regression test, so the property suite can stay small and fast (60 examples per run).
