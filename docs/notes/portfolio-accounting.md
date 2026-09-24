# Portfolio accounting: the book of record

Everything a portfolio reports - its value, its return, its tax, its compliance - is
computed from the book. If the book is wrong, everything downstream is wrong, and
usually in a way nobody notices until a custodian, an auditor or a client does. This
note describes how the book is kept.

**Implementation:** [`accounting/`](../../src/meridian/accounting) ·
**Decisions:** [ADR 0014](../adr/0014-a-double-entry-ledger-at-cost-is-the-book-of-record.md),
[ADR 0015](../adr/0015-the-book-is-a-replay-of-a-versioned-blotter.md)

---

## 1. Double entry, and one sign convention

Every event is a journal entry of two or more postings. **A debit is positive and a
credit is negative**, so an entry balances when its postings sum to zero and a trial
balance is a sum. Each posting carries two amounts: the amount in the currency it
happened in, and the same amount in the base currency at the rate of the day.

An entry must balance in base currency always, and in each local currency unless it is
a genuine currency exchange. A currency gain exists only in base currency, so it is a
posting with a local amount of zero.

## 2. The chart of accounts

| Code | Account | What sits in it |
| --- | --- | --- |
| 1000 | Cash | settled cash at the custodian, one balance per currency |
| 1100 | Investments at cost | open lots at book cost, commission included |
| 1150 | Accrued interest purchased | interest paid to a bond's seller, recovered from the next coupon |
| 1200 | Receivable for investments sold | sales traded but not settled |
| 1210 | Dividends receivable | dividends gone ex but not paid, net of withholding |
| 1230 | Withholding tax reclaimable | withholding above the treaty rate |
| 2000 | Payable for investments purchased | purchases traded but not settled |
| 3000 / 3100 | Contributed capital / transferred in kind | the client's money and securities |
| 4000 / 4010 | Realised gain, short / long term | the price part of a sale's gain |
| 4020 | Realised currency gain on investments | the currency part of a sale's gain |
| 4030 | Realised currency gain on settlement | rate moves between trade and settlement, and conversion spreads |
| 4100 / 4110 | Dividend / interest income | gross of withholding; interest net of accrued purchased |
| 5000 / 5100 / 5200 | Fees / withholding tax / transaction taxes | what left and did not come back |

There is no account for unrealised appreciation. The ledger is at cost; market value is
a valuation of it (see [valuation and the value bridge](valuation-and-the-value-bridge.md)).

## 3. Posting rules

| Event | Trade date (or ex-date) | Settlement (or pay) date |
| --- | --- | --- |
| Purchase | Dr investments, Cr payable | Dr payable, Cr cash; the rate move to base-only 4030 |
| Sale | Dr receivable; Cr investments at historical cost; Cr realised price gain (4000/4010) and currency gain (4020) | Dr cash, Cr receivable; rate move to 4030 |
| Dividend | Dr receivable (net), Dr reclaimable, Dr withholding, Cr dividend income | Dr cash, Cr receivable |
| Coupon | | Dr cash, Cr accrued interest purchased, Cr interest income |
| Deposit, withdrawal | Dr cash, Cr capital (and the reverse) | |
| Transfer in kind | Dr investments, Cr transferred in kind, at carried cost | |
| Conversion | | Dr cash (bought), Cr cash (sold); the spread to 4030 |

Commission and transaction taxes are capitalised into a purchase's cost and deducted
from a sale's proceeds, which is how the IRS and HMRC treat them. The value bridge
still shows them as costs.

A sale's base-currency gain is split exactly:

```
proceeds x rate_sale - cost x rate_open
    = (proceeds - cost) x rate_sale          -> 4000 / 4010
    + cost x (rate_sale - rate_open)          -> 4020
```

## 4. Trade date, settlement date, and the settlement cycle

The position moves on trade date; the cash on settlement date. Between the two the
book holds a payable or receivable, so it can answer both "what do we own?" and "what
does the custodian hold?".

The settlement cycle is a function of the market **and the date**. US equities moved
from T+2 to T+1 on 28 May 2024; the UK and EU remain on T+2 until October 2027;
treasuries settle T+1; spot FX T+2. Business days are counted on the joint calendar of
the exchange and the settlement currency - a dollar ETF listed in Amsterdam skips
Easter Monday although New York is open. The demonstration account was funded on
Tuesday 2 April 2024 rather than the Monday, because 1 April was Easter Monday in
London and in the eurozone.

## 5. Income

A dividend is earned on the ex-date by the shares held the night before, and paid
weeks later; in between it is a receivable. Cross-border dividends are paid net of
withholding. Germany withholds 26.375% against a 15% treaty rate and Switzerland 35%
against 15%; the difference is reclaimable, an asset, not an expense. Booking it as an
expense understates income - a common and expensive back-office error.

A bond buyer pays the seller's accrued interest and recovers it from the next coupon,
so interest income is the coupon less the accrued interest bought. The valuation
carries the full accrual every day.

## 6. Corporate actions

Actions come from the Day 2 corporate action feed and are applied on the ex-date,
before the day's trades. Splits and stock dividends rescale the lots (exactly - the
per-share cost is not rounded, so the lots still tie to the ledger) and pay cash in lieu
of a fraction as a realised disposal; spin-offs move basis to the child with the
holding period; cash mergers close the holding; stock mergers exchange it and tax the
boot under IRC 356/358.

## 7. The book is derived

The engine replays the blotter's transactions and the corporate actions in date order.
The book is a pure function of its inputs, so:

- replaying the blotter as known at a past moment reproduces the book as it stood then;
- a correction is a new version on the blotter, and its effect is the difference between
  two replays (ADR 0015);
- persisting the book replaces what was stored - the transactions are the only input.

Before anything is written the run checks its controls: the trial balance balances,
the investment sub-ledger ties to the open lots instrument by instrument, and cash
ties to the snapshots. A book that fails any of them writes nothing.

## 8. The demonstration

Two and a half years of the Aliyeva family's Global Equity Core account: 94
transactions, 190 journal entries, 23 realised lots, 31 open lots, 620 valuation days,
four currencies, a Treasury, a transfer in kind, two tax-loss harvests (one a wash
sale), a failed settlement and a corrected trade. `meridian book run` replays and
checks it; `meridian book trial-balance --from-db` reads the trial balance back out of
SQL after `run --persist`.
