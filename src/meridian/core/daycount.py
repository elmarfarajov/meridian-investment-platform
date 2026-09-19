"""Day-count conventions.

The fraction of a year between two dates is not one number: a money market deposit
accrues on ACT/360, a gilt on ACT/ACT and a US corporate bond on 30/360. Using the
wrong one misstates accrued interest, so the convention travels with the instrument.
"""

from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from .decimals import to_decimal
from .exceptions import ValidationError


class DayCountConvention(str, Enum):
    ACT_360 = "ACT/360"
    ACT_365F = "ACT/365F"
    ACT_ACT_ISDA = "ACT/ACT ISDA"
    THIRTY_360_US = "30/360 US"
    THIRTY_E_360 = "30E/360"


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


def year_fraction(start: date, end: date, convention: DayCountConvention | str = DayCountConvention.ACT_365F) -> Decimal:
    """Year fraction between two dates under the given convention."""
    convention = DayCountConvention(convention) if not isinstance(convention, DayCountConvention) else convention
    if end < start:
        return -year_fraction(end, start, convention)
    if end == start:
        return Decimal(0)

    if convention is DayCountConvention.ACT_360:
        return to_decimal((end - start).days) / Decimal(360)
    if convention is DayCountConvention.ACT_365F:
        return to_decimal((end - start).days) / Decimal(365)
    if convention is DayCountConvention.THIRTY_360_US:
        return to_decimal(_days_360(start, end, european=False)) / Decimal(360)
    if convention is DayCountConvention.THIRTY_E_360:
        return to_decimal(_days_360(start, end, european=True)) / Decimal(360)
    if convention is DayCountConvention.ACT_ACT_ISDA:
        return _act_act_isda(start, end)
    raise ValidationError(f"Unsupported day count convention {convention!r}")  # pragma: no cover


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
    """A period with the convention that governs it."""

    start: date
    end: date
    convention: DayCountConvention = DayCountConvention.ACT_365F

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def year_fraction(self) -> Decimal:
        return year_fraction(self.start, self.end, self.convention)

    def accrue(self, notional: Decimal, annual_rate: Decimal) -> Decimal:
        """Simple interest accrued over the period."""
        return to_decimal(notional) * to_decimal(annual_rate) * self.year_fraction
