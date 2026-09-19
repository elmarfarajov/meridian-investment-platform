# 3. SQLite for development, PostgreSQL in CI and production

- **Status:** Accepted
- **Date:** 2026-09-19

## Context

The platform needs a real relational database: foreign keys, exact `NUMERIC`, indexes and
migrations. PostgreSQL is the obvious production choice. But requiring a running
PostgreSQL instance to run the test suite makes a clone expensive - a container runtime, a
service, credentials - and a test suite that is expensive to run is a test suite that gets
run less often.

Developing against SQLite alone is not acceptable either. SQLite has no real `NUMERIC`
type, it does not enforce foreign keys unless told to, and its type affinity is forgiving
in ways PostgreSQL is not. Code that only ever meets SQLite will break the first time it
meets a server.

## Decision

The default database is SQLite, so `pip install -e .` and `pytest` work on a fresh clone
with no configuration. The database URL comes from a single environment variable,
`MERIDIAN_DATABASE_URL`, read through `pydantic-settings`, so nothing in the code knows
which engine is in use.

CI runs the same code against a PostgreSQL 16 service container: `alembic upgrade head`,
then `alembic check` to prove the models and the migrations have not drifted, then the
tests marked `integration`. Those tests cover precisely what SQLite cannot: enforced
foreign keys on a server engine, `NUMERIC` round-tripping at full scale, and identical
ordering behaviour from the repository queries.

SQLite quirks are handled once, in the engine factory: `PRAGMA foreign_keys=ON` on every
connection, and batch mode in migrations because SQLite cannot alter a column in place.

## Consequences

- A clone runs in seconds with nothing installed but Python.
- The PostgreSQL path is exercised on every push, so it cannot quietly rot.
- Two engines must be kept working. The cost is contained because repositories are the
  only code that touches the database, and they are dialect-neutral SQLAlchemy Core.
- Anything genuinely PostgreSQL-specific - a materialised view, a window function that
  SQLite lacks - will need a feature check rather than an assumption.
