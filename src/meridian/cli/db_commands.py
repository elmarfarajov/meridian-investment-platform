"""``meridian db`` - create, seed and inspect the database."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import func, select

from ..config import get_settings
from ..persistence import Database, UnitOfWork, seed_reference_data
from ..persistence.base import Base
from ..seed import demo_book
from ._common import console, fail, render_rows, success, table

app = typer.Typer(help="Database lifecycle: migrate, seed and inspect.", no_args_is_help=True)


def _alembic_ini() -> Path | None:
    """Find alembic.ini by walking up from the working directory."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        candidate = directory / "alembic.ini"
        if candidate.is_file():
            return candidate
    return None


@app.command("init")
def init(
    migrate: Annotated[
        bool, typer.Option("--migrate/--create-all", help="Run Alembic migrations, or create tables directly")
    ] = True,
) -> None:
    """Create the schema. Migrations are the supported path; --create-all is for throwaway databases."""
    settings = get_settings()
    settings.ensure_directories()
    ini = _alembic_ini()
    if migrate and ini is not None:
        # Levels are set before the import because Alembic registers its plugins,
        # and logs about it, at import time. Migration steps are kept; the rest
        # of the internal chatter is not something an operator needs to see.
        logging.getLogger("alembic").setLevel(logging.WARNING)
        from alembic import command
        from alembic.config import Config

        logging.getLogger("alembic.runtime.migration").setLevel(logging.INFO)
        config = Config(str(ini))
        config.set_main_option("script_location", str(ini.parent / "alembic"))
        config.attributes["configure_logger"] = False
        command.upgrade(config, "head")
        success("database migrated to head")
        console.print(f"[muted]{settings.database_url}[/muted]", overflow="fold")
        return
    if migrate:
        console.print("[muted]no alembic.ini found; falling back to create_all[/muted]")
    database = Database(settings).create_all()
    database.dispose()
    success(f"created the schema in {settings.database_url}")


@app.command("seed")
def seed() -> None:
    """Load the demonstration book: clients, accounts, portfolios, instruments and trades."""
    settings = get_settings()
    book = demo_book()
    database = Database(settings)
    try:
        with database.session() as session:
            unit_of_work = UnitOfWork(session)
            counts = seed_reference_data(
                unit_of_work,
                instruments=book.instruments,
                benchmarks=book.benchmarks,
                clients=book.clients,
                households=book.households,
                accounts=book.accounts,
                portfolios=book.portfolios,
            )
            counts["transactions"] = unit_of_work.transactions.add_all(book.transactions)
    finally:
        database.dispose()
    console.print(
        render_rows(
            table(
                "Seeded",
                ["Entity", "Rows written"],
                caption="Reference data is upserted, so re-running is safe.",
                numeric=[1],
            ),
            sorted(counts.items()),
        )
    )


@app.command("status")
def status() -> None:
    """Row counts for every table, so a load can be eyeballed in one line."""
    settings = get_settings()
    database = Database(settings)
    rows: list[tuple[str, int]] = []
    try:
        with database.session() as session:
            for table_obj in Base.metadata.sorted_tables:
                count = session.scalar(select(func.count()).select_from(table_obj))
                rows.append((table_obj.name, int(count or 0)))
    except Exception as error:  # the CLI turns any driver error into a clean message
        fail(f"could not read {settings.database_url}: {error}")
    finally:
        database.dispose()
    console.print(
        render_rows(
            table(f"Database contents ({database.dialect})", ["Table", "Rows"], numeric=[1]),
            rows,
        )
    )
    console.print(f"[muted]{settings.database_url}[/muted]", overflow="fold")
