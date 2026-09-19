"""Declarative base and column conventions.

Two decisions live here. First, constraint naming is explicit, because Alembic can
only generate a clean migration for a constraint it can name. Second, every
monetary or quantity column is ``Numeric`` with a fixed scale rather than a float:
the database must not be the place where a cent goes missing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.type_api import TypeEngine

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

AMOUNT = Numeric(28, 10)
QUANTITY = Numeric(28, 10)
RATE = Numeric(20, 12)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, TypeEngine[Any]]] = {
        Decimal: AMOUNT,
        str: String(255),
        datetime: DateTime(timezone=True),
    }

    def as_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        primary = ", ".join(f"{key.name}={getattr(self, key.name)!r}" for key in self.__table__.primary_key)
        return f"<{type(self).__name__} {primary}>"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Audit columns every table carries; investment records are never silently edited."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
