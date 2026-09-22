"""FX rates through time.

The core :class:`~meridian.core.fx.FxTable` answers "what is the rate today?".
Valuation and performance need the same question asked for every date in a
history, with the same rules about staleness applied to FX as to prices: a rate
carried forward over a weekend is correct; one carried forward for a fortnight
because a feed stopped is not.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from ..core.currency import get_currency
from ..core.exceptions import RateNotFoundError
from ..core.fx import FxRate, FxTable
from .quotes import FxQuote, MarketDataset
from .series import TimeSeries


class FxHistory:
    """Dated FX series with as-of lookup, cross rates and series conversion."""

    def __init__(self, series: Mapping[str, TimeSeries], *, pivot: str = "USD", max_age_days: int = 4) -> None:
        self._series = {pair.upper(): value for pair, value in series.items()}
        self.pivot = get_currency(pivot).code
        self.max_age_days = max_age_days

    @classmethod
    def from_quotes(cls, quotes: Iterable[FxQuote], *, pivot: str = "USD", max_age_days: int = 4) -> FxHistory:
        dataset = MarketDataset.from_records(fx=quotes)
        return cls.from_dataset(dataset, pivot=pivot, max_age_days=max_age_days)

    @classmethod
    def from_dataset(cls, dataset: MarketDataset, *, pivot: str = "USD", max_age_days: int = 4) -> FxHistory:
        return cls({pair: dataset.fx_series(pair) for pair in dataset.pairs}, pivot=pivot, max_age_days=max_age_days)

    @property
    def pairs(self) -> tuple[str, ...]:
        return tuple(sorted(self._series))

    @property
    def currencies(self) -> tuple[str, ...]:
        found = {self.pivot}
        for pair in self._series:
            found |= {pair[:3], pair[3:]}
        return tuple(sorted(found))

    def series(self, pair: str) -> TimeSeries:
        return self._series[pair.upper()]

    def table_on(self, day: date) -> FxTable:
        """Every pair's rate as of ``day``, skipping any older than ``max_age_days``."""
        rates: list[FxRate] = []
        for pair, series in self._series.items():
            found = series.as_of(day, max_age_days=self.max_age_days)
            if found is not None:
                rates.append(FxRate(pair[:3], pair[3:], found.value, found.day))
        return FxTable(rates, pivot=self.pivot, as_of=day)

    def rate(self, base: str, quote: str, day: date) -> Decimal:
        return self.table_on(day).rate(base, quote).rate

    def convert_series(self, series: TimeSeries, from_currency: str, to_currency: str) -> TimeSeries:
        """A price series re-expressed in another currency, day by day.

        Days with no usable FX rate are dropped rather than converted at a stale
        rate, so a gap in FX shows up as a gap in the result.
        """
        source, target = get_currency(from_currency).code, get_currency(to_currency).code
        if source == target:
            return series
        points: list[tuple[date, Decimal]] = []
        for point in series:
            try:
                rate = self.rate(source, target, point.day)
            except RateNotFoundError:
                continue
            points.append((point.day, point.value * rate))
        return TimeSeries(points, name=f"{series.name} in {target}")

    def cross_matrix(self, day: date, currencies: Sequence[str] | None = None) -> list[list[float | None]]:
        """Rates between every pair of currencies on one day: row currency in units of column currency."""
        table = self.table_on(day)
        names = list(currencies or self.currencies)
        matrix: list[list[float | None]] = []
        for base in names:
            row: list[float | None] = []
            for quote in names:
                try:
                    row.append(float(table.rate(base, quote).rate))
                except RateNotFoundError:
                    row.append(None)
            matrix.append(row)
        return matrix

    def returns(self, pair: str) -> list[tuple[date, float]]:
        return self.series(pair).returns(log=True)
