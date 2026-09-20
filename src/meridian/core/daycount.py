"""Day-count conventions.

The fraction of a year between two dates is not one number: a money market deposit
accrues on ACT/360, a gilt on ACT/ACT, a US corporate bond on 30/360 and a
Brazilian instrument on business days over 252. Using the wrong one misstates
accrued interest, so the convention travels with the instrument.

Three of these conventions need context beyond the two dates. ACT/ACT ICMA needs
the coupon period the dates sit inside and the coupon frequency, because it
divides by the length of that period rather than by the length of a year.
BUS/252 needs a trading calendar, because its numerator is business days. 30E/360
ISDA needs to know whether the end date is the instrument's maturity. Rather than
pretend otherwise, ``year_fraction`` takes those as optional arguments and raises
if a convention is used without what it needs.
"""

from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from .decimals import to_decimal
from .exceptions import ValidationError

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to the type checker
    from .calendars import TradingCalendar


class DayCountConvention(str, Enum):
    ACT_360 = "ACT/360"
    ACT_365F = "ACT/365F"
    ACT_365_25 = "ACT/365.25"
    ACT_ACT_ISDA = "ACT/ACT ISDA"
    ACT_ACT_ICMA = "ACT/ACT ICMA"
    THIRTY_360_US = "30/360 US"
    THIRTY_E_360 = "30E/360"
    THIRTY_E_360_ISDA = "30E/360 ISDA"
    BUS_252 = "BUS/252"

    @property
    def needs_schedule(self) -> bool:
        """True when the convention cannot be evaluated from two dates alone."""
        return self in {DayCountConvention.ACT_ACT_ICMA, DayCountConvention.BUS_252}

    @property
    def denominator_label(self) -> str:
        return {
            DayCountConvention.ACT_360: "360",
            DayCountConvention.ACT_365F: "365",
            DayCountConvention.ACT_365_25: "365.25",
            DayCountConvention.ACT_ACT_ISDA: "365 or 366, per calendar year",
            DayCountConvention.ACT_ACT_ICMA: "coupon period x frequency",
            DayCountConvention.THIRTY_360_US: "360",
            DayCountConvention.THIRTY_E_360: "360",
            DayCountConvention.THIRTY_E_360_ISDA: "360",
            DayCountConvention.BUS_252: "252",
        }[self]


def _days_360(start: date, end: date, *, european: bool) -> int:
    d1, d2 = start.day, end.day
    if european:
        d1 = min(d1, 30)
        d2 = min(d2, 30)
    else:
        if d1 == 31:
            d1 = 30
        if d2 == 31 and d1 == 30:
            d2 = 30
    return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)


def _is_last_day_of_month(day: date) -> bool:
    return day.day == _calendar.monthrange(day.year, day.month)[1]


def _days_30e_360_isda(start: date, end: date, *, end_is_maturity: bool) -> int:
    """30E/360 ISDA: month ends become the 30th, except February at maturity."""
    d1 = 30 if _is_last_day_of_month(start) else start.day
    d2 = end.day
    if _is_last_day_of_month(end) and not (end_is_maturity and end.month == 2):
        d2 = 30
    return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)


def year_fraction(
    start: date,
    end: date,
    convention: DayCountConvention | str = DayCountConvention.ACT_365F,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    frequency: int | None = None,
    calendar: TradingCalendar | str | None = None,
    end_is_maturity: bool = False,
) -> Decimal:
    """Year fraction between two dates under the given convention.

    ``period_start``/``period_end``/``frequency`` are the surrounding coupon period
    and the number of coupons a year, required by ACT/ACT ICMA. ``calendar`` is
    required by BUS/252. ``end_is_maturity`` matters only to 30E/360 ISDA.
    """
    convention = DayCountConvention(convention) if not isinstance(convention, DayCountConvention) else convention
    if end < start:
        return -year_fraction(
            end,
            start,
            convention,
            period_start=period_start,
            period_end=period_end,
            frequency=frequency,
            calendar=calendar,
            end_is_maturity=end_is_maturity,
        )
    if end == start:
        return Decimal(0)

    if convention is DayCountConvention.ACT_360:
        return to_decimal((end - start).days) / Decimal(360)
    if convention is DayCountConvention.ACT_365F:
        return to_decimal((end - start).days) / Decimal(365)
    if convention is DayCountConvention.ACT_365_25:
        return to_decimal((end - start).days) / Decimal("365.25")
    if convention is DayCountConvention.THIRTY_360_US:
        return to_decimal(_days_360(start, end, european=False)) / Decimal(360)
    if convention is DayCountConvention.THIRTY_E_360:
        return to_decimal(_days_360(start, end, european=True)) / Decimal(360)
    if convention is DayCountConvention.THIRTY_E_360_ISDA:
        return to_decimal(_days_30e_360_isda(start, end, end_is_maturity=end_is_maturity)) / Decimal(360)
    if convention is DayCountConvention.ACT_ACT_ISDA:
        return _act_act_isda(start, end)
    if convention is DayCountConvention.ACT_ACT_ICMA:
        return _act_act_icma(start, end, period_start, period_end, frequency)
    if convention is DayCountConvention.BUS_252:
        return _bus_252(start, end, calendar)
    raise ValidationError(f"Unsupported day count convention {convention!r}")  # pragma: no cover


