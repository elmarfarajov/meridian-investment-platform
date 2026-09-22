"""A source hierarchy: ask the preferred vendor first, fall back down the list.

This is the simplest pricing policy a real desk runs, and for most liquid
instruments it is the right one: the primary exchange close if there is one,
otherwise the data vendor, otherwise the evaluated price. It says nothing about
whether the chosen value is *right* - that is the golden copy's job - but it
guarantees that every returned quote names the source that supplied it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from ...core.exceptions import ValidationError
from ..quotes import FxQuote, Quote
from .base import MarketDataProvider


class WaterfallProvider:
    """Per instrument and day, the quote from the highest-ranked provider that has one."""

    def __init__(self, providers: Sequence[MarketDataProvider], *, name: str = "waterfall") -> None:
        if not providers:
            raise ValidationError("a waterfall needs at least one provider")
        self.providers = list(providers)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def ranking(self) -> tuple[str, ...]:
        return tuple(provider.name for provider in self.providers)

    def quotes(self, instrument_ids: Sequence[str], start: date, end: date) -> list[Quote]:
        chosen: dict[tuple[str, date], Quote] = {}
        for provider in self.providers:
            for quote in provider.quotes(instrument_ids, start, end):
                chosen.setdefault((quote.instrument_id, quote.day), quote)
        return [chosen[key] for key in sorted(chosen)]

    def fx_quotes(self, pairs: Sequence[str], start: date, end: date) -> list[FxQuote]:
        chosen: dict[tuple[str, date], FxQuote] = {}
        for provider in self.providers:
            for rate in provider.fx_quotes(pairs, start, end):
                chosen.setdefault((rate.pair, rate.day), rate)
        return [chosen[key] for key in sorted(chosen)]

    def coverage(self, instrument_ids: Sequence[str], start: date, end: date) -> dict[str, int]:
        """How many of the chosen quotes each provider supplied."""
        counts = dict.fromkeys(self.ranking, 0)
        for quote in self.quotes(instrument_ids, start, end):
            counts[quote.source] = counts.get(quote.source, 0) + 1
        return counts
