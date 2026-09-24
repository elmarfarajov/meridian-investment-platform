"""Where the accounting layer gets its prices and exchange rates.

The engine and the valuation never read a vendor feed directly. They ask two
narrow questions - "what was this security worth on this day?" and "what was
this currency worth in that one?" - through the protocols below, so the same
code runs against the golden copy from the end-of-day pricing run, against a
database, or against a three-line dictionary in a unit test.

Both lookups are *as of*: a price is the latest one on or before the day,
provided it is not older than a staleness limit. A holding in a market that is
closed for a holiday is valued at its last close, which is correct; a holding
whose price stopped arriving a fortnight ago is not valued at all, which is
also correct - a missing price is visible, a stale one is not.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Protocol

from ..core.currency import get_currency
from ..core.exceptions import RateNotFoundError
from ..marketdata.fx_history import FxHistory
from ..marketdata.quotes import MarketDataset
from ..marketdata.series import TimeSeries


class PriceSource(Protocol):
    def price(self, instrument_id: str, day: date) -> Decimal | None: ...

    def price_date(self, instrument_id: str, day: date) -> date | None: ...


class FxSource(Protocol):
    def rate(self, from_currency: str, to_currency: str, day: date) -> Decimal: ...


class SeriesPrices:
    """Prices from a set of close series, looked up as of a date with a staleness limit."""

    def __init__(self, series: Mapping[str, TimeSeries], *, max_age_days: int = 7) -> None:
        self._series = dict(series)
        self.max_age_days = max_age_days

    @classmethod
    def from_dataset(cls, dataset: MarketDataset, *, max_age_days: int = 7) -> SeriesPrices:
        return cls({key: dataset.close_series(key) for key in dataset.instruments}, max_age_days=max_age_days)

    def with_series(self, instrument_id: str, series: TimeSeries) -> SeriesPrices:
        merged = dict(self._series)
        merged[instrument_id] = series
        return SeriesPrices(merged, max_age_days=self.max_age_days)

    @property
    def instruments(self) -> tuple[str, ...]:
        return tuple(sorted(self._series))

    def series(self, instrument_id: str) -> TimeSeries | None:
        return self._series.get(instrument_id)

    def price(self, instrument_id: str, day: date) -> Decimal | None:
        series = self._series.get(instrument_id)
        if series is None:
            return None
        found = series.as_of(day, max_age_days=self.max_age_days)
        return found.value if found else None

    def price_date(self, instrument_id: str, day: date) -> date | None:
        series = self._series.get(instrument_id)
        if series is None:
            return None
        found = series.as_of(day, max_age_days=self.max_age_days)
        return found.day if found else None


class HistoryFx:
    """Exchange rates from an :class:`FxHistory`, cached per day because the valuation asks thousands of times."""

    def __init__(self, history: FxHistory) -> None:
        self.history = history
        self._cached = lru_cache(maxsize=32_768)(self._lookup)

    def _lookup(self, from_currency: str, to_currency: str, day: date) -> Decimal:
        return self.history.rate(from_currency, to_currency, day)

    def rate(self, from_currency: str, to_currency: str, day: date) -> Decimal:
        source, target = get_currency(from_currency).code, get_currency(to_currency).code
        if source == target:
            return Decimal(1)
        return self._cached(source, target, day)


class FixedFx:
    """Constant rates quoted against one pivot currency, for tests and worked examples.

    ``rates`` maps a currency to its value in the pivot: ``{"EUR": 1.10}`` means
    one euro buys 1.10 of the pivot. A dated override can be given as
    ``{("EUR", date): 1.12}``, which applies from that date on.
    """

    def __init__(self, rates: Mapping[object, object], *, pivot: str = "USD") -> None:
        self.pivot = get_currency(pivot).code
        self._flat: dict[str, Decimal] = {}
        self._dated: dict[str, list[tuple[date, Decimal]]] = {}
        for key, value in rates.items():
            rate = Decimal(str(value))
            if isinstance(key, tuple):
                code, start = key
                self._dated.setdefault(get_currency(str(code)).code, []).append((start, rate))
            else:
                self._flat[get_currency(str(key)).code] = rate
        for items in self._dated.values():
            items.sort()

    def _to_pivot(self, currency: str, day: date) -> Decimal:
        if currency == self.pivot:
            return Decimal(1)
        value = self._flat.get(currency)
        for start, rate in self._dated.get(currency, []):
            if start <= day:
                value = rate
        if value is None:
            raise RateNotFoundError(f"no rate for {currency} on {day}")
        return value

    def rate(self, from_currency: str, to_currency: str, day: date) -> Decimal:
        source, target = get_currency(from_currency).code, get_currency(to_currency).code
        if source == target:
            return Decimal(1)
        return self._to_pivot(source, day) / self._to_pivot(target, day)


class FixedPrices:
    """Prices from a dictionary: ``{instrument: {date: price}}``, looked up as of a date."""

    def __init__(self, prices: Mapping[str, Mapping[date, object]], *, max_age_days: int = 10) -> None:
        self._series = {
            key: TimeSeries([(day, Decimal(str(value))) for day, value in values.items()], name=key)
            for key, values in prices.items()
        }
        self.max_age_days = max_age_days

    def price(self, instrument_id: str, day: date) -> Decimal | None:
        series = self._series.get(instrument_id)
        if series is None:
            return None
        found = series.as_of(day, max_age_days=self.max_age_days)
        return found.value if found else None

    def price_date(self, instrument_id: str, day: date) -> date | None:
        series = self._series.get(instrument_id)
        if series is None:
            return None
        found = series.as_of(day, max_age_days=self.max_age_days)
        return found.day if found else None
