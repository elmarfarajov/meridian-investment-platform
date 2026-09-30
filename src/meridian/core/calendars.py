"""Trading calendars and business day conventions.

Settlement dates, accrual periods and return series all depend on knowing which
days an exchange is open. The calendars are computed from rules rather than a
hard-coded list of dates, so they remain correct for any year: fixed holidays with
their observance rules, floating holidays such as "the third Monday in January",
the Easter-linked holidays that move with the lunar calendar, and - for Tokyo -
the equinoxes, which are astronomical events and are computed as such.

Rules change, and a calendar used on history has to know when. Martin Luther King
Jr. Day closed the NYSE only from 1998; Japan moved four holidays to Mondays in 2000
and 2003; TARGET closed on Good Friday only from 2000. Each rule carries the years it
applies to. Markets also close for events no rule predicts - a state funeral, a
hurricane, 11 September 2001 - so each calendar carries its special closures as data,
with their names.

The calendars are validated against QuantLib day by day from 1990 to 2060. Every
remaining difference is listed in ``meridian.devtools.reference`` with its reason.

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
from typing import ClassVar

from .astronomy import equinox_day
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
    """Japan's Vernal Equinox Day: the day in Tokyo on which the Sun crosses the equator northwards."""
    return equinox_day(year, "march")


def autumnal_equinox(year: int) -> date:
    """Japan's Autumnal Equinox Day: the day in Tokyo on which the Sun crosses the equator southwards."""
    return equinox_day(year, "september")


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
    description = "Weekends only"
    # Closures no rule predicts: state funerals, storms, national emergencies
    special_closures: tuple[Holiday, ...] = ()

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        """The scheduled closures for a year, by rule and with names. Subclasses override this one."""
        return ()

    def special_openings(self, year: int) -> frozenset[date]:
        """Scheduled closures the market decided, that year, not to take."""
        return frozenset()

    @lru_cache(maxsize=512)  # noqa: B019 - calendars are long-lived singletons
    def _named_cache(self, year: int) -> tuple[Holiday, ...]:
        opened = self.special_openings(year)
        found = {
            holiday.day: holiday
            for holiday in self.named_holidays(year)
            if holiday.day.year == year and holiday.day not in opened
        }
        for holiday in self.special_closures:
            if holiday.day.year == year:
                found.setdefault(holiday.day, holiday)
        return tuple(sorted(found.values()))

    def scheduled(self) -> TradingCalendar:
        """The calendar as its rules schedule it, without special closures or openings.

        The actual calendar is what settlement and valuation need. The scheduled one is
        what a simulation should step through: a state funeral closes the market, but
        news keeps arriving, and the next open prices all of it. A simulation driven by
        the scheduled calendar therefore produces the same random path whatever
        history later adds to the actual one.
        """
        return _scheduled_view(self)

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
    special_closures = (
        Holiday(date(1994, 4, 27), "National Day of Mourning for President Nixon"),
        Holiday(date(2001, 9, 11), "September 11 attacks"),
        Holiday(date(2001, 9, 12), "September 11 attacks"),
        Holiday(date(2001, 9, 13), "September 11 attacks"),
        Holiday(date(2001, 9, 14), "September 11 attacks"),
        Holiday(date(2004, 6, 11), "National Day of Mourning for President Reagan"),
        Holiday(date(2007, 1, 2), "National Day of Mourning for President Ford"),
        Holiday(date(2012, 10, 29), "Hurricane Sandy"),
        Holiday(date(2012, 10, 30), "Hurricane Sandy"),
        Holiday(date(2018, 12, 5), "National Day of Mourning for President George H. W. Bush"),
        Holiday(date(2025, 1, 9), "National Day of Mourning for President Carter"),
    )

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        easter = easter_sunday(year)
        days = [
            # New Year's Day is not pulled back into the previous year when it falls on a Saturday
            Holiday(_us_observed(date(year, 1, 1), shift_saturday=False), "New Year's Day"),
            Holiday(nth_weekday(year, 2, MONDAY, 3), "Washington's Birthday"),
            Holiday(easter - timedelta(days=2), "Good Friday"),
            Holiday(nth_weekday(year, 5, MONDAY, -1), "Memorial Day"),
            Holiday(_us_observed(date(year, 7, 4)), "Independence Day"),
            Holiday(nth_weekday(year, 9, MONDAY, 1), "Labor Day"),
            Holiday(nth_weekday(year, 11, THURSDAY, 4), "Thanksgiving Day"),
            Holiday(_us_observed(date(year, 12, 25)), "Christmas Day"),
        ]
        if year >= 1998:  # a federal holiday from 1986, but the exchange first closed for it in 1998
            days.append(Holiday(nth_weekday(year, 1, MONDAY, 3), "Martin Luther King Jr. Day"))
        if year >= 2022:  # Juneteenth became a market holiday in 2022
            days.append(Holiday(_us_observed(date(year, 6, 19)), "Juneteenth National Independence Day"))
        return tuple(days)


