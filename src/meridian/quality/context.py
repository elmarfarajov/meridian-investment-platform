"""Everything a rule needs to judge one series, computed once.

Several rules want the same derived data - the closing series, the returns,
the returns with corporate actions taken out, the expected trading days - and
computing them per rule would be both slow and a chance for two rules to
disagree about what the series is. The context computes them once, lazily.

Returns are *event-adjusted* before any statistical rule sees them: on a
4-for-1 split the raw price falls 75%, and an outlier test that has not been
told about the split will flag the most ordinary event in equity markets as
the worst print of the year.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import cached_property

from ..core.calendars import TradingCalendar, get_calendar
from ..domain.corporate_actions import AdjustmentMode, CorporateAction
from ..marketdata.quotes import Quote
from ..marketdata.series import TimeSeries


@dataclass
class SeriesContext:
    """One instrument's quotes from one source, with the reference data to judge them."""

    key: str
    quotes: Sequence[Quote]
    calendar: TradingCalendar
    as_of: date
    source: str = ""
    actions: Sequence[CorporateAction] = ()
    market: Mapping[date, float] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        key: str,
        quotes: Sequence[Quote],
        calendar: TradingCalendar | str,
        *,
        as_of: date | None = None,
        source: str = "",
        actions: Sequence[CorporateAction] = (),
        market: Mapping[date, float] | None = None,
    ) -> SeriesContext:
        ordered = sorted(quotes, key=lambda quote: quote.day)
        resolved_as_of = as_of or (ordered[-1].day if ordered else date.today())
        return cls(
            key=key,
            quotes=ordered,
            calendar=get_calendar(calendar),
            as_of=resolved_as_of,
            source=source,
            actions=[action for action in actions if action.instrument_id == key],
            market=dict(market or {}),
        )

    @classmethod
    def from_series(
        cls, key: str, series: TimeSeries, calendar: TradingCalendar | str = "WEEKEND", *, as_of: date | None = None
    ) -> SeriesContext:
        """A context over a bare series (an FX rate, an index level) with no bid, ask or currency."""
        quotes = [Quote(instrument_id=key, day=point.day, close=point.value, currency="XXX") for point in series]
        return cls.build(key, quotes, calendar, as_of=as_of)

    # ------------------------------------------------------------------ derived data
    @cached_property
    def series(self) -> TimeSeries:
        # a holiday print can duplicate a day in a damaged feed; the first record wins
        seen: dict[date, Decimal] = {}
        for quote in self.quotes:
            seen.setdefault(quote.day, quote.close)
        return TimeSeries(seen.items(), name=self.key)

    @property
    def days(self) -> tuple[date, ...]:
        return self.series.days

    @cached_property
    def actions_by_date(self) -> dict[date, list[CorporateAction]]:
        grouped: dict[date, list[CorporateAction]] = {}
        for action in self.actions:
            grouped.setdefault(action.ex_date, []).append(action)
        return grouped

    def event_factor(self, day: date, cum_price: Decimal) -> Decimal:
        """Combined price factor of every event going ex on ``day``; 1 when nothing happens."""
        factor = Decimal(1)
        for action in self.actions_by_date.get(day, []):
            if action.applies_in(AdjustmentMode.TOTAL_RETURN) and cum_price > 0:
                try:
                    factor *= action.price_factor(cum_price)
                except Exception:  # an event that cannot be sized is reported by its own rule
                    continue
        return factor

    @cached_property
    def raw_returns(self) -> list[tuple[date, float]]:
        """Log returns between consecutive observations, skipping non-positive prices."""
        return self.series.returns(log=True)

    @cached_property
    def adjusted_returns(self) -> list[tuple[date, float]]:
        """Log returns with every corporate action on the ex-date divided out."""
        points = list(self.series)
        results: list[tuple[date, float]] = []
        for previous, current in itertools.pairwise(points):
            if previous.value <= 0 or current.value <= 0:
                continue
            factor = self.event_factor(current.day, previous.value)
            ratio = float(current.value) / (float(previous.value) * float(factor))
            results.append((current.day, math.log(ratio)))
        return results

    @cached_property
    def residual_returns(self) -> list[tuple[date, float]]:
        """Adjusted returns less the market proxy for the same day, when there is one.

        A 6% fall on a day the whole market fell 5% is a market move; a 6% fall on
        a flat day is a question. Scoring the residual is what lets the outlier
        rule tell them apart.
        """
        if not self.market:
            return self.adjusted_returns
        return [(day, value - self.market.get(day, 0.0)) for day, value in self.adjusted_returns]

    @cached_property
    def expected_days(self) -> tuple[date, ...]:
        """Every business day of the instrument's own calendar from the first observation to ``as_of``."""
        if not self.series:
            return ()
        end = self.as_of
        start = self.series.first.day
        if end < start:
            return ()
        return tuple(self.calendar.business_days(start, end))

    @property
    def has_quotes(self) -> bool:
        return any(quote.bid is not None and quote.ask is not None for quote in self.quotes)
