"""The benchmark: what the portfolio is measured against, built the way index providers build one.

Attribution is only as good as the benchmark's own decomposition, so the
benchmark here is not a single return series but a set of constituents with
weights, sectors, regions and currencies:

* **Meridian World Equity** - a synthetic, capitalisation-weighted index of
  thirty-six stocks in five regions and eight sectors. Six of them are the
  demonstration book's own single stocks; thirty are companions generated in the
  *same* synthetic market, sharing its market and sector factors, so the index
  moves with the book as a real index moves with the stocks in it. Weights drift
  with total return, as a cap-weighted index's do; dividends are reinvested.
* **The policy benchmark** - the account's mandate: 80% world equity, 15% the
  US Treasury the account can hold, 5% cash, rebalanced to policy at the start of
  every month.

Each constituent's daily return is split into a local total return and the
currency move on the closing local value - the same convention as the
portfolio's own decomposition (ADR 0017) - so the currency effect in the
attribution compares like with like.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..accounting.income import accrued_per_unit, coupon_schedule
from ..accounting.sources import FxSource
from ..core.exceptions import ValidationError
from ..domain.instruments import Bond, instrument_price_scale
from ..marketdata.series import TimeSeries

REGIONS = {
    "US": "North America",
    "GB": "United Kingdom",
    "DE": "Europe ex UK",
    "FR": "Europe ex UK",
    "NL": "Europe ex UK",
    "CH": "Switzerland",
    "JP": "Japan",
}
FIXED_INCOME = "Fixed income"
CASH = "Cash"


@dataclass(frozen=True, slots=True)
class Constituent:
    instrument_id: str
    name: str
    sector: str
    region: str
    currency: str
    calendar: str
    market_cap: float  # USD billions at the base date


@dataclass(frozen=True, slots=True)
class BenchmarkPiece:
    """One constituent (or sleeve) of the benchmark over one day."""

    key: str
    sector: str
    region: str
    currency: str
    weight: float  # at the start of the day
    local: float  # local total return
    fx: float  # the currency move on the closing local value: x * (1 + local)

    @property
    def rate(self) -> float:
        return self.local + self.fx


@dataclass(frozen=True)
class BenchmarkDay:
    day: date
    pieces: tuple[BenchmarkPiece, ...]

    @property
    def rate(self) -> float:
        return sum(piece.weight * piece.rate for piece in self.pieces)

    def weights(self, by: str = "sector") -> dict[str, float]:
        found: dict[str, float] = defaultdict(float)
        for piece in self.pieces:
            found[getattr(piece, by)] += piece.weight
        return dict(found)


def _level(series: TimeSeries, day: date) -> float | None:
    found = series.as_of(day, max_age_days=10)
    return float(found.value) if found else None


@dataclass
class EquityIndex:
    """A capitalisation-weighted total return index over a set of constituents."""

    name: str
    constituents: tuple[Constituent, ...]
    total_return: Mapping[str, TimeSeries]  # one total return level series per constituent, local currency
    fx: FxSource
    base_currency: str = "USD"

    def __post_init__(self) -> None:
        missing = [item.instrument_id for item in self.constituents if item.instrument_id not in self.total_return]
        if missing:
            raise ValidationError(f"{self.name}: no total return series for {', '.join(missing)}")

    def rate(self, currency: str, day: date) -> float:
        return float(self.fx.rate(currency, self.base_currency, day))

    def days(self, valuation_days: Sequence[date]) -> list[tuple[date, list[tuple[Constituent, float, float, float]]]]:
        """For each day after the first: (constituent, opening weight, local return, currency move)."""
        values = {item.instrument_id: item.market_cap for item in self.constituents}
        previous_day = valuation_days[0]
        levels = {
            item.instrument_id: _level(self.total_return[item.instrument_id], previous_day)
            for item in self.constituents
        }
        rates = {item.instrument_id: self.rate(item.currency, previous_day) for item in self.constituents}
        output = []
        for day in valuation_days[1:]:
            total = sum(values.values())
            rows = []
            for item in self.constituents:
                key = item.instrument_id
                level = _level(self.total_return[key], day)
                rate = self.rate(item.currency, day)
                before = levels[key]
                local = level / before - 1.0 if level is not None and before else 0.0
                move = rate / rates[key] - 1.0
                rows.append((item, values[key] / total, local, move * (1.0 + local)))
                values[key] *= (1.0 + local) * (1.0 + move)
                if level is not None:
                    levels[key] = level
                rates[key] = rate
            output.append((day, rows))
            previous_day = day
        return output


@dataclass
class PolicyBenchmark:
    """A blend of sleeves rebalanced to fixed weights at the start of every month."""

    name: str
    equity: EquityIndex
    policy: Mapping[str, float]  # "equity", "fixed income", "cash"
    bond_return: Mapping[date, float] = field(default_factory=dict)  # daily total return of the bond sleeve

    def __post_init__(self) -> None:
        if abs(sum(self.policy.values()) - 1.0) > 1e-9:
            raise ValidationError(f"{self.name}: policy weights sum to {sum(self.policy.values())}, not 1")

    def build(self, valuation_days: Sequence[date]) -> list[BenchmarkDay]:
        sleeves = dict(self.policy)
        month = (valuation_days[0].year, valuation_days[0].month)
        output: list[BenchmarkDay] = []
        for day, rows in self.equity.days(valuation_days):
            if (day.year, day.month) != month:
                month = (day.year, day.month)
                total = sum(sleeves.values())
                sleeves = {key: total * weight for key, weight in self.policy.items()}
            total = sum(sleeves.values())
            pieces = [
                BenchmarkPiece(
                    item.instrument_id,
                    item.sector,
                    item.region,
                    item.currency,
                    sleeves["equity"] / total * weight,
                    local,
                    move,
                )
                for item, weight, local, move in rows
            ]
            bond = self.bond_return.get(day, 0.0)
            pieces.append(
                BenchmarkPiece(
                    "TREASURY", FIXED_INCOME, FIXED_INCOME, "USD", sleeves["fixed income"] / total, bond, 0.0
                )
            )
            pieces.append(BenchmarkPiece("CASH", CASH, CASH, "USD", sleeves["cash"] / total, 0.0, 0.0))
            equity_return = sum(weight * (local + move) for _, weight, local, move in rows)
            sleeves["equity"] *= 1.0 + equity_return
            sleeves["fixed income"] *= 1.0 + bond
            output.append(BenchmarkDay(day, tuple(pieces)))
        return output


def bond_total_returns(bond: Bond, clean_prices: TimeSeries, days: Sequence[date]) -> dict[date, float]:
    """Daily total return of holding one unit of a bond: dirty price change plus coupons received."""
    scale = instrument_price_scale(bond)
    coupons: dict[date, float] = defaultdict(float)
    for payment in coupon_schedule(bond, days[0], days[-1]):
        coupons[payment.payment_date] += float(payment.per_unit)

    def dirty(day: date) -> float | None:
        clean = clean_prices.as_of(day, max_age_days=10)
        if clean is None:
            return None
        return float(clean.value * scale + accrued_per_unit(bond, day))

    output: dict[date, float] = {}
    previous = dirty(days[0])
    last_day = days[0]
    for day in days[1:]:
        current = dirty(day)
        paid = sum(amount for when, amount in coupons.items() if last_day < when <= day)
        output[day] = (current + paid) / previous - 1.0 if current is not None and previous else 0.0
        if current is not None:
            previous = current
        last_day = day
    return output


def index_level(days: Sequence[BenchmarkDay], base: float = 100.0) -> list[tuple[date, float]]:
    level, points = base, []
    for item in days:
        level *= 1.0 + item.rate
        points.append((item.day, level))
    return points


def annual_volatility(rates: Sequence[float]) -> float:
    if len(rates) < 2:
        return 0.0
    mean = sum(rates) / len(rates)
    variance = sum((value - mean) ** 2 for value in rates) / (len(rates) - 1)
    return math.sqrt(variance * 252)


def region_of(country: str | None) -> str:
    return REGIONS.get((country or "").upper(), "Other")


def as_float(value: Decimal | float) -> float:
    return float(value)
