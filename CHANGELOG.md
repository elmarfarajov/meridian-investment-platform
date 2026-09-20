# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.2.0
[0.1.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.1.0
