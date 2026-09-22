"""Bulk upsert that works the same on SQLite and PostgreSQL.

``Session.merge`` is the right tool for one reference-data record and the
wrong one for an end-of-day load: it issues a SELECT per row, so twenty
thousand observations become forty thousand round trips. A pricing run needs
upsert semantics at batch speed, portably - so the dialect-specific
``ON CONFLICT`` clauses are avoided in favour of three statements whatever the
batch size: one SELECT for the keys that already exist, one executemany
INSERT for the new rows, one executemany UPDATE for the rest.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import ColumnElement, insert, inspect, select, tuple_, update
from sqlalchemy.orm import Session

from .base import Base

#: Stay well inside SQLite's bound-parameter limit when filtering on key tuples.
_KEY_BATCH = 400


def _comparable(value: Any) -> Any:
    """Key values as both dialects return them: SQLite hands back naive UTC datetimes, PostgreSQL aware ones."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _key_columns(model: type[Base]) -> list[ColumnElement[Any]]:
    return list(inspect(model).primary_key)


def _existing_keys(session: Session, model: type[Base], keys: Sequence[tuple[Any, ...]]) -> set[tuple[Any, ...]]:
    key_columns = _key_columns(model)
    found: set[tuple[Any, ...]] = set()
    for start in range(0, len(keys), _KEY_BATCH):
        batch = list(keys[start : start + _KEY_BATCH])
        statement = select(*key_columns).where(tuple_(*key_columns).in_(batch))
        found.update(tuple(_comparable(value) for value in row) for row in session.execute(statement))
    return found


def bulk_upsert(session: Session, model: type[Base], rows: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """Insert or update ``rows`` keyed by the model's primary key; return (inserted, updated)."""
    if not rows:
        return 0, 0
    names = [column.name for column in _key_columns(model)]

    def key_of(row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(row[name] for name in names)

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        unique[key_of(row)] = row  # the last version of a duplicated key wins, as merge would

    existing = _existing_keys(session, model, list(unique))
    new_rows = [row for key, row in unique.items() if tuple(map(_comparable, key)) not in existing]
    old_rows = [row for key, row in unique.items() if tuple(map(_comparable, key)) in existing]
    if new_rows:
        session.execute(insert(model), new_rows)
    if old_rows:
        session.execute(update(model), old_rows)
    return len(new_rows), len(old_rows)


def insert_missing(session: Session, model: type[Base], rows: Iterable[dict[str, Any]]) -> int:
    """Insert only the rows whose key is not already stored: append-only tables never update."""
    materialised = list(rows)
    if not materialised:
        return 0
    names = [column.name for column in _key_columns(model)]
    unique = {tuple(row[name] for name in names): row for row in materialised}
    existing = _existing_keys(session, model, list(unique))
    fresh = [row for key, row in unique.items() if tuple(map(_comparable, key)) not in existing]
    if fresh:
        session.execute(insert(model), fresh)
    return len(fresh)
