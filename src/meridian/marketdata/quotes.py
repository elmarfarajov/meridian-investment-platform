"""Quotes as they arrive from a source, before anyone has decided to believe them.

A :class:`Quote` is deliberately permissive: it will hold a zero price, a bid
above the ask, or a print on a Sunday, because the job of the ingestion layer
is to *record what the vendor sent* and the job of the quality layer is to
judge it. Rejecting bad data at construction would make it invisible, and
invisible bad data is how a stale price ends up in a client statement.

The only things refused here are ones that cannot be recorded at all: a
missing identifier or a value that is not a finite number.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.decimals import Numeric, to_decimal
from ..core.enums import PriceType
from ..core.exceptions import ValidationError
from .series import TimeSeries


@dataclass(frozen=True, slots=True, kw_only=True)
class Quote:
    """One end-of-day record for one instrument from one source."""

    instrument_id: str
    day: date
    close: Decimal
    currency: str
    source: str = "unknown"
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume: int | None = None
    price_type: PriceType = PriceType.CLOSE

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValidationError("a quote needs an instrument_id")
        label = f"{self.instrument_id}[{self.day}]"
        object.__setattr__(self, "close", to_decimal(self.close, field=f"{label}.close"))
        object.__setattr__(self, "currency", self.currency.upper())
        for name in ("bid", "ask"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, to_decimal(value, field=f"{label}.{name}"))
        if self.volume is not None and self.volume < 0:
            raise ValidationError(f"{label}: volume cannot be negative")

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @property
    def is_crossed(self) -> bool:
        return self.bid is not None and self.ask is not None and self.bid > self.ask

    @property
    def spread_bps(self) -> float | None:
        """Quoted spread over the mid, in basis points."""
        mid = self.mid
        if mid is None or mid <= 0 or self.bid is None or self.ask is None:
            return None
        return float((self.ask - self.bid) / mid) * 10_000

    def with_close(self, close: Numeric, **changes: object) -> Quote:
        values: dict[str, object] = {
            "instrument_id": self.instrument_id,
            "day": self.day,
            "close": to_decimal(close, field="close"),
            "currency": self.currency,
            "source": self.source,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "price_type": self.price_type,
        }
        values.update(changes)
        return Quote(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True, kw_only=True)
class FxQuote:
    """One FX rate: one unit of ``base`` buys ``rate`` units of ``quote``."""

    base: str
    quote: str
    day: date
    rate: Decimal
    source: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", self.base.upper())
        object.__setattr__(self, "quote", self.quote.upper())
        if self.base == self.quote:
            raise ValidationError(f"{self.base}{self.quote} is not a currency pair")
        object.__setattr__(self, "rate", to_decimal(self.rate, field=f"{self.pair}[{self.day}]"))

    @property
    def pair(self) -> str:
        return f"{self.base}{self.quote}"


@dataclass
class MarketDataset:
    """Quotes and FX from one load, indexed for the quality and pricing layers."""

    quotes: dict[str, list[Quote]] = field(default_factory=lambda: defaultdict(list))
    fx: dict[str, list[FxQuote]] = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def from_records(cls, quotes: Iterable[Quote] = (), fx: Iterable[FxQuote] = ()) -> MarketDataset:
        dataset = cls()
        dataset.extend(quotes, fx)
        return dataset

    def extend(self, quotes: Iterable[Quote] = (), fx: Iterable[FxQuote] = ()) -> MarketDataset:
        for quote in quotes:
            self.quotes[quote.instrument_id].append(quote)
        for rate in fx:
            self.fx[rate.pair].append(rate)
        for items in self.quotes.values():
            items.sort(key=lambda item: (item.day, item.source))
        for rates in self.fx.values():
            rates.sort(key=lambda item: (item.day, item.source))
        return self

    # ------------------------------------------------------------------ views
    @property
    def instruments(self) -> tuple[str, ...]:
        return tuple(sorted(self.quotes))

    @property
    def pairs(self) -> tuple[str, ...]:
        return tuple(sorted(self.fx))

    @property
    def sources(self) -> tuple[str, ...]:
        found = {quote.source for items in self.quotes.values() for quote in items}
        found |= {rate.source for items in self.fx.values() for rate in items}
        return tuple(sorted(found))

    def __len__(self) -> int:
        return sum(len(items) for items in self.quotes.values()) + sum(len(items) for items in self.fx.values())

    def for_instrument(self, instrument_id: str, *, source: str | None = None) -> list[Quote]:
        items = self.quotes.get(instrument_id, [])
        return [item for item in items if source is None or item.source == source]

    def close_series(self, instrument_id: str, *, source: str | None = None) -> TimeSeries:
        """Closing prices for one instrument from one source.

        With several sources and no ``source`` given, the first record per day
        wins - callers that need a reconciled price should use the golden copy.
        """
        seen: dict[date, Decimal] = {}
        for quote in self.for_instrument(instrument_id, source=source):
            seen.setdefault(quote.day, quote.close)
        return TimeSeries(seen.items(), name=instrument_id)

    def fx_series(self, pair: str, *, source: str | None = None) -> TimeSeries:
        seen: dict[date, Decimal] = {}
        for rate in self.fx.get(pair.upper(), []):
            if source is None or rate.source == source:
                seen.setdefault(rate.day, rate.rate)
        return TimeSeries(seen.items(), name=pair.upper())

    def currency_of(self, instrument_id: str) -> str | None:
        items = self.quotes.get(instrument_id)
        return items[0].currency if items else None

    def days(self) -> tuple[date, ...]:
        found = {quote.day for items in self.quotes.values() for quote in items}
        found |= {rate.day for items in self.fx.values() for rate in items}
        return tuple(sorted(found))

    def restrict(self, instrument_ids: Sequence[str]) -> MarketDataset:
        wanted = set(instrument_ids)
        return MarketDataset.from_records(
            (quote for key, items in self.quotes.items() if key in wanted for quote in items),
            (rate for items in self.fx.values() for rate in items),
        )
