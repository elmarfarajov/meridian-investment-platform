"""``meridian security`` - validate the identifiers a book of record runs on."""

from __future__ import annotations

from typing import Annotated

import typer

from ..core.identifiers import (
    CUSIP,
    ISIN,
    cusip_check_digit,
    isin_check_digit,
    sedol_check_digit,
    validate_cusip,
    validate_figi,
    validate_isin,
    validate_sedol,
)
from ._common import console, render_rows, table

app = typer.Typer(help="Security identifiers: validation and conversion.", no_args_is_help=True)

_VALIDATORS = (
    ("ISIN", validate_isin, 12),
    ("CUSIP", validate_cusip, 9),
    ("SEDOL", validate_sedol, 7),
    ("FIGI", validate_figi, 12),
)


@app.command("validate")
def validate(
    values: Annotated[list[str], typer.Argument(help="One or more identifiers to check")],
) -> None:
    """Check identifiers against their check digits and say which scheme each belongs to."""
    rows: list[tuple[str, str, str, str]] = []
    for raw in values:
        candidate = raw.strip().upper()
        matches = [name for name, validator, length in _VALIDATORS if len(candidate) == length and validator(candidate)]
        if matches:
            scheme = ", ".join(matches)
            detail = ""
            if "ISIN" in matches:
                detail = f"country {candidate[:2]}, check digit {candidate[-1]}"
            elif "CUSIP" in matches:
                detail = f"ISIN would be {CUSIP(candidate).to_isin()}"
            rows.append((raw, scheme, "[good]valid[/good]", detail))
        else:
            rows.append((raw, _guess_scheme(candidate), "[bad]invalid[/bad]", _expected(candidate)))
    console.print(
        render_rows(
            table(
                "Identifier validation",
                ["Input", "Scheme", "Result", "Detail"],
                caption="Check digits: ISIN uses Luhn after letter expansion, CUSIP a weighted mod 10, "
                "SEDOL the 1,3,1,7,3,9 weights, FIGI a doubled-position digit sum.",
            ),
            rows,
        )
    )


def _guess_scheme(candidate: str) -> str:
    by_length = {12: "ISIN or FIGI", 9: "CUSIP", 7: "SEDOL"}
    return by_length.get(len(candidate), f"unknown ({len(candidate)} characters)")


def _expected(candidate: str) -> str:
    """For a near-miss, show the check digit the body actually implies."""
    try:
        if len(candidate) == 12 and candidate[:2].isalpha():
            return f"expected check digit {isin_check_digit(candidate[:11])}"
        if len(candidate) == 9:
            return f"expected check digit {cusip_check_digit(candidate[:8])}"
        if len(candidate) == 7:
            return f"expected check digit {sedol_check_digit(candidate[:6])}"
    except Exception:  # a malformed body simply has no expected digit
        return ""
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