class SIFMACalendar(TradingCalendar):
    """US bond market, on SIFMA's recommended full closes.

    The bond market keeps Columbus Day and Veterans Day, which the equity market does
    not. It observes Martin Luther King Jr. Day from 1983. A Veterans Day that falls on
    a Saturday is not moved to the Friday.

    Good Friday is a full close, except when it falls on the day the monthly
    employment report is published. SIFMA then recommends an early close instead, so
    the market is open. SIFMA decides this year by year: the years it has decided are
    data. Later years are projected by the pattern those decisions follow - Good
    Friday falling on the first Friday of the month, when the report is normally
    released.
    """

    name = "SIFMA"
    timezone = "America/New_York"
    description = "US fixed income market (SIFMA)"
    good_friday_open = frozenset({1996, 1999, 2007, 2010, 2012, 2015, 2021, 2023, 2026})
    decided_through = 2026
    special_closures = (
        Holiday(date(2004, 6, 11), "National Day of Mourning for President Reagan"),
        Holiday(date(2012, 10, 30), "Hurricane Sandy"),
        Holiday(date(2018, 12, 5), "National Day of Mourning for President George H. W. Bush"),
    )

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        easter = easter_sunday(year)
        veterans = date(year, 11, 11)
        days = [
            Holiday(_us_observed(date(year, 1, 1), shift_saturday=False), "New Year's Day"),
            Holiday(nth_weekday(year, 2, MONDAY, 3), "Washington's Birthday"),
            Holiday(nth_weekday(year, 5, MONDAY, -1), "Memorial Day"),
            Holiday(_us_observed(date(year, 7, 4)), "Independence Day"),
            Holiday(nth_weekday(year, 9, MONDAY, 1), "Labor Day"),
            Holiday(nth_weekday(year, 10, MONDAY, 2), "Columbus Day"),
            Holiday(nth_weekday(year, 11, THURSDAY, 4), "Thanksgiving Day"),
            Holiday(_us_observed(date(year, 12, 25)), "Christmas Day"),
        ]
        if year >= 1983:
            days.append(Holiday(nth_weekday(year, 1, MONDAY, 3), "Martin Luther King Jr. Day"))
        days.append(Holiday(easter - timedelta(days=2), "Good Friday"))
        if veterans.weekday() != SATURDAY:
            days.append(Holiday(_us_observed(veterans), "Veterans Day"))
        if year >= 2022:
            days.append(Holiday(_us_observed(date(year, 6, 19)), "Juneteenth National Independence Day"))
        return tuple(days)

    def special_openings(self, year: int) -> frozenset[date]:
        good_friday = easter_sunday(year) - timedelta(days=2)
        decided = year in self.good_friday_open if year <= self.decided_through else good_friday.day <= 7
        return frozenset({good_friday}) if decided else frozenset()


