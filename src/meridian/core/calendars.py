"""Trading calendars and business day conventions.

Settlement dates, accrual periods and return series all depend on knowing which
days an exchange is open. The calendars are computed from rules rather than a
hard-coded list of dates, so they remain correct for any year: fixed holidays with
their observance rules, floating holidays such as "the third Monday in January",
and the Easter-linked holidays that move with the lunar calendar.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Iterator
from datetime import date, timedelta
from enum import Enum
from functools import lru_cache

from .exceptions import CalendarError

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)


class BusinessDayConvention(str, Enum):
    """How a date that falls on a holiday is moved to a business day."""

    UNADJUSTED = "unadjusted"
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"
    MODIFIED_PRECEDING = "modified_preceding"


def easter_sunday(year: int) -> date:
    """Gregorian Easter by the anonymous algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lunar = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lunar) // 451
    month, day = divmod(h + lunar - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th given weekday of a month; ``n = -1`` means the last one."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    last = date(year, month, _calendar.monthrange(year, month)[1])
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _us_observed(day: date, *, shift_saturday: bool = True) -> date:
    """US markets observe a Saturday holiday on the Friday before, a Sunday one on the Monday after."""
    if day.weekday() == SATURDAY and shift_saturday:
        return day - timedelta(days=1)
    if day.weekday() == SUNDAY:
        return day + timedelta(days=1)
    return day


def _uk_substitute(day: date, taken: set[date]) -> date:
    """UK bank holidays move to the next weekday that is not already a holiday."""
    candidate = day
    while candidate.weekday() >= SATURDAY or candidate in taken:
        candidate += timedelta(days=1)
    return candidate


class TradingCalendar:
    """Base calendar: weekends are closed and subclasses add their holiday rules."""

    name = "WEEKEND"
    timezone = "UTC"

    def holidays(self, year: int) -> frozenset[date]:  # pragma: no cover - overridden
        return frozenset()

    @lru_cache(maxsize=256)  # noqa: B019 - calendars are long-lived singletons
    def _holiday_cache(self, year: int) -> frozenset[date]:
        return self.holidays(year)

    def is_weekend(self, day: date) -> bool:
        return day.weekday() >= SATURDAY

    def is_holiday(self, day: date) -> bool:
        return day in self._holiday_cache(day.year)

    def is_business_day(self, day: date) -> bool:
        return not self.is_weekend(day) and not self.is_holiday(day)

    def adjust(self, day: date, convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING) -> date:
        """Move a date onto a business day according to the convention."""
        if convention is BusinessDayConvention.UNADJUSTED or self.is_business_day(day):
            return day
        if convention is BusinessDayConvention.FOLLOWING:
            return self._roll(day, 1)
        if convention is BusinessDayConvention.PRECEDING:
            return self._roll(day, -1)
        if convention is BusinessDayConvention.MODIFIED_FOLLOWING:
            rolled = self._roll(day, 1)
            return self._roll(day, -1) if rolled.month != day.month else rolled
        if convention is BusinessDayConvention.MODIFIED_PRECEDING:
            rolled = self._roll(day, -1)
            return self._roll(day, 1) if rolled.month != day.month else rolled
        raise CalendarError(f"Unsupported convention {convention!r}")  # pragma: no cover

    def _roll(self, day: date, step: int) -> date:
        candidate = day
        for _ in range(370):
            if self.is_business_day(candidate):
                return candidate
            candidate += timedelta(days=step)
        raise CalendarError(f"No business day found near {day}")  # pragma: no cover

    def add_business_days(self, day: date, count: int) -> date:
        """Settlement arithmetic: T+2 is ``add_business_days(trade_date, 2)``."""
        if count == 0:
            return self.adjust(day, BusinessDayConvention.FOLLOWING)
        step = 1 if count > 0 else -1
        remaining = abs(count)
        candidate = day
        while remaining:
            candidate += timedelta(days=step)
            if self.is_business_day(candidate):
                remaining -= 1
        return candidate

    def business_days_between(self, start: date, end: date) -> int:
        """Count business days in ``[start, end)``; negative when the range is reversed."""
        if start == end:
            return 0
        if start > end:
            return -self.business_days_between(end, start)
        return sum(1 for _ in self.business_days(start, end - timedelta(days=1)))

    def business_days(self, start: date, end: date) -> Iterator[date]:
        """Every business day in the inclusive range."""
        if start > end:
            raise CalendarError(f"Start {start} is after end {end}")
        candidate = start
        while candidate <= end:
            if self.is_business_day(candidate):
                yield candidate
            candidate += timedelta(days=1)

    def holidays_between(self, start: date, end: date) -> tuple[date, ...]:
        years = range(start.year, end.year + 1)
        found = sorted(day for year in years for day in self._holiday_cache(year) if start <= day <= end)
        return tuple(found)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


class WeekendCalendar(TradingCalendar):
    """Weekends only - useful for synthetic data and for tests."""

    name = "WEEKEND"


class NYSECalendar(TradingCalendar):
    """New York Stock Exchange."""

    name = "XNYS"
    timezone = "America/New_York"

    def holidays(self, year: int) -> frozenset[date]:
        easter = easter_sunday(year)
        days = {
            _us_observed(date(year, 1, 1), shift_saturday=False),  # New Year's Day is not pulled back to December
            nth_weekday(year, 1, MONDAY, 3),  # Martin Luther King Jr. Day
            nth_weekday(year, 2, MONDAY, 3),  # Washington's Birthday
            easter - timedelta(days=2),  # Good Friday
            nth_weekday(year, 5, MONDAY, -1),  # Memorial Day
            _us_observed(date(year, 7, 4)),  # Independence Day
            nth_weekday(year, 9, MONDAY, 1),  # Labor Day
            nth_weekday(year, 11, THURSDAY, 4),  # Thanksgiving
            _us_observed(date(year, 12, 25)),  # Christmas Day
        }
        if year >= 2022:  # Juneteenth became a market holiday in 2022
            days.add(_us_observed(date(year, 6, 19)))
        return frozenset(day for day in days if day.year == year)


class LSECalendar(TradingCalendar):
    """London Stock Exchange."""

    name = "XLON"
    timezone = "Europe/London"

    def holidays(self, year: int) -> frozenset[date]:
        easter = easter_sunday(year)
        days: set[date] = set()
        for day in (
            date(year, 1, 1),
            easter - timedelta(days=2),  # Good Friday
            easter + timedelta(days=1),  # Easter Monday
            nth_weekday(year, 5, MONDAY, 1),  # Early May bank holiday
            nth_weekday(year, 5, MONDAY, -1),  # Spring bank holiday
            nth_weekday(year, 8, MONDAY, -1),  # Summer bank holiday
            date(year, 12, 25),
            date(year, 12, 26),
        ):
            days.add(_uk_substitute(day, days))
        return frozenset(day for day in days if day.year == year)


class TARGETCalendar(TradingCalendar):
    """TARGET2, the euro area settlement calendar."""

    name = "TARGET"
    timezone = "Europe/Brussels"

    def holidays(self, year: int) -> frozenset[date]:
        easter = easter_sunday(year)
        return frozenset(
            {
                date(year, 1, 1),
                easter - timedelta(days=2),
                easter + timedelta(days=1),
                date(year, 5, 1),
                date(year, 12, 25),
                date(year, 12, 26),
            }
        )


_CALENDARS: dict[str, TradingCalendar] = {
    calendar.name: calendar for calendar in (WeekendCalendar(), NYSECalendar(), LSECalendar(), TARGETCalendar())
}
_ALIASES = {
    "NYSE": "XNYS",
    "US": "XNYS",
    "LSE": "XLON",
    "UK": "XLON",
    "EUR": "TARGET",
    "T2": "TARGET",
    "NONE": "WEEKEND",
}


def get_calendar(name: str | TradingCalendar) -> TradingCalendar:
    if isinstance(name, TradingCalendar):
        return name
    key = name.strip().upper()
    key = _ALIASES.get(key, key)
    try:
        return _CALENDARS[key]
    except KeyError as exc:
        raise CalendarError(f"Unknown calendar {name!r}; known: {sorted(_CALENDARS)}") from exc


def available_calendars() -> tuple[str, ...]:
    return tuple(sorted(_CALENDARS))
