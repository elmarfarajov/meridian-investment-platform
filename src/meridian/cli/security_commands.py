"""``meridian security`` - validate the identifiers a book of record runs on."""

from __future__ import annotations

from typing import Annotated

import typer

from ..core.identifiers import CUSIP, ISIN, expected_check_digit, identify
from ._common import console, render_rows, table

app = typer.Typer(help="Security and entity identifiers: validation and conversion.", no_args_is_help=True)

_SHAPES = {
    20: "LEI",
    12: "ISIN or FIGI",
    9: "CUSIP",
    7: "SEDOL",
}


@app.command("validate")
def validate(
    values: Annotated[list[str], typer.Argument(help="One or more identifiers to check")],
) -> None:
    """Check identifiers against their check digits and say which scheme each belongs to."""
    rows: list[tuple[str, str, str, str]] = []
    for raw in values:
        candidate = raw.strip().upper()
        schemes = identify(candidate)
        if schemes:
            rows.append((raw, ", ".join(schemes), "[good]valid[/good]", _detail(candidate, schemes)))
        else:
            shape = _SHAPES.get(len(candidate), f"unknown ({len(candidate)} characters)")
            expected = expected_check_digit(candidate)
            rows.append(
                (
                    raw,
                    shape,
                    "[bad]invalid[/bad]",
                    f"expected check digit {expected}" if expected else "malformed",
                )
            )
    console.print(
        render_rows(
            table(
                "Identifier validation",
                ["Input", "Scheme", "Result", "Detail"],
                caption="Check digits: ISIN uses Luhn after letter expansion, CUSIP a weighted mod 10, "
                "SEDOL the 1,3,1,7,3,9 weights, FIGI a doubled-position digit sum, LEI ISO 7064 MOD 97-10.",
            ),
            rows,
        )
    )


def _detail(candidate: str, schemes: tuple[str, ...]) -> str:
    if "ISIN" in schemes:
        return f"country {candidate[:2]}, check digit {candidate[-1]}"
    if "CUSIP" in schemes:
        return f"ISIN would be {CUSIP(candidate).to_isin()}"
    if "LEI" in schemes:
        return f"issued by LOU {candidate[:4]}, entity part {candidate[4:18]}"
    if "FIGI" in schemes:
        return "Bloomberg global identifier"
    return ""


@app.command("to-isin")
def to_isin(
    cusip: Annotated[str, typer.Argument(help="A 9-character CUSIP")],
    country: Annotated[str, typer.Option("--country", help="Issuing country code")] = "US",
) -> None:
    """Convert a CUSIP into its ISIN, recomputing the ISIN check digit."""
    identifier = CUSIP(cusip)
    isin: ISIN = identifier.to_isin(country)
    console.print(f"[key]{identifier}[/key] -> [key]{isin}[/key]")