def _act_act_icma(
    start: date,
    end: date,
    period_start: date | None,
    period_end: date | None,
    frequency: int | None,
) -> Decimal:
    """Days in the period over the length of the coupon period it sits in, times the frequency."""
    if period_start is None or period_end is None or frequency is None:
        raise ValidationError("ACT/ACT ICMA needs period_start, period_end and frequency")
    if frequency <= 0:
        raise ValidationError("Coupon frequency must be positive")
    period_days = (period_end - period_start).days
    if period_days <= 0:
        raise ValidationError("The reference coupon period must be non-empty")
    return to_decimal((end - start).days) / (Decimal(period_days) * Decimal(frequency))


def _bus_252(start: date, end: date, calendar: TradingCalendar | str | None) -> Decimal:
    """Business days over 252, the Brazilian convention - and the honest one for anything driven by trading days."""
    if calendar is None:
        raise ValidationError("BUS/252 needs a trading calendar")
    from .calendars import get_calendar  # imported here to keep the module import cycle-free

    resolved = get_calendar(calendar)
    return to_decimal(resolved.business_days_between(start, end)) / Decimal(252)


def _act_act_isda(start: date, end: date) -> Decimal:
    """Split the period at year ends and weight each part by that year's length."""
    total = Decimal(0)
    for year in range(start.year, end.year + 1):
        year_start = max(start, date(year, 1, 1))
        year_end = min(end, date(year + 1, 1, 1))
        if year_end <= year_start:
            continue
        days_in_year = Decimal(366 if _calendar.isleap(year) else 365)
        total += to_decimal((year_end - year_start).days) / days_in_year
    return total


@dataclass(frozen=True, slots=True)
class AccrualPeriod:
    """A period with the convention that governs it, and the context that convention needs."""

    start: date
    end: date
    convention: DayCountConvention = DayCountConvention.ACT_365F
    period_start: date | None = None
    period_end: date | None = None
    frequency: int | None = None
    calendar: str | None = None
    end_is_maturity: bool = False

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def year_fraction(self) -> Decimal:
        return year_fraction(
            self.start,
            self.end,
            self.convention,
            period_start=self.period_start or self.start,
            period_end=self.period_end or self.end,
            frequency=self.frequency,
            calendar=self.calendar,
            end_is_maturity=self.end_is_maturity,
        )

    def accrue(self, notional: Decimal, annual_rate: Decimal) -> Decimal:
        """Simple interest accrued over the period."""
        return to_decimal(notional) * to_decimal(annual_rate) * self.year_fraction


def compare_conventions(
    start: date,
    end: date,
    *,
    notional: Decimal | int = 1_000_000,
    annual_rate: Decimal | str = "0.05",
    calendar: TradingCalendar | str = "XNYS",
    frequency: int = 2,
) -> dict[DayCountConvention, tuple[Decimal, Decimal]]:
    """Year fraction and accrued interest for every convention over the same period.

    The spread between the largest and smallest result is the answer to "does the
    convention really matter?" - on a million dollars over six months it is worth
    hundreds of dollars, every period, on every instrument.
    """
    results: dict[DayCountConvention, tuple[Decimal, Decimal]] = {}
    rate = to_decimal(annual_rate)
    amount = to_decimal(notional)
    for convention in DayCountConvention:
        fraction = year_fraction(
            start,
            end,
            convention,
            period_start=start,
            period_end=end,
            frequency=frequency,
            calendar=calendar,
            end_is_maturity=False,
        )
        results[convention] = (fraction, amount * rate * fraction)
    return results
