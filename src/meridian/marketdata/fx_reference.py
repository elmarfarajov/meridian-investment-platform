"""Real FX reference rates: the ECB's euro fixings and the Federal Reserve's noon rates.

The synthetic market shows that the quality rules find the faults its author planted.
Real data shows what else is out there. Two public datasets are packaged (see
``meridian.devtools.fetch_rates``):

- :func:`ecb_rates` - the **ECB euro foreign exchange reference rates**. Every currency
  the ECB has fixed against the euro since 4 January 1999, set at 14:15 CET from a
  concertation among central banks. They are quoted as units of currency per euro. A
  currency appears only while the ECB fixed it, so the series stop and start with euro
  adoptions, redenominations and suspensions.
- :func:`fed_rates` - the **Federal Reserve's H.10** noon buying rates in New York (via
  FRED), for the dollar against the euro, sterling, the Swiss franc and the yen. They
  are an independent second source of the same rates, fixed 3h45 later (2h45 when the clocks disagree) in
  another city.

Both are returned as series keyed by the market's pair convention (``EURUSD``,
``GBPUSD``, ``USDJPY``), so the two sources can be compared directly.
"""

from __future__ import annotations

import csv
import gzip
import io
from datetime import date
from decimal import Decimal
from functools import lru_cache

from .rates_history import REFERENCE_DIR
from .series import TimeSeries

ECB_FILE = "ecb_reference_rates.csv.gz"
FED_FILE = "fed_h10_noon_rates.csv.gz"

#: FRED series and the pair each one is, with whether FRED quotes it the other way round.
FED_SERIES: dict[str, tuple[str, bool]] = {
    "DEXUSEU": ("EURUSD", False),  # US dollars per euro
    "DEXUSUK": ("GBPUSD", False),  # US dollars per pound
    "DEXSZUS": ("USDCHF", False),  # Swiss francs per dollar
    "DEXJPUS": ("USDJPY", False),  # yen per dollar
}
SOURCES = {
    "ecb": "European Central Bank, euro foreign exchange reference rates (reuse permitted with the source cited)",
    "fed": "Board of Governors of the Federal Reserve System, H.10 Foreign Exchange Rates, via FRED (public domain)",
}


def _read(name: str) -> list[dict[str, str]]:
    with gzip.open(REFERENCE_DIR / name, "rt", encoding="utf-8") as handle:
        return list(csv.DictReader(io.StringIO(handle.read())))


def _columns(rows: list[dict[str, str]]) -> list[str]:
    return [name for name in rows[0] if name != "date"] if rows else []


@lru_cache(maxsize=1)
def ecb_rates() -> dict[str, TimeSeries]:
    """Every ECB fixing as a series ``EURxxx``: units of currency per euro, only on days it was fixed."""
    rows = _read(ECB_FILE)
    series: dict[str, TimeSeries] = {}
    for currency in _columns(rows):
        points = [(date.fromisoformat(row["date"]), Decimal(row[currency])) for row in rows if row[currency]]
        if points:
            series[f"EUR{currency}"] = TimeSeries(points, name=f"EUR{currency}")
    return series


@lru_cache(maxsize=1)
def fed_rates() -> dict[str, TimeSeries]:
    """The Federal Reserve's noon rates, keyed by pair, only on days a rate was published."""
    rows = _read(FED_FILE)
    series: dict[str, TimeSeries] = {}
    for column, (pair, inverted) in FED_SERIES.items():
        points = []
        for row in rows:
            if row.get(column):
                value = Decimal(row[column])
                points.append((date.fromisoformat(row["date"]), Decimal(1) / value if inverted else value))
        series[pair] = TimeSeries(points, name=f"{pair} (Fed noon)")
    return series


def ecb_cross(base: str, quote: str) -> TimeSeries:
    """A cross derived from two ECB fixings on every day both exist: ``base``/``quote`` = EURquote / EURbase."""
    rates = ecb_rates()
    left = rates[f"EUR{base}"] if base != "EUR" else None
    right = rates[f"EUR{quote}"] if quote != "EUR" else None
    if left is None and right is not None:
        return right.with_name(f"EUR{quote}")
    if right is None and left is not None:
        return TimeSeries(((point.day, Decimal(1) / point.value) for point in left), name=f"{base}EUR")
    assert left is not None and right is not None
    points = [(point.day, right[point.day] / point.value) for point in left if point.day in right]
    return TimeSeries(points, name=f"{base}{quote} (ECB cross)")
