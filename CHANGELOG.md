# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-09-22

Day 2: market data. Prices with a memory of what was known and when, quality rules
that are measured rather than asserted, corporate actions applied to both the history
and the book, and one published price built from several disagreeing sources.

### Added

- **Bitemporal market data.** Every observation carries its value date and the
  moment the platform learned it; corrections are new records, never edits, so the
  series as known at any past moment can be rebuilt and the look-ahead in a restated
  history can be measured. The same "as known at" query is implemented in memory and
  in SQL and tested case for case against each other.
- **A synthetic market** with the stylised facts a quality rule has to survive:
  Student-t innovations, GARCH(1,1) volatility clustering, market and sector factors,
  one exchange calendar per instrument, and splits and dividends that move the quoted
  price. Its economic value is kept as ground truth for the adjustment code.
- **A fault injector** that damages clean data in the nine ways real feeds fail and
  records exactly where, so the rules can be scored.
- **Thirteen quality rules** across the five DAMA dimensions, with robust (median and
  MAD) statistics on event-adjusted returns net of a leave-one-out market proxy, an
  engine that scores each series and decides what may be published, and detection
  measured at 100% recall and 97% precision over 126 planted faults.
- **Corporate actions**: dividends, splits, stock dividends, spin-offs, rights, cash
  and stock mergers and symbol changes - with CRSP-style back-adjustment as a derived
  view, and entitlement rules that conserve cost basis, tack holding periods, pay
  cash in lieu of fractional shares and tax merger boot under IRC 356/358.
- **A golden copy** built by ranked consensus with price challenges recorded, and
  **FX history** with as-of lookup, cross rates and staleness limits.
- **A security master**: identifiers mapped to instruments over validity intervals
  and resolved by date, and golden records built field by field with lineage,
  conflicts and check-digit validation.
- **The end-of-day pricing run** - collect, record, validate, reconcile, publish -
  with five new tables, migration 0002, and batch upserts.
- **`meridian market`**: `rules`, `quality`, `price --persist`, `history --known-at`,
  `actions`, `adjust` and `xref --on`.
- **Thirteen charts** (thirty in the gallery), four methodology notes and ADRs 0009
  to 0013.

### Changed

- `PriceRepository` and `FxRateRepository` gained batch upserts, and observations are
  written with one insert rather than one merge per row: the demonstration load fell
  from 24 s to 2.8 s.
- The market proxy used by the outlier rules is exposed as `attach_market_proxy`.
- The demonstration book gains one clearly labelled synthetic instrument, so the
  history contains a 4-for-1 split to adjust for.

### Fixed

- A stale source can no longer outvote the source that moved. Two vendors resending
  yesterday's close agreed with each other, formed the median and excluded the one
  vendor with the right price; the worst golden-copy error fell from 254 bp to 13 bp
  once unchanged values were set aside on days when other sources moved.
- The synthetic market's GARCH parameters now satisfy the fourth-moment condition.
  With Student-t(4) innovations it failed, and a two-year sample came out 56% more
  volatile than specified.

## [0.2.0] - 2026-09-20

Day 1, continued: the financial mathematics the rest of the platform will be built on,
and the charts that argue for it.

### Added

- **Analytics layer.** Safeguarded Newton root finding with a bisection fallback;
  yield curves bootstrapped from par yields with the round trip asserted at every
  tenor; bond pricing, accrued interest, yield to maturity, Macaulay and modified
  duration, convexity, DV01, z-spread and key rate durations.
- **Payment schedules.** Rolled backwards from maturity, with the sticky end-of-month
  rule, four stub conventions, payment lags, and adjusted or unadjusted accrual.
- **Five more calendars** - the US bond market, Xetra, SIX, Tokyo and the weekend
  base - with holiday names, and `JointCalendar` for cross-border settlement.
- **Four more day-count conventions**: ACT/ACT ICMA, BUS/252, 30E/360 ISDA and
  ACT/365.25, including the context each one needs.
- **Compounding conventions** with exact conversion between them, and three
  interpolation methods including Fritsch-Carlson monotone cubic.
- **LEI validation** by ISO 7064 MOD 97-10, identifier scheme detection, and
  expected-check-digit reporting for near misses.
- **Eleven more charts**, an entity-relationship diagram generated from the live
  SQLAlchemy metadata, and one gallery definition behind the docs, the CLI and the
  tests.
- **`meridian rates` and `meridian charts`** command groups; `calendar matrix`,
  `calendar ladder` and named holidays.
- **Two methodology notes** - fixed income mathematics and calendar conventions -
  and ADRs 0006 to 0008.

### Changed

- Chart title blocks scale with the figure, so a tall multi-panel page and a single
  wide chart look the same.
- Repository queries return `Sequence` rather than `list`: a query result is a
  snapshot, not a collection to mutate.

## [0.1.0] - 2026-09-19

The foundation: the vocabulary every later module is written in.

### Added

- **Core value objects.** `Money` on `Decimal` with banker's rounding, currency tagging
  and a remainder-conserving `allocate`; 22 currencies with correct minor units; FX rates
  with inversion and pivot cross rates.
- **Security identifiers.** ISIN, CUSIP, SEDOL and FIGI with their real check-digit
  algorithms, CUSIP-to-ISIN conversion, and tests against published identifiers.
- **Trading calendars.** NYSE, LSE and TARGET generated from statutory rules, business-day
  conventions, T+n settlement arithmetic, and ACT/360, ACT/365F, 30/360 and ACT/ACT ISDA
  day counts.
- **Domain model.** Instruments (equity, fund, bond, cash), clients, households, accounts,
  portfolios with an investment policy, transactions with fixed sign conventions, and
  positions as tax lots with FIFO, LIFO, HIFO, average-cost and specific identification.
- **Persistence.** Typed SQLAlchemy 2.0 schema with fixed-scale `NUMERIC` columns,
  explicit domain-to-row mappers, repositories returning domain objects, a unit of work,
  and Alembic migrations with a drift check.
- **Visualisation.** A house chart style, and the exchange trading calendar chart showing
  the weekdays on which markets disagree.
- **CLI.** `meridian info`, `db init|seed|status`, `calendar list|holidays|settle|chart`
  and `security validate|to-isin`, with structured logging.
- **Demonstration book.** Twelve instruments across four currencies, a taxable account and
  a pension, and eight trades spanning short and long holding periods.
- **Project infrastructure.** CI running lint, format, types, the suite on Python 3.10 to
  3.12, and integration tests against PostgreSQL 16; architecture decision records
  0001-0005.

[0.3.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.3.0
[0.2.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.2.0
[0.1.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.1.0