class LSECalendar(TradingCalendar):
    """London Stock Exchange.

    The early May and spring bank holidays have been moved by proclamation for
    national occasions: VE Day anniversaries in 1995 and 2020, and the jubilees of 2002,
    2012 and 2022. Such years are data, as are the one-off bank holidays for royal
    events and the millennium.
    """

    name = "XLON"
    timezone = "Europe/London"
    description = "London Stock Exchange"
    moved_early_may: ClassVar[dict[int, date]] = {1995: date(1995, 5, 8), 2020: date(2020, 5, 8)}
    moved_spring: ClassVar[dict[int, date]] = {2002: date(2002, 6, 4), 2012: date(2012, 6, 4), 2022: date(2022, 6, 2)}
    special_closures = (
        Holiday(date(1999, 12, 31), "Millennium Celebrations"),
        Holiday(date(2002, 6, 3), "Golden Jubilee of Queen Elizabeth II"),
        Holiday(date(2011, 4, 29), "Wedding of Prince William and Catherine Middleton"),
        Holiday(date(2012, 6, 5), "Diamond Jubilee of Queen Elizabeth II"),
        Holiday(date(2022, 6, 3), "Platinum Jubilee of Queen Elizabeth II"),
        Holiday(date(2022, 9, 19), "State Funeral of Queen Elizabeth II"),
        Holiday(date(2023, 5, 8), "Coronation of King Charles III"),
    )

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        easter = easter_sunday(year)
        taken: set[date] = set()
        result: list[Holiday] = []
        for day, label in (
            (date(year, 1, 1), "New Year's Day"),
            (easter - timedelta(days=2), "Good Friday"),
            (easter + timedelta(days=1), "Easter Monday"),
            (date(year, 12, 25), "Christmas Day"),
            (date(year, 12, 26), "Boxing Day"),
        ):
            observed = _uk_substitute(day, taken)
            taken.add(observed)
            result.append(Holiday(observed, label if observed == day else f"{label} (substitute day)"))
        result.append(
            Holiday(self.moved_early_may.get(year, nth_weekday(year, 5, MONDAY, 1)), "Early May Bank Holiday")
        )
        result.append(Holiday(self.moved_spring.get(year, nth_weekday(year, 5, MONDAY, -1)), "Spring Bank Holiday"))
        result.append(Holiday(nth_weekday(year, 8, MONDAY, -1), "Summer Bank Holiday"))
        return tuple(result)


class TARGETCalendar(TradingCalendar):
    """TARGET2, the euro area settlement calendar.

    TARGET opened on 4 January 1999 closing only on New Year's Day and Christmas
    Day. Good Friday, Easter Monday, Labour Day and 26 December were added from 2000.
    It also closed on 31 December 1999 (the millennium) and 31 December 2001 (the
    euro cash changeover).
    """

    name = "TARGET"
    timezone = "Europe/Brussels"
    description = "Euro area settlement (TARGET2)"
    special_closures = (
        Holiday(date(1999, 12, 31), "Millennium"),
        Holiday(date(2001, 12, 31), "Euro cash changeover"),
    )

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        days = [Holiday(date(year, 1, 1), "New Year's Day"), Holiday(date(year, 12, 25), "Christmas Day")]
        if year >= 2000:
            easter = easter_sunday(year)
            days += [
                Holiday(easter - timedelta(days=2), "Good Friday"),
                Holiday(easter + timedelta(days=1), "Easter Monday"),
                Holiday(date(year, 5, 1), "Labour Day"),
                Holiday(date(year, 12, 26), "Christmas Holiday"),
            ]
        return tuple(days)


