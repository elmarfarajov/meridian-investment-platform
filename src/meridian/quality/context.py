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

import bisect
import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import cached_property

from ..core.calendars import TradingCalendar, get_calendar
from ..domain.corporate_actions import AdjustmentMode, CorporateAction
from ..marketdata.adjustments import in_price_units
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
    # periods with no price to expect: a currency after the euro, a suspended fixing
    inactive: Sequence[tuple[date, date | None]] = ()
    # days under a managed exchange-rate regime, judged against its band, not by statistics
    managed: frozenset[date] = frozenset()

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
        inactive: Sequence[tuple[date, date | None]] = (),
        managed: frozenset[date] = frozenset(),
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
            inactive=tuple(inactive),
            managed=managed,
        )

    @classmethod
    def from_series(
        cls,
        key: str,
        series: TimeSeries,
        calendar: TradingCalendar | str = "WEEKEND",
        *,
        as_of: date | None = None,
        inactive: Sequence[tuple[date, date | None]] = (),
        managed: frozenset[date] = frozenset(),
    ) -> SeriesContext:
        """A context over a bare series (an FX rate, an index level) with no bid, ask or currency."""
        quotes = [Quote(instrument_id=key, day=point.day, close=point.value, currency="XXX") for point in series]
        return cls.build(key, quotes, calendar, as_of=as_of, inactive=inactive, managed=managed)

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

    @property
    def price_unit(self) -> str | None:
        """The unit the prices are quoted in (GBX, ZAc, USD...), from the quotes themselves."""
        units = {quote.currency for quote in self.quotes if quote.currency and quote.currency != "XXX"}
        return units.pop() if len(units) == 1 else None

    @cached_property
    def actions_by_date(self) -> dict[date, list[CorporateAction]]:
        grouped: dict[date, list[CorporateAction]] = {}
        for action in self.actions:
            grouped.setdefault(action.ex_date, []).append(action)
        return grouped

    def events_between(self, after: date, through: date) -> list[CorporateAction]:
        """Every event going ex after one observation and on or before the next.

        An ex-date can fall on a day the series has no print - a missing day, or a
        market holiday in the feed's own calendar. The event still happened, and the
        next observation's return has to be judged with it divided out.
        """
        return [
            action
            for day, actions in sorted(self.actions_by_date.items())
            if after < day <= through
            for action in actions
        ]

    def event_factor(self, day: date, cum_price: Decimal, *, since: date | None = None) -> Decimal:
        """Combined price factor of every event going ex on ``day`` (or after ``since``); 1 when nothing happens."""
        factor = Decimal(1)
        events = self.events_between(since, day) if since is not None else self.actions_by_date.get(day, [])
        for action in events:
            if action.applies_in(AdjustmentMode.TOTAL_RETURN) and cum_price > 0:
                try:
                    # a dividend in pounds set against a price in pence: same unit first
                    factor *= in_price_units(action, self.price_unit).price_factor(cum_price)
                except Exception:  # an event that cannot be sized is reported by its own rule
                    continue
        return factor

    @cached_property
    def raw_returns(self) -> list[tuple[date, float]]:
        """Log returns between consecutive observations, skipping non-positive prices."""
        return self.series.returns(log=True)

    @cached_property
    def adjusted_spans(self) -> list[tuple[date, date, float]]:
        """(previous day, day, log return) with every event in between divided out."""
        points = list(self.series)
        results: list[tuple[date, date, float]] = []
        for previous, current in itertools.pairwise(points):
            if previous.value <= 0 or current.value <= 0:
                continue
            if any(previous.day <= after < current.day for after, _ in self.inactive):
                continue  # nine years of a suspended fixing are not one day's return
            factor = self.event_factor(current.day, previous.value, since=previous.day)
            ratio = float(current.value) / (float(previous.value) * float(factor))
            results.append((previous.day, current.day, math.log(ratio)))
        return results

    @cached_property
    def adjusted_returns(self) -> list[tuple[date, float]]:
        """Log returns with every corporate action since the previous observation divided out."""
        return [(day, value) for _, day, value in self.adjusted_spans]

    def is_one_session(self, previous: date, day: date) -> bool:
        """True when ``previous`` is the business day immediately before ``day`` on this calendar."""
        return self.calendar.add_business_days(day, -1) == previous

    @cached_property
    def residual_returns(self) -> list[tuple[date, float]]:
        """Adjusted returns less the market's move over the same span, when there is a proxy.

        A 6% fall on a day the whole market fell 5% is a market move; a 6% fall on
        a flat day is a question. Scoring the residual is what lets the outlier
        rule tell them apart. A return that spans a gap - three days, after two
        missing prints - is set against the market's move over all three, not the
        last one.
        """
        if not self.market:
            return self.adjusted_returns
        market_days = sorted(self.market)
        results: list[tuple[date, float]] = []
        for previous, day, value in self.adjusted_spans:
            low = bisect.bisect_right(market_days, previous)
            high = bisect.bisect_right(market_days, day)
            moved = sum(self.market[market_days[index]] for index in range(low, high))
            results.append((day, value - moved))
        return results

    @cached_property
    def expected_days(self) -> tuple[date, ...]:
        """Every business day of the instrument's own calendar from the first observation to ``as_of``."""
        if not self.series:
            return ()
        end = self.as_of
        start = self.series.first.day
        if end < start:
            return ()
        return tuple(
            day
            for day in self.calendar.business_days(start, end)
            if not any(after < day and (until is None or day < until) for after, until in self.inactive)
        )

    @cached_property
    def tick_returns(self) -> list[float]:
        """For each return, one tick of the quotes just before it: the resolution, measured locally.

        Sources change how they quote. The ECB fixed the Icelandic krona to two
        decimals in 1999 and to one decimal later, so a single resolution for the
        whole history would be wrong at one end or the other. The finest step among
        the twenty prints before each return is used.
        """
        closes = [point for point in self.series if point.value > 0]
        index = {point.day: position for position, point in enumerate(closes)}
        exponents = [int(point.value.normalize().as_tuple().exponent) for point in closes]
        result = []
        for previous, _, _ in self.adjusted_spans:
            position = index[previous]
            finest = min(exponents[max(0, position - 19) : position + 1])
            result.append(10.0**finest / float(closes[position].value))
        return result

    @cached_property
    def tick_return(self) -> float:
        """One tick of the finest quote in the series, as a return: the resolution of the data.

        A rate fixed to four decimals near 1.96 cannot move by less than 0.5 bp; an
        ISK rate quoted to one decimal near 140, by less than 7 bp. Statistics that
        ignore this mistake rounding for information.
        """
        closes = [quote.close for quote in self.quotes if quote.close > 0]
        if not closes:
            return 0.0
        # the finest step any print shows: 1.9558 resolves 0.0001, 1,202,000 resolves 1,000
        finest = min(int(close.normalize().as_tuple().exponent) for close in closes)
        typical = sorted(float(close) for close in closes)[len(closes) // 2]
        return 10.0**finest / typical

    def recent_volatility(self, window: int = 60) -> list[float | None]:
        """For each return, the robust daily volatility of the ``window`` returns before it."""
        values = [value for _, value in self.adjusted_returns]
        result: list[float | None] = []
        for index in range(len(values)):
            history = values[max(0, index - window) : index]
            if len(history) < 20:
                result.append(None)
                continue
            ordered = sorted(history)
            centre = ordered[len(ordered) // 2]
            deviations = sorted(abs(value - centre) for value in history)
            result.append(deviations[len(deviations) // 2] * 1.482602218505602)
        return result

    @property
    def has_quotes(self) -> bool:
        return any(quote.bid is not None and quote.ask is not None for quote in self.quotes)
