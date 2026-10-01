"""Rebuild the packaged rates and FX history from its public sources.

Four datasets ship with the package:

- the **US Treasury daily par yield curve** (constant-maturity par yields, 1 month to 30
  years, from 1990), published by the Treasury's Office of Debt Management;
- the **Gurkaynak-Sack-Wright Svensson curve** (Federal Reserve Board, FEDS 2006-28): the
  daily fitted parameters and the zero-coupon yields they imply;
- the **ECB euro foreign exchange reference rates**: every currency the ECB has fixed
  against the euro since 4 January 1999, at 14:15 CET (reuse permitted with the source
  cited);
- the **Federal Reserve H.10** noon buying rates in New York for the dollar against the
  euro, sterling, the Swiss franc and the yen, via FRED (public domain).

They are packaged, rather than fetched at run time, so that every chart and test is
reproducible offline and the numbers in the documentation do not drift. This script
is how they are refreshed:

    python -m meridian.devtools.fetch_rates            # download and rebuild
    python -m meridian.devtools.fetch_rates --from DIR # rebuild from files already downloaded
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path

from ..marketdata.fx_reference import ECB_FILE, FED_FILE, FED_SERIES
from ..marketdata.rates_history import GSW_FILE, GSW_TENORS, REFERENCE_DIR, TREASURY_FILE, TREASURY_TENORS

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
    "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)
GSW_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FIRST_YEAR = 1990

# The Treasury has renamed a column or two over the years; map every heading to a tenor label
_HEADINGS = {
    "1 Mo": "1M",
    "1.5 Month": "6W",
    "2 Mo": "2M",
    "3 Mo": "3M",
    "4 Mo": "4M",
    "6 Mo": "6M",
    "1 Yr": "1Y",
    "2 Yr": "2Y",
    "3 Yr": "3Y",
    "5 Yr": "5Y",
    "7 Yr": "7Y",
    "10 Yr": "10Y",
    "20 Yr": "20Y",
    "30 Yr": "30Y",
}


def _download(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "meridian-investment-platform"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return str(response.read().decode("utf-8-sig"))


def treasury_rows(texts: list[str]) -> list[dict[str, str]]:
    """Every day of every year, keyed by tenor label, in date order."""
    rows: dict[date, dict[str, str]] = {}
    for text in texts:
        for record in csv.DictReader(io.StringIO(text)):
            day = datetime.strptime(record["Date"], "%m/%d/%Y").date()
            values = {_HEADINGS[key]: value.strip() for key, value in record.items() if key in _HEADINGS}
            rows[day] = {"date": day.isoformat(), **{tenor: values.get(tenor, "") for tenor in TREASURY_TENORS}}
    return [rows[day] for day in sorted(rows)]


def gsw_rows(text: str, first: date = date(FIRST_YEAR, 1, 1)) -> list[dict[str, str]]:
    """The parameters and a selection of zero yields, from the first date on."""
    lines = text.splitlines()
    header = next(index for index, line in enumerate(lines) if line.startswith("Date,"))
    wanted = ["BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2", *(f"SVENY{t:02d}" for t in GSW_TENORS)]
    rows = []
    for record in csv.DictReader(io.StringIO("\n".join(lines[header:]))):
        day = date.fromisoformat(record["Date"])
        if day < first or not record.get("BETA0") or record["BETA0"] == "NA":
            continue
        # parameters at full precision; yields to a millionth of a percent, which is ample
        values = {key: record[key] for key in wanted}
        for key in wanted[6:]:
            values[key] = values[key] if values[key] == "NA" else f"{float(values[key]):.6f}"
        rows.append({"date": day.isoformat(), **values})
    return rows


def ecb_rows(text: str) -> list[dict[str, str]]:
    """The ECB's wide file (newest first, "N/A" for no fixing) in date order, blanks for no fixing."""
    reader = csv.reader(io.StringIO(text))
    header = [name.strip() for name in next(reader) if name.strip()]
    rows = []
    for record in reader:
        if not record or not record[0].strip():
            continue
        values = [value.strip() for value in record[: len(header)]]
        row = {"date": values[0]}
        row.update(
            {name: ("" if value in {"N/A", ""} else value) for name, value in zip(header[1:], values[1:], strict=False)}
        )
        rows.append(row)
    return sorted(rows, key=lambda row: row["date"])


def fred_rows(texts: dict[str, str]) -> list[dict[str, str]]:
    """FRED's one-series files, joined on the date; FRED marks a holiday with an empty value."""
    joined: dict[str, dict[str, str]] = {}
    for series, text in texts.items():
        for record in csv.DictReader(io.StringIO(text)):
            day = record.get("observation_date") or record.get("DATE") or ""
            value = (record.get(series) or "").strip()
            joined.setdefault(day, {})[series] = "" if value in {".", ""} else value
    return [{"date": day, **{series: joined[day].get(series, "") for series in texts}} for day in sorted(joined)]


def write_gzip_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    # mtime=0 keeps the file byte-identical when the data has not changed
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as target:
        target.write(buffer.getvalue().encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source", type=Path, help="a directory holding tsy_YYYY.csv and feds200628.csv")
    parser.add_argument("--last-year", type=int, default=date.today().year)
    arguments = parser.parse_args(argv)

    years = range(FIRST_YEAR, arguments.last_year + 1)
    if arguments.source:
        texts = [
            (arguments.source / f"tsy_{year}.csv").read_text(encoding="utf-8-sig")
            for year in years
            if (arguments.source / f"tsy_{year}.csv").exists()
        ]
        gsw = (arguments.source / "feds200628.csv").read_text(encoding="utf-8-sig")
        ecb = (arguments.source / "eurofxref-hist.csv").read_text(encoding="utf-8-sig")
        fred = {series: (arguments.source / f"{series}.csv").read_text(encoding="utf-8-sig") for series in FED_SERIES}
    else:
        texts = [_download(TREASURY_URL.format(year=year)) for year in years]
        gsw = _download(GSW_URL)
        ecb = _ecb_download()
        fred = {series: _download(FRED_URL.format(series=series)) for series in FED_SERIES}

    treasury = treasury_rows(texts)
    fitted = gsw_rows(gsw)
    write_gzip_csv(REFERENCE_DIR / TREASURY_FILE, treasury)
    write_gzip_csv(REFERENCE_DIR / GSW_FILE, fitted)
    print(f"Treasury par yields: {len(treasury)} days, {treasury[0]['date']} to {treasury[-1]['date']}")
    print(f"GSW Svensson curve: {len(fitted)} days, {fitted[0]['date']} to {fitted[-1]['date']}")
    reference = ecb_rows(ecb)
    noon = fred_rows(fred)
    write_gzip_csv(REFERENCE_DIR / ECB_FILE, reference)
    write_gzip_csv(REFERENCE_DIR / FED_FILE, noon)
    print(f"ECB reference rates: {len(reference)} days, {reference[0]['date']} to {reference[-1]['date']}")
    print(f"Federal Reserve H.10: {len(noon)} days, {noon[0]['date']} to {noon[-1]['date']}")
    return 0


def _ecb_download() -> str:
    request = urllib.request.Request(ECB_URL, headers={"User-Agent": "meridian-investment-platform"})
    with urllib.request.urlopen(request, timeout=120) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    return archive.read(archive.namelist()[0]).decode("utf-8-sig")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
