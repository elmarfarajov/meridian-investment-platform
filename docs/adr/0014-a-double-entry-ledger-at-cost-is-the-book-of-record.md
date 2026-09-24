# 14. A double-entry ledger at cost is the book of record

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

A portfolio system needs one place that is right. Positions, cash, income, realised
gains and fees can each be kept in its own table, but then nothing guarantees they
agree with each other, and the first reconciliation with a custodian or an auditor
becomes an investigation into which table is wrong.

Market value changes every day. If it is posted into the ledger, every evening
produces a revaluation entry that the next evening reverses, the ledger grows with
numbers nobody paid or received, and "what did we pay for this?" and "what is it
worth?" become the same account.

## Decision

- Every economic event is a **balanced double-entry journal entry**. A debit is
  positive and a credit negative, so an entry balances when it sums to zero and a
  trial balance is a sum.
- Every posting carries its **local amount and its base-currency amount** at the
  day's rate. An entry must balance in base currency always, and in each local
  currency unless it is a genuine currency exchange. A currency gain is a base-only
  posting.
- The chart of accounts is numbered by class (1xxx assets, 2xxx liabilities, 3xxx
  capital, 4xxx income, 5xxx expenses) and holds only what was paid, received, owed
  and earned. **Investments are carried at cost.** Market value is a valuation of the
  ledger, computed each day from it, never posted into it.
- Trades are recorded on **trade date** against a payable or receivable, which
  settlement clears into cash, so the ledger holds both views of cash at once.
- Entries are immutable; the ledger is append-only.

## Consequences

- The trial balance must balance, and it is checked: by a property test over
  arbitrary sequences of multi-currency entries, on every month-end of the
  demonstration history, and as a control before the accounting run writes anything.
- The investment sub-ledger ties to the open lots at historical cost instrument by
  instrument - a second control. Writing it found that the entitlement rules round a
  split's per-share cost to 1e-10, which left the lots 7e-8 dollars away from the
  ledger; the engine now rescales exactly.
- The same trial balance is computed in SQL (one `GROUP BY` over the postings) and
  held equal, account by account, to the in-memory ledger on SQLite and PostgreSQL.
- Unrealised gain has no account. Reports that need it read the valuation, which
  splits it into price and currency per lot (ADR 0017).
