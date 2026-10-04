"""A century of US equity returns: Kenneth French's industry portfolios and the Fama-French factors.

Two tables from the Kenneth R. French Data Library are packaged (rebuilt by
``meridian.devtools.fetch_french``), monthly from July 1926:

- the **12 industry portfolios**: each industry's value-weighted and
  equal-weighted return, its number of firms, and their average market
  capitalisation at the start of the month. Number times average size is the
  industry's market value, so the twelve together are a capitalisation-weighted
  index of every NYSE, AMEX and NASDAQ stock that can be rebuilt from its parts;
- the **Fama-French three factors**: the market's return over the one-month
  Treasury bill, size (SMB), value (HML), and the bill rate itself.

They come from CRSP via the library, which publishes them for research and
teaching and asks that they be cited. Returns are stored as the library prints
them, in per cent, and converted to fractions when loaded.

The data is what Day 4 never had: a real benchmark built from real constituents,
and real portfolios to attribute against it over a century, not a synthetic year.
"""

from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..core.exceptions import ValidationError

REFERENCE_DIR = Path(__file__).with_name("reference")
INDUSTRY_FILE = "french_12_industries.csv.gz"
FACTOR_FILE = "french_ff3_factors.csv.gz"
DAILY_INDUSTRY_FILE = "french_12_industries_daily.csv.gz"
DAILY_FACTOR_FILE = "french_ff3_factors_daily.csv.gz"
SOURCE = "Kenneth R. French Data Library (CRSP), 12 industry portfolios and Fama-French factors"

#: The library's industry codes and what they hold (its SIC definitions).
INDUSTRY_NAMES: dict[str, str] = {
    "NoDur": "Consumer non-durables",
    "Durbl": "Consumer durables",
    "Manuf": "Manufacturing",
    "Enrgy": "Energy",
    "Chems": "Chemicals",
    "BusEq": "Business equipment",
    "Telcm": "Telecoms",
    "Utils": "Utilities",
    "Shops": "Retail and services",
    "Hlth": "Healthcare",
    "Money": "Finance",
    "Other": "Other",
}


