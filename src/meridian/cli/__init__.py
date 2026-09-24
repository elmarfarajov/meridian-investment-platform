"""The ``meridian`` command line.

The CLI is the thinnest possible layer over the library: every command maps to a
function that is tested on its own. Anything an operations team would run at
three in the afternoon on a settlement date belongs here.
"""

from __future__ import annotations

from typing import Annotated

import typer

from .. import __version__
from ..config import get_settings
from ..observability import configure_logging
from . import (
    book_commands,
    calendar_commands,
    chart_commands,
    db_commands,
    market_commands,
    perf_commands,
    rates_commands,
    security_commands,
)
from ._common import console, render_rows, table

app = typer.Typer(
    name="meridian",
    help="Meridian - institutional investment management platform.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(db_commands.app, name="db")
app.add_typer(calendar_commands.app, name="calendar")
app.add_typer(security_commands.app, name="security")
app.add_typer(rates_commands.app, name="rates")
app.add_typer(chart_commands.app, name="charts")
app.add_typer(market_commands.app, name="market")
app.add_typer(book_commands.app, name="book")
app.add_typer(perf_commands.app, name="perf")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"meridian {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the version and exit")
    ] = False,
) -> None:
    configure_logging()


@app.command("info")
def info() -> None:
    """Show the effective configuration, which is the first thing to check when something looks wrong."""
    settings = get_settings()
    rows = [
        ("version", __version__),
        ("database", settings.database_url),
        ("dialect", "sqlite" if settings.is_sqlite else settings.database_url.split(":", 1)[0]),
        ("base currency", settings.base_currency),
        ("default calendar", settings.default_calendar),
        ("data directory", settings.data_dir),
        ("reports directory", settings.reports_dir),
        ("log level", settings.log_level),
        ("log format", "json" if settings.log_json else "console"),
    ]
    console.print(
        render_rows(
            table(
                "Meridian configuration",
                ["Setting", "Value"],
                caption="Every value can be overridden with a MERIDIAN_ environment variable or a .env file.",
            ),
            rows,
        )
    )


__all__ = ["app", "main"]
