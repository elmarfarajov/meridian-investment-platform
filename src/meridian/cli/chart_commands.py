"""``meridian charts`` - regenerate every figure the documentation uses."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..gallery import build_gallery, gallery_items
from ..viz.schema import plot_schema
from ..viz.style import save_figure
from ._common import console, render_rows, success, table

app = typer.Typer(help="Charts: regenerate the documentation figures.", no_args_is_help=True)


@app.command("list")
def list_charts() -> None:
    """Show every chart the platform can produce."""
    rows = [(item.group, item.filename, item.title, item.description) for item in gallery_items()]
    console.print(
        render_rows(
            table(
                "Chart gallery",
                ["Group", "File", "Title", "What it shows"],
                caption="Rebuild them all with: meridian charts gallery",
            ),
            rows,
        )
    )


@app.command("gallery")
def gallery(
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory to write into")] = Path("docs/images"),
    only: Annotated[str | None, typer.Option("--only", help="One group or filename")] = None,
    dpi: Annotated[int, typer.Option("--dpi")] = 130,
) -> None:
    """Rebuild the documentation figures from the current source."""
    written = build_gallery(out, only=only, dpi=dpi)
    for path in written:
        console.print(f"[muted]{path}[/muted]")
    success(f"{len(written)} chart(s) written to {out}")


@app.command("schema")
def schema(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("docs/images/data-model.png"),
) -> None:
    """Draw the entity-relationship diagram from the live metadata."""
    success(f"wrote {save_figure(plot_schema(), out)}")
