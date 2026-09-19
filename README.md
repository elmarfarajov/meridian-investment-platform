# Meridian

**An institutional investment management platform: the book of record, the risk, and the reporting behind a multi-currency, multi-account client portfolio.**

[![CI](https://github.com/elmarfarajov/meridian-investment-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/elmarfarajov/meridian-investment-platform/actions/workflows/ci.yml)
[![Python 3.10 – 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-1B3A6B)](https://www.python.org/)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-1F8A80)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-6A4C93)](https://docs.astral.sh/ruff/)
[![License: MIT](https://img.shields.io/badge/license-MIT-4A5C75)](LICENSE)

Asset managers do not run on spreadsheets. They run on systems like BlackRock's Aladdin,
Charles River IMS and SimCorp Dimension: one place that holds every position and tax lot,
values it every night, attributes the return against a benchmark, decomposes the risk,
checks every proposed trade against the mandate, and produces the statement the client
reads. Meridian is a working implementation of that spine, built from first principles.

It is a portfolio engineering project, not a commercial product. The point is to show the
reasoning: why money is a `Decimal` and never a float, why tax lots have to be identified
rather than averaged, why an exchange calendar is generated from statutory rules rather
than loaded from a file that goes stale, and why a schema must be migrated rather than
recreated.

---

## The first thing the platform draws

Two markets that are open on different days are the reason a cross-border trade fails to
settle, a coupon lands a day late, or a portfolio is compared against a benchmark that did
not trade that day. Meridian generates its calendars from statutory rules - including
Easter by the Meeus/Jones/Butcher algorithm, US observed-holiday shifts and UK substitute
days - and can show you exactly which days disagree.

![Exchange trading calendars, 2026](docs/images/trading-calendar-2026.png)

```bash
meridian calendar chart --year 2026 --calendars XNYS,XLON,TARGET
meridian calendar settle 2026-12-24 --calendar XNYS --days 2
# XNYS  T+2: 2026-12-24 (Thursday) -> 2026-12-29 (Tuesday); 3 non-business days skipped
```

---

## Architecture

The package is layered so each concern is testable on its own, and so nothing above the
persistence layer knows which database is in use.

```
meridian
├── core          value objects: Money, Currency, FX, identifiers, calendars, day counts
├── domain        the business model: instruments, portfolios, accounts, positions, trades
├── persistence   SQLAlchemy 2.0 schema, explicit mappers, repositories, unit of work
├── viz           the house chart style; every module ships a visual, not only numbers
├── cli           a thin Typer layer over tested functions
└── seed          a hand-made demonstration book to run everything against
```

**Dependencies point inwards.** `core` imports nothing from the platform. `domain` imports
`core`. `persistence` maps `domain` to rows through explicit functions rather than
persisting the domain classes directly, so the schema can change for storage reasons
without loosening a domain invariant. Analytics code never imports SQLAlchemy.

---

## Engineering standards

| Concern | Decision |
| --- | --- |
| Money | `Decimal` end to end, banker's rounding, currency-tagged, no silent mixing. `Money.allocate` splits an amount so the parts always sum back to the whole. |
| Identifiers | ISIN, CUSIP, SEDOL and FIGI validated by their real check-digit algorithms, and tested against published identifiers for Apple, Microsoft, BAE, Bayer, Toyota and Roche. |
| Calendars | Generated from rules, not files. NYSE, LSE and TARGET, with business-day conventions and T+n settlement arithmetic. |
| Database | SQLite locally so a clone runs with no setup; the same suite runs against PostgreSQL 16 in CI. Fixed-scale `NUMERIC` columns, never floats. |
| Migrations | Alembic, with `alembic check` in CI failing the build if the models and the migrations drift apart. |
| Tests | 177 tests including property-based tests (Hypothesis) for the invariants that must hold for every input, such as allocation conserving the total. |
| Types | `mypy` with `disallow_untyped_defs` across the package; `ruff` for lint and format. |

---

## Quickstart

```bash
git clone https://github.com/elmarfarajov/meridian-investment-platform.git
cd meridian-investment-platform
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

meridian info                 # the effective configuration
meridian db init              # run the migrations (SQLite by default)
meridian db seed              # load the demonstration book
meridian db status            # row counts per table
meridian calendar chart       # write reports/trading-calendar-<year>.png
```

Point it at PostgreSQL by setting one environment variable, with no code change:

```bash
export MERIDIAN_DATABASE_URL=postgresql+psycopg://meridian:meridian@localhost:5432/meridian
```

Run the checks the way CI runs them:

```bash
ruff check src tests && ruff format --check src tests && mypy && pytest -q
```

---

## Roadmap

Built in daily increments; each day is an issue, a branch, a pull request and a tag.

| Day | Module | Status |
| --- | --- | --- |
| 1 | Foundation: money, identifiers, calendars, domain model, persistence, migrations, CLI | ✅ Done |
| 2 | Market data: prices, corporate actions, FX, data-quality rules | Planned |
| 3 | Portfolio accounting: tax lots, cost basis, wash sales, daily valuation | Planned |
| 4 | Performance: time- and money-weighted returns, Brinson-Fachler attribution, Cariño linking | Planned |
| 5 | Risk: factor model, EWMA and shrinkage covariance, VaR, bias-statistic validation | Planned |
| 6 | Compliance: a rule DSL for mandate limits, pre- and post-trade checks | Planned |
| 7 | Tax-aware optimisation: rebalancing with lot selection and tax cost | Planned |
| 8 | Execution: order management, allocation, transaction cost analysis, client reporting | Planned |
| 9 | Platform: web API, role-based access, release | Planned |

The full plan, with the reasoning behind each module, is in [docs/ROADMAP.md](docs/ROADMAP.md).
Architecture decisions are recorded in [docs/adr](docs/adr).

---

## Licence

MIT. See [LICENSE](LICENSE).
