# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.1.0
