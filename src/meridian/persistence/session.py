"""Engine and session management.

SQLite is the default so a clone runs with no setup, while the same code runs on
PostgreSQL in CI and in production. Two SQLite quirks are handled here rather than
being discovered later: foreign keys are off by default, and the default isolation
handling breaks transactional tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from .base import Base


def create_database_engine(settings: Settings | None = None, **kwargs: Any) -> Engine:
    settings = settings or get_settings()
    options: dict[str, Any] = {"echo": settings.echo_sql, "future": True}
    if settings.is_sqlite:
        options["connect_args"] = {"check_same_thread": False}
        url = settings.database_url
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    else:
        options["pool_pre_ping"] = True
    options.update(kwargs)
    engine = create_engine(settings.database_url, **options)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_all(engine: Engine) -> None:
    """Create the schema directly; migrations remain the path for real deployments."""
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    Base.metadata.drop_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Database:
    """Convenience wrapper tying an engine, a session factory and the schema together."""

    def __init__(self, settings: Settings | None = None, engine: Engine | None = None) -> None:
        self.settings = settings or get_settings()
        self.engine = engine or create_database_engine(self.settings)
        self.session_factory = create_session_factory(self.engine)

    def create_all(self) -> Database:
        create_all(self.engine)
        return self

    @contextmanager
    def session(self) -> Iterator[Session]:
        with session_scope(self.session_factory) as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name
