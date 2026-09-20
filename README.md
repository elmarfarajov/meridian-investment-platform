# Meridian

**An institutional investment management platform: the book of record, the analytics and the reporting behind a multi-currency, multi-account client portfolio.**

[![CI](https://github.com/elmarfarajov/meridian-investment-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/elmarfarajov/meridian-investment-platform/actions/workflows/ci.yml)
[![Python 3.10 – 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-1B3A6B)](https://www.python.org/)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-1F8A80)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-6A4C93)](https://docs.astral.sh/ruff/)
[![Tests](https://img.shields.io/badge/tests-373-2E7D5B)](tests)
[![License: MIT](https://img.shields.io/badge/license-MIT-4A5C75)](LICENSE)

Asset managers do not run on spreadsheets. They run on systems like BlackRock's Aladdin,
Charles River IMS and SimCorp Dimension: one place that holds every position and tax lot,
values it every night, attributes the return against a benchmark, decomposes the risk,
checks every proposed trade against the mandate, and produces the statement the client
reads. Meridian is a working implementation of that spine, built from first principles.

It is a portfolio engineering project, not a commercial product. The point is to show the
reasoning: why money is a `Decimal` and never a float, why a curve's interpolation method
is a modelling decision rather than a detail, why an exchange calendar is generated from
statutory rules rather than loaded from a file that goes stale, and why duration alone is
not a risk measure.

---

## What it does today

```bash
meridian rates curve --tenors 0.25,1,2,5,10,30 --par 4.25,4.18,3.95,3.90,4.15,4.55
# Bootstraps a zero curve, one instrument at a time, and prints par, zero,
# discount factors and forwards side by side.

meridian rates bond 2034-05-15 --coupon 4 --issue 2024-05-15 --price 96.79
# Yield to maturity 4.500272%, modified duration 6.407, convexity 48.61,
# DV01 0.0629 per 100 of face, accrued 1.40 on 129/184 days.

meridian calendar ladder 2026-12-23 --calendars XNYS,XLON,TARGET,XTKS
# Where T+1 to T+3 land in each market, and in the joint calendar every leg
# of a cross-border trade has to clear.

meridian security validate US0378331005 HWUPKR0MPOU8FGXBT394
# ISIN and LEI, each against its own check-digit algorithm.
```

---

## The charts

Every module ships a visual, not only numbers. All seventeen are in the
[gallery](docs/GALLERY.md) and are rebuilt from source with `meridian charts gallery`.

**Two markets that are open on different days are the reason a cross-border trade fails
to settle.** Meridian generates its calendars from statutory rules - Easter by the
Meeus/Jones/Butcher algorithm, US observed-day shifts, UK substitute days that chain, and
the Japanese equinoxes, which are astronomical events approximated by formula.

![Exchange trading calendars, 2026](docs/images/trading-calendar-2026.png)

**The par curve, the zero curve and the forward curve are three views of one set of
quotes,** and confusing them misprices everything downstream.

![Yield curve](docs/images/yield-curve.png)

**Interpolation is a modelling choice.** The three methods agree at every quoted pillar
and disagree everywhere else - most visibly in the forward curve, where linear
interpolation produces a sawtooth that looks like an arbitrage that is not there.

![Curve interpolation](docs/images/curve-interpolation.png)

**Duration is a straight line drawn through a curved function.** It always overstates the
loss from a rise in yields and understates the gain from a fall; convexity is the
correction, and at 300 basis points it is worth more than two points of face value.

![Price against yield](docs/images/price-yield.png)

**A trade whose legs settle in different markets has to clear both calendars.** These are
the days that produce failed settlements, missed coupons and stale marks.

![Settlement ladder](docs/images/settlement-ladder.png)

**The data model is drawn from the live SQLAlchemy metadata,** so the architecture diagram
cannot drift from the schema.

![Data model](docs/images/data-model.png)

---

## Architecture

The package is layered so each concern is testable on its own, and so nothing above the
persistence layer knows which database is in use.

```
meridian
├── core          value objects: Money, Currency, FX, identifiers, calendars,
│                 day counts, schedules, compounding, interpolation
├── domain        the business model: instruments, portfolios, accounts,
│                 positions, transactions
├── analytics     the quantitative layer: solvers, yield curves, bond mathematics
├── persistence   SQLAlchemy 2.0 schema, explicit mappers, repositories, unit of work
├── viz           the house chart style and seventeen figures
├── cli           a thin Typer layer over tested functions
├── gallery       one definition of every chart, used by the docs and the tests
└── seed          a hand-made demonstration book to run everything against
```

**Dependencies point inwards.** `core` imports nothing from the platform. `domain` and
`analytics` import `core`. `persistence` maps `domain` to rows through explicit functions
rather than persisting the domain classes directly, so the schema can change for storage
reasons without loosening a domain invariant. Analytics code never imports SQLAlchemy.

---

## Engineering standards

| Concern | Decision |
| --- | --- |
| Money | `Decimal` end to end, banker's rounding, currency-tagged, no silent mixing. `Money.allocate` splits an amount so the parts always sum back to the whole. |
| Analytics | `float`, deliberately: this layer solves and differentiates. Values crossing into the ledger convert back to `Decimal` at the boundary ([ADR 0008](docs/adr/0008-decimal-in-the-ledger-float-in-the-analytics.md)). |
| Identifiers | ISIN, CUSIP, SEDOL, FIGI and LEI by their real check-digit algorithms, tested against published identifiers for Apple, Microsoft, BAE, Bayer, Toyota, Roche, Goldman Sachs, JPMorgan, Deutsche Bank, HSBC and Barclays. |
| Calendars | Eight markets generated from rules, not files, with composition for cross-border settlement, plus five business-day conventions and T+n arithmetic. |
| Day counts | Nine conventions, including the three that need a coupon period, a calendar or a maturity flag to be evaluated at all. |
| Numerics | Safeguarded Newton with a bisection fallback; non-convergence raises rather than returning a plausible wrong number. |
| Database | SQLite locally so a clone runs with no setup; the same suite runs against PostgreSQL 16 in CI. Fixed-scale `NUMERIC` columns, never floats. |
| Migrations | Alembic, with `alembic check` in CI failing the build if the models and the migrations drift apart. |
| Tests | 373 tests, including property-based tests (Hypothesis) for the invariants that must hold for every input: allocation conserves the total, rate conversions round-trip, monotone interpolation stays monotone. |
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
meridian charts gallery       # rebuild every figure in docs/images
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

## Documentation

| Document | What it covers |
| --- | --- |
| [Fixed income mathematics](docs/notes/fixed-income-mathematics.md) | Discounting, bootstrapping, clean and dirty price, duration, convexity, key rate durations, and the numerical method behind them |
| [Calendar conventions](docs/notes/calendar-conventions.md) | How each market's holidays are computed, the asymmetries that are easy to get wrong, and why calendars compose |
| [Chart gallery](docs/GALLERY.md) | All seventeen figures, with what each one argues |
| [Architecture decisions](docs/adr) | Eight records: what was decided, what the alternatives were, and what it costs |
| [Roadmap](docs/ROADMAP.md) | The nine modules, and the reasoning behind each |

---

## Roadmap

Built in daily increments; each day is an issue, a branch, a pull request and a tag.

| Day | Module | Status |
| --- | --- | --- |
| 1 | Foundation: money, identifiers, calendars, schedules, curves, bond analytics, domain model, persistence, migrations, CLI | ✅ Done |
| 2 | Market data: prices, corporate actions, FX, data-quality rules | Planned |
| 3 | Portfolio accounting: tax lots, cost basis, wash sales, daily valuation | Planned |
| 4 | Performance: time- and money-weighted returns, Brinson-Fachler attribution, Cariño linking | Planned |
| 5 | Risk: factor model, EWMA and shrinkage covariance, VaR, bias-statistic validation | Planned |
| 6 | Compliance: a rule DSL for mandate limits, pre- and post-trade checks | Planned |
| 7 | Tax-aware optimisation: rebalancing with lot selection and tax cost | Planned |
| 8 | Execution: order management, allocation, transaction cost analysis, client reporting | Planned |
| 9 | Platform: web API, role-based access, release | Planned |

---

## Licence

MIT. See [LICENSE](LICENSE).
