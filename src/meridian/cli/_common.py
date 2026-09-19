"""Shared CLI plumbing: one console, one table style, one way to fail."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table
from rich.theme import Theme

THEME = Theme(
    {
        "heading": "bold #1B3A6B",
        "key": "bold",
        "muted": "dim",
        "good": "bold green",
        "bad": "bold red",
        "highlight": "bold #E07A29",
    }
)

console = Console(theme=THEME, highlight=False)
error_console = Console(theme=THEME, stderr=True, highlight=False)


def table(
    title: str,
    columns: Sequence[str],
    *,
    caption: str | None = None,
    numeric: Sequence[int] = (),
) -> Table:
    """A table in the house style. ``numeric`` holds the indexes of right-aligned columns."""
    built = Table(title=title, caption=caption, title_justify="left", caption_justify="left", header_style="heading")
    for index, column in enumerate(columns):
        built.add_column(column, justify="right" if index in numeric else "left")
    return built


def render_rows(built: Table, rows: Iterable[Sequence[Any]]) -> Table:
    for row in rows:
        built.add_row(*["" if cell is None else str(cell) for cell in row])
    return built


def fail(message: str, *, code: int = 1) -> NoReturn:
    error_console.print(f"[bad]error[/bad] {message}")
    raise typer.Exit(code)


def success(message: str) -> None:
    console.print(f"[good]ok[/good] {message}")