def month_end(year_month: str) -> date:
    """``"192607"`` as the last day of July 1926."""
    year, month = int(year_month[:4]), int(year_month[4:])
    following = date(year + month // 12, month % 12 + 1, 1)
    return following - timedelta(days=1)


@dataclass(frozen=True)
class IndustryMonth:
    """One industry in one month: returns as fractions, market value in USD millions at the start."""

    value_weighted: float
    equal_weighted: float
    firms: int
    average_size: float

    @property
    def market_value(self) -> float:
        return self.firms * self.average_size


@dataclass(frozen=True)
class FactorMonth:
    market_excess: float
    smb: float
    hml: float
    risk_free: float

    @property
    def market(self) -> float:
        """The market's total return: its excess return plus the bill."""
        return self.market_excess + self.risk_free


@dataclass(frozen=True)
class FrenchHistory:
    months: tuple[date, ...]  # month ends
    industries: tuple[str, ...]
    data: dict[date, dict[str, IndustryMonth]]
    factors: dict[date, FactorMonth]

    def between(self, start: date, end: date) -> FrenchHistory:
        """The months whose month end falls in ``(start, end]``."""
        months = tuple(month for month in self.months if start < month <= end)
        if not months:
            raise ValidationError(f"no months between {start} and {end}")
        return FrenchHistory(
            months,
            self.industries,
            {month: self.data[month] for month in months},
            {month: self.factors[month] for month in months if month in self.factors},
        )

    def weights(self, month: date) -> dict[str, float]:
        """Each industry's share of the market's value at the start of ``month``."""
        values = {name: item.market_value for name, item in self.data[month].items()}
        total = sum(values.values())
        return {name: value / total for name, value in values.items()}

    def firm_shares(self, month: date) -> dict[str, float]:
        """Each industry's share of the number of firms: its weight in an equal-weighted market."""
        counts = {name: item.firms for name, item in self.data[month].items()}
        total = sum(counts.values())
        return {name: count / total for name, count in counts.items()}

    def cap_weighted(self, month: date) -> float:
        """The market rebuilt from its twelve industries, weighted by their value at the start of the month."""
        weights = self.weights(month)
        return sum(weights[name] * item.value_weighted for name, item in self.data[month].items())

    def equal_weighted(self, month: date) -> float:
        """Every stock in equal weight: each industry's equal-weighted return by its share of firms."""
        shares = self.firm_shares(month)
        return sum(shares[name] * item.equal_weighted for name, item in self.data[month].items())


def _open(name: str) -> list[dict[str, str]]:
    path = REFERENCE_DIR / name
    if not path.exists():
        raise ValidationError(f"{name} is not packaged; run python -m meridian.devtools.fetch_french")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def french_history() -> FrenchHistory:
    """The packaged industries and factors, every month from July 1926."""
    data: dict[date, dict[str, IndustryMonth]] = {}
    industries: list[str] = []
    for row in _open(INDUSTRY_FILE):
        month = month_end(row["month"])
        if row["industry"] not in industries:
            industries.append(row["industry"])
        data.setdefault(month, {})[row["industry"]] = IndustryMonth(
            float(row["vw"]) / 100.0, float(row["ew"]) / 100.0, int(row["firms"]), float(row["size"])
        )
    factors = {
        month_end(row["month"]): FactorMonth(
            float(row["mkt_rf"]) / 100.0, float(row["smb"]) / 100.0, float(row["hml"]) / 100.0, float(row["rf"]) / 100.0
        )
        for row in _open(FACTOR_FILE)
    }
    months = tuple(sorted(data))
    incomplete = [month for month in months if len(data[month]) != len(industries)]
    if incomplete:
        raise ValidationError(f"the industry table is incomplete in {incomplete[0]:%Y-%m}")
    return FrenchHistory(months, tuple(industries), data, factors)


@dataclass(frozen=True)
class FrenchDaily:
    """Every trading day since 1 July 1926: the industries' value-weighted returns and the factors (fractions)."""

    days: tuple[date, ...]
    industries: tuple[str, ...]
    returns: np.ndarray  # T x 12
    market_excess: np.ndarray  # T
    risk_free: np.ndarray  # T
    smb: np.ndarray
    hml: np.ndarray

    @property
    def market(self) -> np.ndarray:
        """The market's total daily return: its excess return plus the bill's daily rate."""
        return self.market_excess + self.risk_free

    def industry(self, name: str) -> np.ndarray:
        return self.returns[:, self.industries.index(name)]

    def index_of(self, day: date) -> int:
        """The position of the first trading day on or after ``day``."""
        return int(np.searchsorted(np.array([d.toordinal() for d in self.days]), day.toordinal()))


def _day(text: str) -> date:
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


@lru_cache(maxsize=1)
def french_daily() -> FrenchDaily:
    """The packaged daily tables, aligned day by day."""
    industry_rows = _open(DAILY_INDUSTRY_FILE)
    factor_rows = {row["day"]: row for row in _open(DAILY_FACTOR_FILE)}
    industries = tuple(key for key in industry_rows[0] if key != "day")
    shared = [row for row in industry_rows if row["day"] in factor_rows]
    if len(shared) != len(industry_rows):
        raise ValidationError("the daily industry and factor tables cover different days")
    days = tuple(_day(row["day"]) for row in shared)
    returns = np.array([[float(row[name]) for name in industries] for row in shared]) / 100.0
    factors = (
        np.array([[float(factor_rows[row["day"]][key]) for key in ("mkt_rf", "rf", "smb", "hml")] for row in shared])
        / 100.0
    )
    return FrenchDaily(days, industries, returns, factors[:, 0], factors[:, 1], factors[:, 2], factors[:, 3])
