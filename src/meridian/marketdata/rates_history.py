"""Real rates history: the US Treasury par curve and the Federal Reserve's fitted curve.

Everything else in Meridian's demonstration runs on a synthetic market, built so that
the truth is known and every estimator can be checked against it. Rates are
different. The history of the US yield curve is public, and a rates engine that has
never met it has not been tested.

Two public-domain datasets are packaged (see ``meridian.devtools.fetch_rates``):

- :func:`treasury_par_yields` - the Treasury's daily **par** yields at constant
  maturities, 1 month to 30 years, since 1990. They are bond-equivalent (semi-annual)
  yields, published in percent, with a column only where the Treasury published one.
  The 1-month column starts in 2001, the 20-year returns in 1993, the 30-year pauses
  from 2002 to 2006.
- :func:`gsw_curve` - the Gurkaynak-Sack-Wright curve (Federal Reserve Board, FEDS
  2006-28). These are the six daily parameters of a Svensson curve fitted to
  off-the-run Treasuries, with the continuously compounded zero yields it implies.
  It is an independent fit of the same market, and it is what our Nelson-Siegel-Svensson
  code is checked against.
"""

from __future__ import annotations

import csv
import gzip
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

REFERENCE_DIR = Path(__file__).with_name("reference")
TREASURY_FILE = "treasury_par_yields.csv.gz"
GSW_FILE = "gsw_svensson.csv.gz"

TREASURY_TENORS: tuple[str, ...] = (
    "1M",
    "6W",
    "2M",
    "3M",
    "4M",
    "6M",
    "1Y",
    "2Y",
    "3Y",
    "5Y",
    "7Y",
    "10Y",
    "20Y",
    "30Y",
)
TENOR_YEARS: dict[str, float] = {
    "1M": 1 / 12, "6W": 1.5 / 12, "2M": 2 / 12, "3M": 3 / 12, "4M": 4 / 12, "6M": 0.5,
    "1Y": 1.0, "2Y": 2.0, "3Y": 3.0, "5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "20Y": 20.0, "30Y": 30.0,
}  # fmt: skip
GSW_TENORS: tuple[int, ...] = (1, 2, 3, 5, 7, 10, 15, 20, 30)
SOURCES = {
    "treasury": "US Department of the Treasury, Daily Treasury Par Yield Curve Rates (public domain)",
    "gsw": "Gurkaynak, Sack and Wright (2007), The U.S. Treasury Yield Curve: 1961 to the Present, "
    "Federal Reserve Board FEDS 2006-28, data file feds200628.csv (public domain)",
}


@dataclass(frozen=True, slots=True)
class ParCurve:
    """One day's Treasury par curve: tenors in years and yields as decimals, published points only."""

    day: date
    tenors: tuple[float, ...]
    labels: tuple[str, ...]
    yields: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.tenors)


@dataclass(frozen=True, slots=True)
class SvenssonParameters:
    """The GSW parameters for one day, as published (yields in percent, tau in years)."""

    day: date
    beta0: float
    beta1: float
    beta2: float
    beta3: float
    tau1: float
    tau2: float


def _read(name: str) -> list[dict[str, str]]:
    with gzip.open(REFERENCE_DIR / name, "rt", encoding="utf-8") as handle:
        return list(csv.DictReader(io.StringIO(handle.read())))


@lru_cache(maxsize=1)
def treasury_par_yields() -> tuple[ParCurve, ...]:
    """Every published day of the Treasury par curve since 1990, in date order."""
    curves = []
    for row in _read(TREASURY_FILE):
        points = [(TENOR_YEARS[label], label, float(row[label]) / 100) for label in TREASURY_TENORS if row[label]]
        points.sort()
        curves.append(
            ParCurve(
                date.fromisoformat(row["date"]),
                tuple(point[0] for point in points),
                tuple(point[1] for point in points),
                tuple(point[2] for point in points),
            )
        )
    return tuple(curves)


def par_curve_on(day: date) -> ParCurve:
    """The curve published on a day, or on the last day before it."""
    curves = treasury_par_yields()
    days = [curve.day for curve in curves]
    index = int(np.searchsorted(np.array(days, dtype="datetime64[D]"), np.datetime64(day), side="right")) - 1
    if index < 0:
        raise LookupError(f"No Treasury curve on or before {day}")
    return curves[index]


def treasury_matrix(labels: Sequence[str], start: date | None = None) -> tuple[list[date], np.ndarray]:
    """Days on which every one of ``labels`` was published, and the yields as a (days x tenors) array."""
    days: list[date] = []
    rows: list[list[float]] = []
    for curve in treasury_par_yields():
        if start and curve.day < start:
            continue
        lookup = dict(zip(curve.labels, curve.yields, strict=True))
        if all(label in lookup for label in labels):
            days.append(curve.day)
            rows.append([lookup[label] for label in labels])
    return days, np.array(rows)


@lru_cache(maxsize=1)
def gsw_curve() -> tuple[tuple[SvenssonParameters, ...], np.ndarray]:
    """The GSW parameters for every day since 1990, and their published zero yields (percent)."""
    parameters: list[SvenssonParameters] = []
    yields: list[list[float]] = []
    for row in _read(GSW_FILE):
        parameters.append(
            SvenssonParameters(
                date.fromisoformat(row["date"]),
                *(float(row[key]) for key in ("BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2")),
            )
        )
        # the long end is "NA" in years without bonds long enough to fit it
        yields.append(
            [float(row[f"SVENY{tenor:02d}"]) if row[f"SVENY{tenor:02d}"] != "NA" else np.nan for tenor in GSW_TENORS]
        )
    return tuple(parameters), np.array(yields)
