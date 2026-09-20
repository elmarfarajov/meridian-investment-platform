"""Trading calendars and business day conventions.

Settlement dates, accrual periods and return series all depend on knowing which
days an exchange is open. The calendars are computed from rules rather than a
hard-coded list of dates, so they remain correct for any year: fixed holidays with
their observance rules, floating holidays such as "the third Monday in January",
the Easter-linked holidays that move with the lunar calendar, and - for Tokyo -
the equinoxes, which are astronomical events approximated by formula.

Holidays carry their names. A valuation that fails because a market was shut is
far easier to explain when the system can say *which* holiday closed it.

Cross-border settlement needs more than one calendar at a time: a EUR/JPY trade
settles only on a day that is good in both TARGET and Tokyo. :class:`JointCalendar`
composes calendars for exactly that.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True, order=True)
class Holiday:
    """A market closure, with the name it is known by."""

    day: date
    name: str

    def __str__(self) -> str:
        return f"{self.day.isoformat()} {self.name}"


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


def vernal_equinox(year: int) -> date:
    """Japan's Vernal Equinox Day, by the approximation used for 1980-2099."""
    return date(year, 3, int(20.8431 + 0.242194 * (year - 1980) - (year - 1980) // 4))


def autumnal_equinox(year: int) -> date:
    """Japan's Autumnal Equinox Day, by the approximation used for 1980-2099."""
    return date(year, 9, int(23.2488 + 0.242194 * (year - 1980) - (year - 1980) // 4))


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


def _jp_substitute(day: date, taken: set[date]) -> date:
    """Japan's furikae kyujitsu: a Sunday holiday is observed on the next free weekday."""
    if day.weekday() != SUNDAY:
        return day
    candidate = day + timedelta(days=1)
    while candidate in taken:
        candidate += timedelta(days=1)
    return candidate


class TradingCalendar:
    """Base calendar: weekends are closed and subclasses add their holiday rules."""

    name = "WEEKEND"
    timezone = "UTC"
    description = "Weekends only"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        """The closures for a year, with names. Subclasses override this one."""
        return ()

    @lru_cache(maxsize=512)  # noqa: B019 - calendars are long-lived singletons
    def _named_cache(self, year: int) -> tuple[Holiday, ...]:
        found = {holiday.day: holiday for holiday in self.named_holidays(year) if holiday.day.year == year}
        return tuple(sorted(found.values()))

    @lru_cache(maxsize=512)  # noqa: B019 - see above
    def _holiday_cache(self, year: int) -> frozenset[date]:
        return frozenset(holiday.day for holiday in self._named_cache(year))

    def holidays(self, year: int) -> frozenset[date]:
        """The closure dates for a year."""
        return self._holiday_cache(year)

    def holiday_name(self, day: date) -> str | None:
        """Which holiday closed the market on this day, if any."""
        for holiday in self._named_cache(day.year):
            if holiday.day == day:
                return holiday.name
        return None

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

    def named_holidays_between(self, start: date, end: date) -> tuple[Holiday, ...]:
        years = range(start.year, end.year + 1)
        return tuple(
            sorted(holiday for year in years for holiday in self._named_cache(year) if start <= holiday.day <= end)
        )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


class WeekendCalendar(TradingCalendar):
    """Weekends only - useful for synthetic data and for tests."""

    name = "WEEKEND"
    description = "Saturdays and Sundays only"


class NYSECalendar(TradingCalendar):
    """New York Stock Exchange."""

    name = "XNYS"
    timezone = "America/New_York"
    description = "New York Stock Exchange"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        easter = easter_sunday(year)
        days = [
            # New Year's Day is not pulled back into the previous year when it falls on a Saturday
            Holiday(_us_observed(date(year, 1, 1), shift_saturday=False), "New Year's Day"),
            Holiday(nth_weekday(year, 1, MONDAY, 3), "Martin Luther King Jr. Day"),
            Holiday(nth_weekday(year, 2, MONDAY, 3), "Washington's Birthday"),
            Holiday(easter - timedelta(days=2), "Good Friday"),
            Holiday(nth_weekday(year, 5, MONDAY, -1), "Memorial Day"),
            Holiday(_us_observed(date(year, 7, 4)), "Independence Day"),
            Holiday(nth_weekday(year, 9, MONDAY, 1), "Labor Day"),
            Holiday(nth_weekday(year, 11, THURSDAY, 4), "Thanksgiving Day"),
            Holiday(_us_observed(date(year, 12, 25)), "Christmas Day"),
        ]
        if year >= 2022:  # Juneteenth became a market holiday in 2022
            days.append(Holiday(_us_observed(date(year, 6, 19)), "Juneteenth National Independence Day"))
        return tuple(days)


class SIFMACalendar(NYSECalendar):
    """US bond market (SIFMA recommended close), which keeps two holidays the equity market does not."""

    name = "SIFMA"
    timezone = "America/New_York"
    description = "US fixed income market"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        equities = [holiday for holiday in super().named_holidays(year) if holiday.name != "Good Friday"]
        return (
            *equities,
            # The bond market closes for Good Friday too, except when it is a major employment-report day;
            # that exception is a recommendation rather than a rule, so the closure is kept here.
            Holiday(easter_sunday(year) - timedelta(days=2), "Good Friday"),
            Holiday(nth_weekday(year, 10, MONDAY, 2), "Columbus Day"),
            Holiday(_us_observed(date(year, 11, 11)), "Veterans Day"),
        )


class LSECalendar(TradingCalendar):
    """London Stock Exchange."""

    name = "XLON"
    timezone = "Europe/London"
    description = "London Stock Exchange"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        easter = easter_sunday(year)
        taken: set[date] = set()
        result: list[Holiday] = []
        for day, label in (
            (date(year, 1, 1), "New Year's Day"),
            (easter - timedelta(days=2), "Good Friday"),
            (easter + timedelta(days=1), "Easter Monday"),
            (nth_weekday(year, 5, MONDAY, 1), "Early May Bank Holiday"),
            (nth_weekday(year, 5, MONDAY, -1), "Spring Bank Holiday"),
            (nth_weekday(year, 8, MONDAY, -1), "Summer Bank Holiday"),
            (date(year, 12, 25), "Christmas Day"),
            (date(year, 12, 26), "Boxing Day"),
        ):
            observed = _uk_substitute(day, taken)
            taken.add(observed)
            result.append(Holiday(observed, label if observed == day else f"{label} (substitute day)"))
        return tuple(result)


class TARGETCalendar(TradingCalendar):
    """TARGET2, the euro area settlement calendar."""

    name = "TARGET"
    timezone = "Europe/Brussels"
    description = "Euro area settlement (TARGET2)"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        easter = easter_sunday(year)
        return (
            Holiday(date(year, 1, 1), "New Year's Day"),
            Holiday(easter - timedelta(days=2), "Good Friday"),
            Holiday(easter + timedelta(days=1), "Easter Monday"),
            Holiday(date(year, 5, 1), "Labour Day"),
            Holiday(date(year, 12, 25), "Christmas Day"),
            Holiday(date(year, 12, 26), "Christmas Holiday"),
        )


class XETRACalendar(TradingCalendar):
    """Xetra, the German electronic exchange."""

    name = "XETR"
    timezone = "Europe/Berlin"
    description = "Deutsche Boerse Xetra"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        easter = easter_sunday(year)
        return (
            Holiday(date(year, 1, 1), "New Year's Day"),
            Holiday(easter - timedelta(days=2), "Good Friday"),
            Holiday(easter + timedelta(days=1), "Easter Monday"),
            Holiday(date(year, 5, 1), "Labour Day"),
            Holiday(easter + timedelta(days=50), "Whit Monday"),
            Holiday(date(year, 12, 24), "Christmas Eve"),
            Holiday(date(year, 12, 25), "Christmas Day"),
            Holiday(date(year, 12, 26), "Boxing Day"),
            Holiday(date(year, 12, 31), "New Year's Eve"),
        )


class SIXCalendar(TradingCalendar):
    """SIX Swiss Exchange."""

    name = "XSWX"
    timezone = "Europe/Zurich"
    description = "SIX Swiss Exchange"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        easter = easter_sunday(year)
        return (
            Holiday(date(year, 1, 1), "New Year's Day"),
            Holiday(date(year, 1, 2), "Berchtold's Day"),
            Holiday(easter - timedelta(days=2), "Good Friday"),
            Holiday(easter + timedelta(days=1), "Easter Monday"),
            Holiday(date(year, 5, 1), "Labour Day"),
            Holiday(easter + timedelta(days=39), "Ascension Day"),
            Holiday(easter + timedelta(days=50), "Whit Monday"),
            Holiday(date(year, 8, 1), "Swiss National Day"),
            Holiday(date(year, 12, 24), "Christmas Eve"),
            Holiday(date(year, 12, 25), "Christmas Day"),
            Holiday(date(year, 12, 26), "St Stephen's Day"),
            Holiday(date(year, 12, 31), "New Year's Eve"),
        )


class TokyoCalendar(TradingCalendar):
    """Tokyo Stock Exchange, including the equinoxes and the year-end closure."""

    name = "XTKS"
    timezone = "Asia/Tokyo"
    description = "Tokyo Stock Exchange"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        statutory: list[tuple[date, str]] = [
            (date(year, 1, 1), "New Year's Day"),
            (nth_weekday(year, 1, MONDAY, 2), "Coming of Age Day"),
            (date(year, 2, 11), "National Foundation Day"),
            (vernal_equinox(year), "Vernal Equinox Day"),
            (date(year, 4, 29), "Showa Day"),
            (date(year, 5, 3), "Constitution Memorial Day"),
            (date(year, 5, 4), "Greenery Day"),
            (date(year, 5, 5), "Children's Day"),
            (nth_weekday(year, 7, MONDAY, 3), "Marine Day"),
            (date(year, 8, 11), "Mountain Day"),
            (nth_weekday(year, 9, MONDAY, 3), "Respect for the Aged Day"),
            (autumnal_equinox(year), "Autumnal Equinox Day"),
            (nth_weekday(year, 10, MONDAY, 2), "Sports Day"),
            (date(year, 11, 3), "Culture Day"),
            (date(year, 11, 23), "Labour Thanksgiving Day"),
        ]
        if year >= 2020:  # the Emperor's Birthday moved with the accession in 2019
            statutory.append((date(year, 2, 23), "The Emperor's Birthday"))
        else:
            statutory.append((date(year, 12, 23), "The Emperor's Birthday"))

        taken = {day for day, _ in statutory}
        result = [Holiday(day, label) for day, label in statutory]
        for day, label in statutory:
            observed = _jp_substitute(day, taken)
            if observed != day:
                taken.add(observed)
                result.append(Holiday(observed, f"{label} (observed)"))
        # The exchange itself closes for the new year period, beyond the statutory holidays
        result.extend(
            [
                Holiday(date(year, 1, 2), "Exchange holiday (new year)"),
                Holiday(date(year, 1, 3), "Exchange holiday (new year)"),
                Holiday(date(year, 12, 31), "Exchange holiday (year end)"),
            ]
        )
        return tuple(result)


class JointCalendar(TradingCalendar):
    """Several calendars composed into one.

    ``union`` - the default - is the settlement rule: a day is good only if it is
    good in *every* calendar, so the holidays are the union of all of them. That is
    what a cross-currency settlement or a cross-listed trade needs.

    ``intersection`` closes only on days that *all* the calendars close, which is
    the right rule for asking "was any market open on this day?".
    """

    def __init__(self, calendars: Sequence[TradingCalendar | str], *, mode: str = "union", name: str | None = None):
        resolved = [get_calendar(item) for item in calendars]
        if not resolved:
            raise CalendarError("A joint calendar needs at least one calendar")
        if mode not in {"union", "intersection"}:
            raise CalendarError(f"Unknown joint calendar mode {mode!r}")
        self.calendars = tuple(resolved)
        self.mode = mode
        self.name = name or (
            "+".join(item.name for item in resolved) if mode == "union" else "|".join(item.name for item in resolved)
        )
        self.timezone = resolved[0].timezone
        self.description = f"{mode} of {', '.join(item.name for item in resolved)}"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        if self.mode == "union":
            merged: dict[date, list[str]] = {}
            for calendar in self.calendars:
                for holiday in calendar._named_cache(year):
                    merged.setdefault(holiday.day, []).append(f"{calendar.name}: {holiday.name}")
            return tuple(Holiday(day, " / ".join(labels)) for day, labels in sorted(merged.items()))
        shared = set.intersection(*(set(calendar.holidays(year)) for calendar in self.calendars))
        return tuple(Holiday(day, self.calendars[0].holiday_name(day) or "Holiday") for day in sorted(shared))


_CALENDARS: dict[str, TradingCalendar] = {
    calendar.name: calendar
    for calendar in (
        WeekendCalendar(),
        NYSECalendar(),
        SIFMACalendar(),
        LSECalendar(),
        TARGETCalendar(),
        XETRACalendar(),
        SIXCalendar(),
        TokyoCalendar(),
    )
}
_ALIASES = {
    "NYSE": "XNYS",
    "US": "XNYS",
    "USD": "XNYS",
    "BOND": "SIFMA",
    "LSE": "XLON",
    "UK": "XLON",
    "GBP": "XLON",
    "EUR": "TARGET",
    "T2": "TARGET",
    "FRANKFURT": "XETR",
    "DE": "XETR",
    "ZURICH": "XSWX",
    "CHF": "XSWX",
    "TOKYO": "XTKS",
    "JPY": "XTKS",
    "JP": "XTKS",
    "NONE": "WEEKEND",
}


def get_calendar(name: str | TradingCalendar) -> TradingCalendar:
    if isinstance(name, TradingCalendar):
        return name
    key = name.strip().upper()
    if "+" in key:  # "XNYS+XLON" composes a settlement calendar on the spot
        return JointCalendar([part for part in key.split("+") if part])
    key = _ALIASES.get(key, key)
    try:
        return _CALENDARS[key]
    except KeyError as exc:
        raise CalendarError(f"Unknown calendar {name!r}; known: {sorted(_CALENDARS)}") from exc


def available_calendars() -> tuple[str, ...]:
    return tuple(sorted(_CALENDARS))


def calendar_aliases() -> dict[str, str]:
    return dict(_ALIASES)


def settlement_date(
    trade_date: date,
    days: int,
    calendars: Iterable[TradingCalendar | str],
) -> date:
    """Settlement under every calendar that has to agree, which is the real rule for a cross-border trade."""
    joint = JointCalendar(list(calendars))
    return joint.add_business_days(trade_date, days)
