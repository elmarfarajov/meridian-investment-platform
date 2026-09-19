# 5. The domain model is mapped to rows explicitly, not persisted directly

- **Status:** Accepted
- **Date:** 2026-09-19

## Context

SQLAlchemy can map the domain classes themselves, which removes a translation layer and a
file of mapping functions. The cost is that the domain classes then have to be shaped for
the ORM: they cannot be frozen dataclasses with validation in `__post_init__`, they gain
identity semantics they did not ask for, they must tolerate being constructed in a
half-initialised state by the loader, and every schema decision starts to leak into the
model that expresses the business rules.

The domain classes here are immutable and validate on construction: a `Transaction` with a
settlement date before its trade date cannot exist, a `Position` cannot hold a lot of a
different instrument, a `BlendedBenchmark` whose weights do not sum to one is rejected.
Those invariants are the most valuable thing in the domain layer, and an ORM that needs to
build objects incrementally is in direct tension with them.

## Decision

`meridian.domain` contains plain frozen dataclasses that know nothing about SQLAlchemy.
`meridian.persistence.models` contains the tables. `meridian.persistence.mappers` contains
a pair of functions per entity - `instrument_to_row`, `row_to_instrument` - and
repositories speak domain objects in both directions.

## Consequences

- Domain invariants hold for every object in the system, including ones just loaded from
  the database, because loading goes through the same constructor as everything else.
- The schema can be denormalised, indexed or reshaped for storage reasons without touching
  the business model. Identifiers live as columns on the instrument table, for instance,
  because every query on a security starts from one of them.
- Analytics code never imports SQLAlchemy and can be tested with in-memory objects.
- There is duplication: a new field must be added in two places, and the mapper tests
  exist to catch the case where it is added in only one.
- Lazy loading of relationships is given up. In exchange, every query is explicit, which
  is what an auditable system wants anyway.
