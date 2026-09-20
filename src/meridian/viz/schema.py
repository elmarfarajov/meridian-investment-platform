"""An entity-relationship diagram drawn from the live SQLAlchemy metadata.

Hand-drawn architecture diagrams are wrong within a month. This one is generated
from ``Base.metadata``, so it cannot disagree with the schema: if a column is
added, it appears; if a foreign key is dropped, the arrow goes.

Tables are laid out in dependency layers - a table sits to the right of everything
it points at - which makes the direction of reference readable at a glance.
"""

from __future__ import annotations

from collections import defaultdict

from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from sqlalchemy import MetaData, Table

from ..persistence.base import Base
from .style import PALETTE, caption, new_figure, title_block

_ROW_HEIGHT = 0.185
_BOX_WIDTH = 2.55
_HEADER = 0.34


def _layers(metadata: MetaData) -> list[list[Table]]:
    """Group tables so that every table appears after the tables it references."""
    depth: dict[str, int] = {}
    tables = {table.name: table for table in metadata.sorted_tables}

    def resolve(name: str, seen: frozenset[str] = frozenset()) -> int:
        if name in depth:
            return depth[name]
        if name in seen:  # a cycle: stop rather than recurse forever
            return 0
        parents = {
            key.column.table.name
            for key in tables[name].foreign_keys
            if key.column.table.name != name and key.column.table.name in tables
        }
        value = 0 if not parents else 1 + max(resolve(parent, seen | {name}) for parent in parents)
        depth[name] = value
        return value

    for name in tables:
        resolve(name)

    grouped: dict[int, list[Table]] = defaultdict(list)
    for name, level in sorted(depth.items()):
        grouped[level].append(tables[name])
    return [grouped[level] for level in sorted(grouped)]


def _column_label(table: Table, column_name: str) -> str:
    column = table.columns[column_name]
    marks = []
    if column.primary_key:
        marks.append("PK")
    if column.foreign_keys:
        marks.append("FK")
    suffix = f"  {'/'.join(marks)}" if marks else ""
    return f"{column.name}{suffix}"


def plot_schema(metadata: MetaData | None = None, *, max_columns: int = 9) -> Figure:
    """Draw every table, its key columns and the foreign keys between them."""
    metadata = metadata or Base.metadata
    layers = _layers(metadata)
    tallest = max(
        sum(
            (min(len(table.columns), max_columns) + (1 if len(table.columns) > max_columns else 0)) * _ROW_HEIGHT
            + _HEADER
            + 0.42
            for table in layer
        )
        for layer in layers
    )

    width = 2.1 + len(layers) * (_BOX_WIDTH + 0.85)
    figure = new_figure(max(11.0, width), max(7.0, tallest + 1.9))
    axis = figure.add_subplot()
    figure.subplots_adjust(
        top=1 - 1.0 / figure.get_figheight(), bottom=0.3 / figure.get_figheight(), left=0.02, right=0.99
    )
    axis.set_axis_off()
    axis.set_xlim(0, len(layers) * (_BOX_WIDTH + 0.85) + 0.4)
    axis.set_ylim(0, tallest + 0.6)

    colours = (PALETTE["navy"], PALETTE["teal"], PALETTE["violet"], PALETTE["sky"], PALETTE["slate"])
    anchors: dict[str, tuple[float, float, float, float]] = {}

    for layer_index, layer in enumerate(layers):
        x = 0.35 + layer_index * (_BOX_WIDTH + 0.85)
        y = tallest + 0.2
        colour = colours[layer_index % len(colours)]
        for table in layer:
            shown = list(table.columns)[:max_columns]
            truncated = len(table.columns) > max_columns
            height = (len(shown) + (1 if truncated else 0)) * _ROW_HEIGHT + _HEADER
            y -= height + 0.42
            axis.add_patch(
                FancyBboxPatch(
                    (x, y),
                    _BOX_WIDTH,
                    height,
                    boxstyle="round,pad=0.02,rounding_size=0.05",
                    linewidth=1.0,
                    edgecolor=colour,
                    facecolor="white",
                    zorder=3,
                )
            )
            axis.add_patch(
                FancyBboxPatch(
                    (x, y + height - _HEADER),
                    _BOX_WIDTH,
                    _HEADER,
                    boxstyle="round,pad=0.02,rounding_size=0.05",
                    linewidth=0,
                    facecolor=colour,
                    zorder=4,
                )
            )
            axis.text(
                x + _BOX_WIDTH / 2,
                y + height - _HEADER / 2,
                table.name,
                ha="center",
                va="center",
                fontsize=9.5,
                fontweight="bold",
                color="white",
                zorder=5,
            )
            for row, column in enumerate(shown):
                axis.text(
                    x + 0.1,
                    y + height - _HEADER - (row + 0.6) * _ROW_HEIGHT,
                    _column_label(table, column.name),
                    ha="left",
                    va="center",
                    fontsize=7.2,
                    color=PALETTE["ink"] if column.primary_key else PALETTE["muted"],
                    zorder=5,
                )
            if truncated:
                axis.text(
                    x + 0.1,
                    y + height - _HEADER - (len(shown) + 0.6) * _ROW_HEIGHT,
                    f"... {len(table.columns) - max_columns} more",
                    fontsize=6.6,
                    color=PALETTE["muted"],
                    style="italic",
                    zorder=5,
                )
            anchors[table.name] = (x, y, _BOX_WIDTH, height)

    for table in metadata.sorted_tables:
        for key in table.foreign_keys:
            target = key.column.table.name
            if target not in anchors or target == table.name:
                continue
            sx, sy, sw, sh = anchors[target]
            tx, ty, tw, th = anchors[table.name]
            start = (sx + sw, sy + sh / 2) if sx < tx else (sx, sy + sh / 2)
            end = (tx, ty + th / 2) if sx < tx else (tx + tw, ty + th / 2)
            axis.add_patch(
                FancyArrowPatch(
                    start,
                    end,
                    connectionstyle="arc3,rad=0.16",
                    arrowstyle="-|>",
                    mutation_scale=9,
                    linewidth=0.9,
                    color=PALETTE["muted"],
                    alpha=0.75,
                    zorder=2,
                )
            )

    table_count = len(metadata.sorted_tables)
    column_count = sum(len(table.columns) for table in metadata.sorted_tables)
    key_count = sum(len(table.foreign_keys) for table in metadata.sorted_tables)
    title_block(
        figure,
        "Meridian data model",
        f"{table_count} tables, {column_count} columns, {key_count} foreign keys - generated from the live "
        "SQLAlchemy metadata, so it cannot drift from the schema.",
    )
    caption(
        figure,
        "Arrows point from the referenced table to the table holding the foreign key. "
        "Tables are arranged in dependency layers, left to right.",
    )
    return figure