class XETRACalendar(TradingCalendar):
    """Xetra, the German electronic exchange.

    Whit Monday, Ascension and German Unity Day are trading days on Xetra. New
    Year's Eve is not: the Deutsche Boerse trading calendar lists it as a closure,
    although QuantLib's Xetra calendar does not.
    """

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
    """Tokyo Stock Exchange, on the Act on National Holidays as it stood each year.

    The rules that moved:

    - the Happy Monday reforms took Coming of Age Day and Sports Day to Mondays in
      2000, and Marine Day and Respect for the Aged Day in 2003;
    - Marine Day began in 1996 and Mountain Day in 2016, and the Olympic special
      measures moved three holidays in 2020 and 2021;
    - since 2007 a Sunday holiday is substituted by the next day that is not a holiday
      (before then, only by the Monday);
    - a day sandwiched between two holidays is a holiday - which is how Golden Week and
      the "Silver Weeks" of 2009, 2015 and 2026 arise;
    - the Emperor's Birthday moved with the accession.

    The equinoxes are computed (see ``meridian.core.astronomy``). The exchange also
    closes on 2 and 3 January and 31 December.
    """

    name = "XTKS"
    timezone = "Asia/Tokyo"
    description = "Tokyo Stock Exchange"
    special_closures = (
        Holiday(date(1990, 11, 12), "Enthronement Ceremony of Emperor Akihito"),
        Holiday(date(1993, 6, 9), "Wedding of Crown Prince Naruhito"),
        Holiday(date(2019, 10, 22), "Enthronement Ceremony of Emperor Naruhito"),
    )
    _olympic: ClassVar[dict[str, dict[int, date]]] = {
        "Marine Day": {2020: date(2020, 7, 23), 2021: date(2021, 7, 22)},
        "Sports Day": {2020: date(2020, 7, 24), 2021: date(2021, 7, 23)},
        "Mountain Day": {2020: date(2020, 8, 10), 2021: date(2021, 8, 8)},
    }

    def statutory_holidays(self, year: int) -> list[tuple[date, str]]:
        """The national holidays of the year, before substitution."""

        def moved(label: str, usual: date) -> tuple[date, str]:
            return self._olympic.get(label, {}).get(year, usual), label

        days = [
            (date(year, 1, 1), "New Year's Day"),
            (date(year, 1, 15) if year < 2000 else nth_weekday(year, 1, MONDAY, 2), "Coming of Age Day"),
            (date(year, 2, 11), "National Foundation Day"),
            (vernal_equinox(year), "Vernal Equinox Day"),
            (date(year, 4, 29), "Showa Day" if year >= 2007 else "Greenery Day"),
            (date(year, 5, 3), "Constitution Memorial Day"),
            (date(year, 5, 5), "Children's Day"),
            (date(year, 9, 15) if year < 2003 else nth_weekday(year, 9, MONDAY, 3), "Respect for the Aged Day"),
            (autumnal_equinox(year), "Autumnal Equinox Day"),
            moved("Sports Day", date(year, 10, 10) if year < 2000 else nth_weekday(year, 10, MONDAY, 2)),
            (date(year, 11, 3), "Culture Day"),
            (date(year, 11, 23), "Labour Thanksgiving Day"),
        ]
        if year >= 2007:
            days.append((date(year, 5, 4), "Greenery Day"))
        if year >= 1996:
            days.append(moved("Marine Day", date(year, 7, 20) if year < 2003 else nth_weekday(year, 7, MONDAY, 3)))
        if year >= 2016:
            days.append(moved("Mountain Day", date(year, 8, 11)))
        if 1989 <= year <= 2018:
            days.append((date(year, 12, 23), "The Emperor's Birthday"))
        elif year >= 2020:
            days.append((date(year, 2, 23), "The Emperor's Birthday"))
        if year == 2019:
            days.append((date(2019, 5, 1), "Accession of Emperor Naruhito"))
        days += [(holiday.day, holiday.name) for holiday in self.special_closures if holiday.day.year == year]
        return days

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        statutory = self.statutory_holidays(year)
        national = {day for day, _ in statutory}
        result = [Holiday(day, label) for day, label in statutory]

        taken = set(national)
        for day, label in statutory:
            if day.weekday() != SUNDAY:
                continue
            substitute = day + timedelta(days=1)
            if year >= 2007:
                while substitute in taken:
                    substitute += timedelta(days=1)
            if substitute not in taken:
                taken.add(substitute)
                result.append(Holiday(substitute, f"{label} (substitute holiday)"))

        # A day between two national holidays is itself a holiday, unless it is a Sunday
        for day in sorted(national):
            between = day + timedelta(days=1)
            if between + timedelta(days=1) in national and between not in taken and between.weekday() != SUNDAY:
                taken.add(between)
                result.append(Holiday(between, "Citizens' Holiday"))

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


class ScheduledCalendar(TradingCalendar):
    """A calendar's rules alone: no special closures, no special openings."""

    def __init__(self, actual: TradingCalendar) -> None:
        self.actual = actual
        self.name = actual.name
        self.timezone = actual.timezone
        self.description = f"{actual.description} (scheduled)"

    def named_holidays(self, year: int) -> tuple[Holiday, ...]:
        if isinstance(self.actual, JointCalendar):
            joint = JointCalendar([member.scheduled() for member in self.actual.calendars], mode=self.actual.mode)
            return joint.named_holidays(year)
        return self.actual.named_holidays(year)

    def scheduled(self) -> TradingCalendar:
        return self

    def __repr__(self) -> str:
        return f"<ScheduledCalendar {self.name}>"


@lru_cache(maxsize=64)
def _scheduled_view(calendar: TradingCalendar) -> ScheduledCalendar:
    return ScheduledCalendar(calendar)


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
