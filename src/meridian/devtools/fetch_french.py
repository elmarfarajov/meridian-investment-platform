"""Rebuild the packaged Kenneth French data: 12 industry portfolios and the Fama-French factors.

    python -m meridian.devtools.fetch_french             # download and rebuild
    python -m meridian.devtools.fetch_french --from DIR  # rebuild from the library's CSV files already downloaded

The library publishes each table as a zipped CSV of several sections, each a title,
a header row and one row per month (``192607``) or year (``  1927``). Only the
monthly sections are kept: the value- and equal-weighted returns, the number of
firms and their average size for the industries, and the three factors.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import urllib.request
import zipfile
from pathlib import Path

from ..marketdata.french import FACTOR_FILE, INDUSTRY_FILE, REFERENCE_DIR

BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
INDUSTRY_ZIP = "12_Industry_Portfolios_CSV.zip"
FACTOR_ZIP = "F-F_Research_Data_Factors_CSV.zip"
MISSING = {"-99.99", "-999"}

INDUSTRY_SECTIONS = {
    "Average Value Weighted Returns -- Monthly": "vw",
    "Average Equal Weighted Returns -- Monthly": "ew",
    "Number of Firms in Portfolios": "firms",
    "Average Firm Size": "size",
}


def sections(text: str) -> dict[str, tuple[list[str], list[tuple[str, list[str]]]]]:
    """Every section of a library CSV: its title, header and rows (first cell, the other cells)."""
    found: dict[str, tuple[list[str], list[tuple[str, list[str]]]]] = {}
    title: str | None = None
    current: list[tuple[str, list[str]]] | None = None
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split(",")]
        if not line.strip():
            continue
        if line.startswith(",") and title is not None:
            current = []
            found[title] = (cells[1:], current)
        elif cells[0].isdigit() and current is not None:
            current.append((cells[0], cells[1:]))
        elif not cells[0].isdigit():
            title, current = line.strip(), None
    return found


def monthly_rows(table: tuple[list[str], list[tuple[str, list[str]]]]) -> list[tuple[str, list[str]]]:
    return [(key, values) for key, values in table[1] if len(key) == 6]


def industry_rows(text: str) -> list[dict[str, str]]:
    parsed = sections(text)
    missing = [title for title in INDUSTRY_SECTIONS if title not in parsed]
    if missing:
        raise ValueError(f"the industry file has no section {missing[0]!r}")
    header = parsed["Average Value Weighted Returns -- Monthly"][0]
    columns = {field: dict(monthly_rows(parsed[title])) for title, field in INDUSTRY_SECTIONS.items()}
    rows = []
    for month in sorted(columns["vw"]):
        for index, industry in enumerate(header):
            record = {"month": month, "industry": industry}
            for field, by_month in columns.items():
                value = by_month[month][index]
                if value in MISSING:
                    raise ValueError(f"{industry} has no {field} in {month}")
                record[field] = value
            rows.append(record)
    return rows


def factor_rows(text: str) -> list[dict[str, str]]:
    parsed = sections(text)
    header, _ = next(iter(parsed.values()))
    table = next(table for table in parsed.values() if monthly_rows(table))
    names = {"Mkt-RF": "mkt_rf", "SMB": "smb", "HML": "hml", "RF": "rf"}
    return [
        {"month": month, **{names[name]: value for name, value in zip(header, values, strict=True)}}
        for month, values in monthly_rows(table)
    ]


def _write(name: str, rows: list[dict[str, str]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    with gzip.GzipFile(REFERENCE_DIR / name, "wb", mtime=0) as handle:  # mtime 0: identical bytes on rebuild
        handle.write(buffer.getvalue().encode("utf-8"))


def _read_zip(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")


def _download(name: str) -> str:
    request = urllib.request.Request(BASE_URL + name, headers={"User-Agent": "meridian-investment-platform"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return _read_zip(response.read())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", type=Path, help="a directory holding the two library CSV files")
    args = parser.parse_args(argv)
    if args.source:
        industries = (args.source / "12_Industry_Portfolios.csv").read_text(encoding="utf-8", errors="replace")
        factors = (args.source / "F-F_Research_Data_Factors.csv").read_text(encoding="utf-8", errors="replace")
    else:
        industries, factors = _download(INDUSTRY_ZIP), _download(FACTOR_ZIP)
    rows = industry_rows(industries)
    _write(INDUSTRY_FILE, rows)
    factor_table = factor_rows(factors)
    _write(FACTOR_FILE, factor_table)
    print(f"{INDUSTRY_FILE}: {len(rows):,} rows; {FACTOR_FILE}: {len(factor_table):,} months")


if __name__ == "__main__":  # pragma: no cover
    main()
