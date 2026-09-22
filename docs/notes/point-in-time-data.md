# Point-in-time data: what we knew, and when

Ask a portfolio system what a stock closed at on 14 May and it will answer. Ask it
what it *believed* the stock closed at on the morning of 15 May, and most systems
cannot answer at all — because when the vendor corrected the price, the old value was
overwritten.

That second question is the one that matters for audit, for reproducing a valuation,
and for any backtest whose results are supposed to mean something.

**Implementation:** [`marketdata/bitemporal.py`](../../src/meridian/marketdata/bitemporal.py),
[`persistence/marketdata_repositories.py`](../../src/meridian/persistence/marketdata_repositories.py) ·
**Decision:** [ADR 0009](../adr/0009-bitemporal-market-data.md)

---

## 1. Two dates, not one

Every market data record carries:

- a **value date** — the day the price describes;
- a **knowledge time** — the moment the platform learned it.

A correction is a new record with a later knowledge time, never an edit. Nothing is
ever updated in place and nothing is deleted, so the store is append-only and every
past state of knowledge survives.

The query that matters is *as known at*: for each value date, the latest record whose
knowledge time is on or before a given moment.

```python
store.as_known_at("US-AAPL:close", moment)          # in memory
unit_of_work.observations.as_known_at("US-AAPL", moment)   # the same answer in SQL
```

Both implementations are tested against the same cases, including a correction that
must not leak into the past and knowledge times given in another timezone.

---

## 2. What it looks like when a feed corrects itself

![What we knew, and when](../images/point-in-time.png)

The grey line is what a live system saw: eight of these prints were wrong, and each
was corrected one to three days later. The blue line is the history as it stands
today. Three dates arrived two days late and simply did not exist for anyone on the
evening they describe.

---

## 3. Look-ahead bias, measured

A backtest run on today's restated history uses the blue line. A strategy trading at
the time saw the grey one. The difference is information the backtest was not
entitled to:

```python
lookahead_error(store, key, known_at)   # per date, restated vs first print, in bp
```

This is not a small effect in practice. Restatements cluster exactly where a strategy
would have traded: around the days the data was hardest to get right. A backtest that
buys on a "dip" which was really a bad print, and sells at the corrected level, earns
a return nobody could have earned.

The same store also answers the audit question. A valuation from the 14th can be
reproduced with the prices as known on the 14th, and the difference from today's
numbers explained line by line, rather than argued about.

---

## 4. Loading history honestly

A historical load written at one knowledge time would say that nothing was known
before the load ran — true of the database, and useless. Meridian *backfills*: each
observation is stamped with the evening of its own value date, which is the honest
assumption for end-of-day data, and the load's run id records that it was a backfill
rather than a live capture.

```bash
meridian market price --persist                       # collect, validate, publish, record
meridian market history US-AAPL --known-at 2026-09-10 # the series as it stood that evening
meridian market history US-AAPL                       # as known now
```

Asking for a date before the instrument had any data returns nothing — correctly, and
with a message that says so rather than an empty table.

---

## 5. What it costs

One row per instrument, day, price type, source **and** knowledge time. At end-of-day
frequency, with three sources and a few hundred instruments, that is tens of
thousands of rows a year: nothing. Intraday data at the same fidelity would need
compaction, and the sensible boundary is to keep every *correction* but not every
resend of an unchanged value.

The published golden copy stays a single row per instrument and day, because
valuation wants one number. It is derived; the observations are the record of how it
was derived.
