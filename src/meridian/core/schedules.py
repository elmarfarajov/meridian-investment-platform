"""Payment schedules.

A bond, a swap leg and a loan all share one piece of machinery: a list of accrual
periods with a payment date attached to each. Getting it right is unglamorous and
consequential. The parts that are easy to get wrong, and are handled explicitly
here, are:

*Rolling backwards.* Schedules are generated from the maturity date backwards, not
from the start forwards, because the maturity is the date that is contractually
fixed. Rolling forwards from the start leaves the final period as the odd one out,
which is the wrong place to put the irregularity.

*The end-of-month rule.* A bond that starts on 31 January and pays quarterly pays
on 30 April, not on 1 May - and then on 31 July, not on 30 July. The rule is
sticky: once a schedule is anchored on a month end it stays on month ends.

*Stubs.* A period that is shorter or longer than the others has to go somewhere,
and which end it goes on changes the cash flows.

*Adjustment versus accrual.* A payment date moves to a business day; whether the
accrual period moves with it is a separate decision, and both behaviours exist in
the market.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from itertools import pairwise

from .calendars import BusinessDayConvention, TradingCalendar, get_calendar
from .daycount import DayCountConvention, year_fraction
from .enums import Frequency
from .exceptions import ValidationError

_MONTHS_PER_PERIOD = {
    Frequency.ANNUAL: 12,
    Frequency.SEMI_ANNUAL: 6,
    Frequency.QUARTERLY: 3,
    Frequency.MONTHLY: 1,
}


class StubConvention(str, Enum):
    """Where an irregular period is placed when the term is not a whole number of periods."""

    SHORT_FRONT = "short_front"
    LONG_FRONT = "long_front"
    SHORT_BACK = "short_back"
    LONG_BACK = "long_back"
    NONE = "none"


class RollConvention(str, Enum):
    """What the schedule is anchored on."""

    DAY_OF_MONTH = "day_of_month"
    END_OF_MONTH = "end_of_month"


def is_end_of_month(day: date) -> bool:
    return day.day == _calendar.monthrange(day.year, day.month)[1]


def add_months(day: date, months: int, *, end_of_month: bool = False) -> date:
    """Add months, clamping to the end of the target month.

    With ``end_of_month`` the result is pinned to the last day of the target month,
    which is the sticky behaviour a month-end schedule needs.
    """
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    last = _calendar.monthrange(year, month)[1]
    return date(year, month, last if end_of_month else min(day.day, last))


@dataclass(frozen=True, slots=True)
class SchedulePeriod:
    """One accrual period and the date it pays."""

    start: date
    end: date
    payment_date: date
    is_stub: bool = False
    index: int = 0

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def year_fraction(
        self,
        convention: DayCountConvention | str = DayCountConvention.ACT_365F,
        *,
        frequency: int | None = None,
        calendar: TradingCalendar | str | None = None,
        is_final: bool = False,
    ) -> Decimal:
        return year_fraction(
            self.start,
            self.end,
            convention,
            period_start=self.start,
            period_end=self.end,
            frequency=frequency,
            calendar=calendar,
            end_is_maturity=is_final,
        )

    def __str__(self) -> str:
        stub = " (stub)" if self.is_stub else ""
        return f"{self.start.isoformat()} -> {self.end.isoformat()} pays {self.payment_date.isoformat()}{stub}"


@dataclass(frozen=True, slots=True)
class Schedule:
    """The full set of periods for an instrument, plus how it was built."""

    periods: tuple[SchedulePeriod, ...]
    frequency: Frequency
    convention: BusinessDayConvention
    calendar_name: str
    stub: StubConvention
    roll: RollConvention
    payment_lag: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.periods:
            raise ValidationError("A schedule needs at least one period")

    def __len__(self) -> int:
        return len(self.periods)

    def __iter__(self) -> Iterator[SchedulePeriod]:
        return iter(self.periods)

    def __getitem__(self, item: int) -> SchedulePeriod:
        return self.periods[item]

    @property
    def start(self) -> date:
        return self.periods[0].start

    @property
    def end(self) -> date:
        return self.periods[-1].end

    @property
    def payment_dates(self) -> tuple[date, ...]:
        return tuple(period.payment_date for period in self.periods)

    @property
    def accrual_dates(self) -> tuple[date, ...]:
        return (self.periods[0].start, *(period.end for period in self.periods))

    @property
    def has_stub(self) -> bool:
        return any(period.is_stub for period in self.periods)

    def period_containing(self, day: date) -> SchedulePeriod | None:
        """The accrual period a date falls in, which is what accrued interest needs."""
        for period in self.periods:
            if period.start <= day < period.end:
                return period
        if day == self.end:
            return self.periods[-1]
        return None

    def next_payment_after(self, day: date) -> SchedulePeriod | None:
        for period in self.periods:
            if period.payment_date > day:
                return period
        return None

    def remaining(self, day: date) -> tuple[SchedulePeriod, ...]:
        """The periods that still pay after a valuation date."""
        return tuple(period for period in self.periods if period.payment_date > day)

    def describe(self) -> str:
        return (
            f"{len(self)} x {self.frequency.value} from {self.start.isoformat()} to {self.end.isoformat()} "
            f"on {self.calendar_name}, {self.convention.value}" + (", with a stub" if self.has_stub else "")
        )


def _unadjusted_dates(
    start: date,
    end: date,
    months: int,
    stub: StubConvention,
    end_of_month: bool,
) -> list[date]:
    """Roll backwards from maturity, then decide what to do with the leftover period."""
    dates: list[date] = [end]
    cursor = end
    while True:
        previous = add_months(cursor, -months, end_of_month=end_of_month)
        if previous <= start:
            break
        dates.append(previous)
        cursor = previous
    dates.append(start)
    dates.reverse()

    if len(dates) < 2:  # pragma: no cover - guarded by the caller
        raise ValidationError("A schedule needs at least one period")

    front_days = (dates[1] - dates[0]).days
    regular_days = (dates[2] - dates[1]).days if len(dates) > 2 else front_days
    is_short_front = front_days < regular_days * 0.6

    if stub is StubConvention.NONE and is_short_front:
        raise ValidationError(
            f"The term {start} to {end} is not a whole number of {months}-month periods; choose a stub convention"
        )
    if is_short_front and stub in {StubConvention.LONG_FRONT} and len(dates) > 2:
        del dates[1]  # merge the stub into the next period, making a long first period
    elif stub in {StubConvention.SHORT_BACK, StubConvention.LONG_BACK} and is_short_front:
        # Roll forwards instead, so the irregular period lands at the end
        forward: list[date] = [start]
        cursor = start
        while True:
            nxt = add_months(cursor, months, end_of_month=end_of_month)
            if nxt >= end:
                break
            forward.append(nxt)
            cursor = nxt
        forward.append(end)
        if stub is StubConvention.LONG_BACK and len(forward) > 2:
            del forward[-2]
        dates = forward
    return dates


def generate_schedule(
    start: date,
    end: date,
    frequency: Frequency | str = Frequency.SEMI_ANNUAL,
    *,
    calendar: TradingCalendar | str = "XNYS",
    convention: BusinessDayConvention = BusinessDayConvention.MODIFIED_FOLLOWING,
    stub: StubConvention = StubConvention.SHORT_FRONT,
    roll: RollConvention | None = None,
    payment_lag: int = 0,
    adjust_accrual: bool = False,
) -> Schedule:
    """Build a payment schedule between two dates.

    ``adjust_accrual`` decides whether the accrual periods follow the adjusted
    payment dates or stay on the unadjusted calendar dates. Both conventions exist:
    most bonds accrue on unadjusted dates and pay on adjusted ones.
    """
    frequency = Frequency(frequency) if not isinstance(frequency, Frequency) else frequency
    if frequency not in _MONTHS_PER_PERIOD:
        raise ValidationError(f"{frequency.value} schedules are not supported; use monthly or longer")
    if end <= start:
        raise ValidationError(f"Schedule end {end} must be after start {start}")

    trading_calendar = get_calendar(calendar)
    months = _MONTHS_PER_PERIOD[frequency]
    if roll is None:
        roll = RollConvention.END_OF_MONTH if is_end_of_month(end) else RollConvention.DAY_OF_MONTH
    end_of_month = roll is RollConvention.END_OF_MONTH

    dates = _unadjusted_dates(start, end, months, stub, end_of_month)
    regular = months * 30  # nominal length, used only to label a period as irregular

    periods: list[SchedulePeriod] = []
    for index, (period_start, period_end) in enumerate(pairwise(dates)):
        payment = trading_calendar.adjust(period_end, convention)
        if payment_lag:
            payment = trading_calendar.add_business_days(payment, payment_lag)
        accrual_start = trading_calendar.adjust(period_start, convention) if adjust_accrual else period_start
        accrual_end = trading_calendar.adjust(period_end, convention) if adjust_accrual else period_end
        nominal = (period_end - period_start).days
        periods.append(
            SchedulePeriod(
                start=accrual_start,
                end=accrual_end,
                payment_date=payment,
                is_stub=abs(nominal - regular) > regular * 0.35,
                index=index,
            )
        )

    return Schedule(
        periods=tuple(periods),
        frequency=frequency,
        convention=convention,
        calendar_name=trading_calendar.name,
        stub=stub,
        roll=roll,
        payment_lag=payment_lag,
        metadata={"adjust_accrual": str(adjust_accrual)},
    )


def imm_date(year: int, month: int) -> date:
    """The third Wednesday of a month - the IMM roll used by futures and many swaps."""
    first = date(year, month, 1)
    offset = (2 - first.weekday()) % 7  # 2 = Wednesday
    return first + timedelta(days=offset + 14)


def imm_dates(year: int) -> tuple[date, ...]:
    """The four quarterly IMM dates of a year."""
    return tuple(imm_date(year, month) for month in (3, 6, 9, 12))


def accrual_fractions(
    schedule: Schedule,
    convention: DayCountConvention | str = DayCountConvention.THIRTY_360_US,
    *,
    calendar: TradingCalendar | str | None = None,
) -> tuple[Decimal, ...]:
    """The year fraction of every period, which is what turns a schedule into cash flows."""
    per_year = schedule.frequency.periods_per_year
    return tuple(
        period.year_fraction(
            convention,
            frequency=per_year,
            calendar=calendar or schedule.calendar_name,
            is_final=index == len(schedule) - 1,
        )
        for index, period in enumerate(schedule)
    )


def schedule_summary(schedules: Sequence[Schedule]) -> list[tuple[str, int, str, str]]:
    """Rows for a table or a chart: name, period count, first payment, last payment."""
    return [
        (
            schedule.describe(),
            len(schedule),
            schedule.payment_dates[0].isoformat(),
            schedule.payment_dates[-1].isoformat(),
        )
        for schedule in schedules
    ]
