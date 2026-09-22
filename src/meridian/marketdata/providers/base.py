"""The contract every market data source satisfies.

Real platforms take prices from several vendors - an exchange feed, a data
vendor, an evaluated pricing service for bonds, a broker quote for the illiquid
tail - and none of them is trusted on its own. The provider interface is the
narrowest thing they have in common: *give me what you have for these
instruments over these dates*. Everything else, including deciding whether to
believe it, happens downstream.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from ...core.exceptions import MeridianError
from ..quotes import FxQuote, MarketDataset, Quote


class ProviderError(MeridianError):
    """A source could not deliver (unreachable, malformed file, unknown instrument)."""


@runtime_checkable
class MarketDataProvider(Protocol):
    """Anything that can be asked for quotes and FX rates over a date range."""

    @property
    def name(self) -> str: ...

    def quotes(self, instrument_ids: Sequence[str], start: date, end: date) -> list[Quote]: ...

    def fx_quotes(self, pairs: Sequence[str], start: date, end: date) -> list[FxQuote]: ...


def load(
    provider: MarketDataProvider,
    instrument_ids: Sequence[str],
    start: date,
    end: date,
    *,
    pairs: Sequence[str] = (),
) -> MarketDataset:
    """Pull everything a provider has for a request into one dataset."""
    if end < start:
        raise ProviderError(f"{provider.name}: the request ends ({end}) before it starts ({start})")
    return MarketDataset.from_records(
        provider.quotes(instrument_ids, start, end),
        provider.fx_quotes(pairs, start, end) if pairs else (),
    )


class StaticProvider:
    """A provider over records already in memory: fixtures, replays, manual overrides."""

    def __init__(self, name: str, quotes: Sequence[Quote] = (), fx: Sequence[FxQuote] = ()) -> None:
        self._name = name
        self._quotes = list(quotes)
        self._fx = list(fx)

    @property
    def name(self) -> str:
        return self._name

    def quotes(self, instrument_ids: Sequence[str], start: date, end: date) -> list[Quote]:
        wanted = set(instrument_ids)
        return [quote for quote in self._quotes if quote.instrument_id in wanted and start <= quote.day <= end]

    def fx_quotes(self, pairs: Sequence[str], start: date, end: date) -> list[FxQuote]:
        wanted = {pair.upper() for pair in pairs}
        return [rate for rate in self._fx if rate.pair in wanted and start <= rate.day <= end]
