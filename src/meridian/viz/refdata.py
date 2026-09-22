"""Charts for the security master.

Reference data errors are silent: a wrong identifier does not crash anything,
it quietly books a trade against the wrong company. These two pictures show
the two defences - identifiers resolved by date, and golden records built
field by field with their lineage and their disagreements kept in view.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from datetime import date

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch

from ..core.exceptions import ValidationError
from ..refdata.golden_record import GoldenRecord, VendorRecord, normalise
from ..refdata.xref import CrossReference, IdentifierScheme
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block, x_of

SCHEME_COLOURS: dict[IdentifierScheme, str] = {
    IdentifierScheme.TICKER: PALETTE["navy"],
    IdentifierScheme.ISIN: PALETTE["teal"],
    IdentifierScheme.CUSIP: PALETTE["violet"],
    IdentifierScheme.SEDOL: PALETTE["sky"],
    IdentifierScheme.FIGI: PALETTE["slate"],
    IdentifierScheme.LEI: PALETTE["gain"],
    IdentifierScheme.VENDOR: PALETTE["grid"],
}


def plot_identifier_timeline(
    reference: CrossReference,
    instruments: Sequence[str],
    *,
    start: date,
    end: date,
    schemes: Sequence[IdentifierScheme] = (IdentifierScheme.TICKER, IdentifierScheme.ISIN, IdentifierScheme.CUSIP),
) -> Figure:
    """Which identifier meant which instrument, and when."""
    rows: list[tuple[str, IdentifierScheme]] = [
        (instrument, scheme)
        for instrument in instruments
        for scheme in schemes
        if any(entry.scheme is scheme for entry in reference.entries(instrument))
    ]
    figure = new_figure(15.0, 1.9 + 0.46 * len(rows) + 1.2)
    axis = figure.add_subplot()
    height = figure.get_figheight()
    figure.subplots_adjust(top=1 - 1.25 / height, bottom=0.9 / height, left=0.16, right=0.975)

    for row, (instrument, scheme) in enumerate(rows):
        if row % 2 == 0:
            axis.axhspan(row - 0.5, row + 0.5, color=PALETTE["band"], zorder=0, linewidth=0)
        for entry in reference.entries(instrument):
            if entry.scheme is not scheme:
                continue
            left = max(entry.valid_from, start)
            right = min(entry.valid_to, end)
            if right <= left:
                continue
            axis.add_patch(
                FancyBboxPatch(
                    (x_of(left), row - 0.3),
                    x_of(right) - x_of(left),
                    0.6,
                    boxstyle="round,pad=0,rounding_size=12",
                    mutation_aspect=0.02,
                    facecolor=SCHEME_COLOURS[scheme],
                    edgecolor="white",
                    linewidth=1.2,
                    zorder=3,
                )
            )
            axis.text(
                (x_of(left) + x_of(right)) / 2,
                row,
                entry.value,
                ha="center",
                va="center",
                fontsize=7.8,
                color="white",
                weight="bold",
                zorder=4,
            )

    for (scheme, value), owners in reference.reused().items():
        history = reference.history(scheme, value)
        for earlier, later in itertools.pairwise(history):
            if earlier.instrument_id == later.instrument_id:
                continue
            first_row = rows.index((earlier.instrument_id, scheme)) if (earlier.instrument_id, scheme) in rows else None
            second_row = rows.index((later.instrument_id, scheme)) if (later.instrument_id, scheme) in rows else None
            if first_row is None or second_row is None:
                continue
            axis.annotate(
                "",
                xy=(x_of(later.valid_from), second_row),
                xytext=(x_of(earlier.valid_to), first_row),
                arrowprops={
                    "arrowstyle": "->",
                    "color": PALETTE["accent"],
                    "linewidth": 1.4,
                    "connectionstyle": "arc3,rad=-0.25",
                },
                zorder=5,
            )
            annotate(
                axis,
                f"{value} reused by an unrelated company: {', '.join(owners)}",
                (x_of(earlier.valid_to), (first_row + second_row) / 2),
                highlight=True,
                xytext=(12, 0),
                textcoords="offset points",
                va="center",
            )

    for entry in reference.entries():
        if entry.scheme is IdentifierScheme.TICKER and entry.valid_from > start and entry.instrument_id in instruments:
            predecessors = [
                item
                for item in reference.entries(entry.instrument_id)
                if item.scheme is IdentifierScheme.TICKER and item.valid_to == entry.valid_from
            ]
            if predecessors:
                axis.axvline(x_of(entry.valid_from), color=PALETTE["ink"], linewidth=0.8, linestyle="--", zorder=2)
                annotate(
                    axis,
                    f"{predecessors[0].value} renamed {entry.value}, {entry.valid_from:%d %b %Y}",
                    (x_of(entry.valid_from), -0.45),
                    xytext=(4, 0),
                    textcoords="offset points",
                    va="top",
                )

    axis.set_yticks(range(len(rows)), labels=[f"{instrument}  {scheme.value.upper()}" for instrument, scheme in rows])
    axis.set_ylim(len(rows) - 0.5, -0.8)
    axis.set_xlim(x_of(start), x_of(end))
    axis.xaxis_date()
    style_axes(axis, grid="x")
    axis.tick_params(axis="y", labelsize=8.5, length=0)
    axis.legend(
        handles=[Patch(color=SCHEME_COLOURS[scheme], label=scheme.value.upper()) for scheme in schemes],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.06),
        ncol=len(schemes),
    )
    title_block(
        figure,
        "An identifier is not a name",
        "Tickers change and are reused; ISINs change when a company redomiciles. Every mapping carries a validity "
        "interval and every lookup a date, so an old trade file resolves to the company it meant at the time.",
    )
    caption(
        figure,
        "Meta's rename is real (FB became META on 9 June 2022); DEMO-OLDCO and DEMO-NEWCO are fictional, with ISINs "
        "generated with valid check digits. Overlapping claims on one identifier are refused (ADR 0012).",
    )
    return figure


def plot_golden_record(
    records: Sequence[VendorRecord],
    golden: Mapping[str, GoldenRecord],
    *,
    sources: Sequence[str] = ("exchange", "vendor-b", "evaluated"),
) -> Figure:
    """Every field from every vendor, the winner, and why the losers lost."""
    lines: list[tuple[str, str]] = []
    for instrument_id in golden:
        offered = {name for vendor in records if vendor.instrument_id == instrument_id for name in vendor.fields}
        lines.extend((instrument_id, name) for name in sorted(offered))
    columns = [*sources, "golden"]

    figure = new_figure(15.0, 1.9 + 0.3 * len(lines) + 1.0)
    axis = figure.add_subplot()
    height = figure.get_figheight()
    figure.subplots_adjust(top=1 - 1.3 / height, bottom=0.8 / height, left=0.02, right=0.98)
    axis.set_xlim(0, 2.1 + 3.0 * len(columns))
    axis.set_ylim(len(lines) + 0.2, -1.2)
    axis.set_axis_off()

    for column, name in enumerate(columns):
        axis.text(
            2.2 + column * 3.0 + 1.4,
            -0.65,
            name,
            ha="center",
            va="center",
            fontsize=9,
            weight="bold",
            color=PALETTE["ink"],
        )
    previous = ""
    for row, (instrument_id, field) in enumerate(lines):
        if instrument_id != previous:
            axis.plot([0, axis.get_xlim()[1]], [row - 0.5, row - 0.5], color=PALETTE["ink"], linewidth=0.8)
            axis.text(0.05, row, instrument_id, fontsize=8.5, weight="bold", va="center", color=PALETTE["navy"])
            previous = instrument_id
        axis.text(1.05, row, field, fontsize=8, va="center", color=PALETTE["muted"])
        record = golden[instrument_id]
        conflicted = {item.field for item in record.conflicts}
        for column, source in enumerate(sources):
            raw = next(
                (
                    vendor.fields.get(field)
                    for vendor in records
                    if vendor.instrument_id == instrument_id and vendor.source == source
                ),
                None,
            )
            if raw is None:
                continue
            x = 2.2 + column * 3.0
            rejected = any(item.field == field and item.source == source for item in record.rejected)
            winner = record.lineage.get(field) == source
            if rejected:
                face = "#F4D3D6"
            elif winner:
                face = "#D6EDE0"
            elif field in conflicted:
                face = "#F3E7CC"
            else:
                face = PALETTE["band"]
            axis.add_patch(
                FancyBboxPatch(
                    (x, row - 0.38),
                    2.8,
                    0.76,
                    boxstyle="round,pad=0,rounding_size=0.08",
                    facecolor=face,
                    edgecolor="white",
                    linewidth=1,
                )
            )
            shown = raw if len(raw) <= 30 else raw[:28] + "..."
            axis.text(
                x + 1.4,
                row,
                shown,
                ha="center",
                va="center",
                fontsize=7.4,
                color=PALETTE["ink"],
                style="italic" if rejected else "normal",
            )
            if rejected:
                axis.plot([x + 0.25, x + 2.55], [row, row], color=PALETTE["loss"], linewidth=1.1)
        value = record.values.get(field)
        x = 2.2 + len(sources) * 3.0
        if value is not None:
            axis.add_patch(
                FancyBboxPatch(
                    (x, row - 0.38),
                    2.8,
                    0.76,
                    boxstyle="round,pad=0,rounding_size=0.08",
                    facecolor=PALETTE["navy"],
                    edgecolor="white",
                    linewidth=1,
                )
            )
            axis.text(
                x + 1.4,
                row,
                value if len(value) <= 30 else value[:28] + "...",
                ha="center",
                va="center",
                fontsize=7.4,
                color="white",
                weight="bold",
            )

    conflict_count = sum(len(record.conflicts) for record in golden.values())
    refused_count = sum(len(record.rejected) for record in golden.values())
    axis.legend(
        handles=[
            Patch(color="#D6EDE0", label="Chosen by the survivorship rules"),
            Patch(color="#F3E7CC", label="Outranked in a genuine disagreement"),
            Patch(color=PALETTE["band"], label="Agreed after normalisation"),
            Line2D([], [], color=PALETTE["loss"], label="Failed validation: cannot win"),
            Patch(color=PALETTE["navy"], label="Golden value"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.0),
        ncol=5,
    )
    title_block(
        figure,
        "One security, three vendors",
        f"{len(golden)} golden records from {len(records)} vendor records: {conflict_count} genuine disagreements "
        f"kept for review, {refused_count} values refused by check-digit validation. Each field names its source.",
    )
    caption(
        figure,
        "Values are compared after normalisation (4.125 = 4.12500, 'Information Tech' = 'Information Technology'); "
        "field-level rankings decide the rest. GBX against GBP is the pence-and-pounds trap the quality rules watch.",
    )
    return figure


def normalised_or_none(field: str, value: str) -> str | None:
    """A value as the golden record compares it, or ``None`` if it fails validation."""
    try:
        return normalise(field, value)
    except ValidationError:
        return None


__all__ = ["SCHEME_COLOURS", "normalised_or_none", "plot_golden_record", "plot_identifier_timeline"]
