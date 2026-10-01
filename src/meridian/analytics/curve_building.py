"""Curves built from market instruments on their real dates.

``bootstrap_par_curve`` works on a grid of year fractions: a 5-year par yield is a
bond paying exactly every half year for exactly five years. That is the right
abstraction for a constant-maturity series such as the Treasury's par curve, and the
wrong one for a trading desk. A desk's curve is built from instruments with dates,
and each date is decided by a convention:

- **spot lag**: a SOFR swap traded today starts two business days later;
- **calendars**: every date is rolled to a business day, modified following;
- **day counts**: the fixed leg accrues ACT/360, and the curve's own clock is ACT/365F;
- **payment lags**: SOFR swaps usually pay two business days after the period ends.

This module builds such a curve from deposits and overnight index swaps.

**Every instrument prices back to its quote.** The floating leg of an OIS compounds
the daily overnight rate. When the forecasting and discounting curve is the same,
that compounding telescopes to ``DF(start) / DF(end)``. The par rate of a swap is
therefore a ratio of discount factors, and the bootstrap solves one pillar at a
time. Interpolators that are not local (monotone convex, monotone cubic) couple the
pillars, so the pass is repeated until nothing moves.

**Risk is reported in the instruments that hedge it.** Bumping each quote by a basis
point and rebuilding gives the Jacobian of the zero curve with respect to the market,
and a portfolio's bucketed DV01 in the quoted instruments. The desk can trade that
DV01 directly as a hedge.

The construction is checked against QuantLib's ``PiecewiseLogLinearDiscount`` with
``DepositRateHelper`` and ``OISRateHelper`` (see ``meridian.devtools.reference``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..core.calendars import BusinessDayConvention, TradingCalendar, get_calendar
from ..core.compounding import Compounding
from ..core.daycount import DayCountConvention, year_fraction
from ..core.enums import Frequency
from ..core.exceptions import CurveError, ValidationError
from ..core.interpolation import InterpolationMethod
from ..core.schedules import RollConvention, add_months, generate_schedule
from .curves import YieldCurve
from .solvers import solve

CURVE_DAY_COUNT = DayCountConvention.ACT_365F
_TENOR = re.compile(r"^\s*(\d+)\s*([DWMY])\s*$", re.IGNORECASE)
_LOCAL = frozenset({InterpolationMethod.LOG_LINEAR, InterpolationMethod.FLAT_FORWARD, InterpolationMethod.LINEAR})


@dataclass(frozen=True, slots=True, order=True)
class Tenor:
    """A length of time as the market quotes it: 1W, 3M, 18M, 10Y."""

    count: int
    unit: str

    @classmethod
    def parse(cls, text: str | Tenor) -> Tenor:
        if isinstance(text, Tenor):
            return text
        match = _TENOR.match(text)
        if not match:
            raise ValidationError(f"Not a tenor: {text!r} (expected something like 1W, 3M or 10Y)")
        return cls(int(match.group(1)), match.group(2).upper())

    def add_to(self, day: date) -> date:
        """The unadjusted date this tenor after ``day``; months keep the day, clamped to the month end."""
        if self.unit == "D":
            return day + timedelta(days=self.count)
        if self.unit == "W":
            return day + timedelta(weeks=self.count)
        return add_months(day, self.count * (12 if self.unit == "Y" else 1))

    @property
    def years(self) -> float:
        """A nominal length, for ordering and labels only - never for accrual."""
        return self.count * {"D": 1 / 365, "W": 7 / 365, "M": 1 / 12, "Y": 1.0}[self.unit]

    def __str__(self) -> str:
        return f"{self.count}{self.unit}"


# ---------------------------------------------------------------------------- instruments
DiscountFunction = Callable[[date], float]


@dataclass(frozen=True, slots=True)
class Deposit:
    """A money-market deposit: one simple-interest payment at the end."""

    label: str
    quote: float
    start: date
    end: date
    day_count: DayCountConvention = DayCountConvention.ACT_360

    @property
    def pillar(self) -> date:
        return self.end

    @property
    def accrual(self) -> float:
        return float(year_fraction(self.start, self.end, self.day_count))

    def implied_rate(self, discount: DiscountFunction) -> float:
        return (discount(self.start) / discount(self.end) - 1.0) / self.accrual


@dataclass(frozen=True, slots=True)
class SwapPeriod:
    """One period of an OIS: accrual dates, the payment date and the fixed-leg accrual."""

    start: date
    end: date
    payment: date
    accrual: float


@dataclass(frozen=True, slots=True)
class OvernightIndexSwap:
    """A fixed-for-compounded-overnight swap (SOFR, SONIA, ESTR), quoted by its fixed rate.

    Both legs share the periods. The floating coupon for a period is the daily
    overnight rate compounded, which is ``DF(start) / DF(end) - 1`` on the curve that
    forecasts it. Paid on the payment date, it is worth ``DF(payment)`` times that.
    """

    label: str
    quote: float
    periods: tuple[SwapPeriod, ...]
    day_count: DayCountConvention = DayCountConvention.ACT_360

    @property
    def start(self) -> date:
        return self.periods[0].start

    @property
    def maturity(self) -> date:
        return self.periods[-1].end

    @property
    def pillar(self) -> date:
        return max(self.periods[-1].end, self.periods[-1].payment)

    def annuity(self, discount: DiscountFunction) -> float:
        """The value of one unit of fixed rate: sum of accrual times discount factor."""
        return sum(period.accrual * discount(period.payment) for period in self.periods)

    def floating_leg(self, discount: DiscountFunction) -> float:
        return sum(
            discount(period.payment) * (discount(period.start) / discount(period.end) - 1.0) for period in self.periods
        )

    def implied_rate(self, discount: DiscountFunction) -> float:
        return self.floating_leg(discount) / self.annuity(discount)

    def value(self, discount: DiscountFunction, notional: float = 1.0) -> float:
        """Value to the fixed-rate receiver at the quoted rate: zero on the curve it built."""
        return notional * (self.quote * self.annuity(discount) - self.floating_leg(discount))


Instrument = Deposit | OvernightIndexSwap


def spot_date(valuation_date: date, calendar: TradingCalendar | str, lag: int) -> date:
    """The start of a spot-starting trade: ``lag`` business days after the trade date."""
    return get_calendar(calendar).add_business_days(valuation_date, lag)


def deposit(
    valuation_date: date,
    tenor: str | Tenor,
    rate: float,
    *,
    calendar: TradingCalendar | str = "SIFMA",
    spot_lag: int = 2,
    convention: BusinessDayConvention = BusinessDayConvention.MODIFIED_FOLLOWING,
    day_count: DayCountConvention = DayCountConvention.ACT_360,
) -> Deposit:
    """A spot-starting deposit, dated the way the market dates it."""
    period = Tenor.parse(tenor)
    trading = get_calendar(calendar)
    start = spot_date(valuation_date, trading, spot_lag)
    end = trading.adjust(period.add_to(start), convention)
    return Deposit(f"{period} deposit", rate, start, end, day_count)


def overnight_index_swap(
    valuation_date: date,
    tenor: str | Tenor,
    rate: float,
    *,
    calendar: TradingCalendar | str = "SIFMA",
    spot_lag: int = 2,
    payment_lag: int = 0,
    day_count: DayCountConvention = DayCountConvention.ACT_360,
    index: str = "SOFR",
) -> OvernightIndexSwap:
    """A spot-starting OIS with annual periods rolled backwards from maturity.

    Periods are adjusted modified following, and a tenor of a year or less is a
    single period. Each payment falls ``payment_lag`` business days after the period
    ends: two for a cleared SOFR swap, zero in the simplest textbook form.
    """
    period = Tenor.parse(tenor)
    trading = get_calendar(calendar)
    start = spot_date(valuation_date, trading, spot_lag)
    schedule = generate_schedule(
        start,
        period.add_to(start),
        Frequency.ANNUAL,
        calendar=trading,
        convention=BusinessDayConvention.MODIFIED_FOLLOWING,
        roll=RollConvention.DAY_OF_MONTH,
        adjust_accrual=True,
    )
    periods = tuple(
        SwapPeriod(
            start=item.start,
            end=item.end,
            payment=trading.add_business_days(item.end, payment_lag) if payment_lag else item.end,
            accrual=float(year_fraction(item.start, item.end, day_count)),
        )
        for item in schedule.periods
    )
    return OvernightIndexSwap(f"{period} {index} OIS", rate, periods, day_count)


# ---------------------------------------------------------------------------- the curve
@dataclass
class InstrumentCurve:
    """A zero curve with the instruments it was built from, and their risk."""

    valuation_date: date
    instruments: tuple[Instrument, ...]
    interpolation: InterpolationMethod
    curve: YieldCurve
    iterations: int = 1
    name: str = "curve"
    _jacobian: list[list[float]] | None = field(default=None, repr=False)

    @property
    def pillars(self) -> tuple[date, ...]:
        return tuple(item.pillar for item in self.instruments)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(item.label for item in self.instruments)

    def time(self, day: date) -> float:
        return float(year_fraction(self.valuation_date, day, CURVE_DAY_COUNT))

    def discount(self, day: date) -> float:
        return self.curve.discount_factor(self.time(day))

    def zero_rate(self, day: date) -> float:
        return self.curve.zero_rate(self.time(day), Compounding.CONTINUOUS)

    def forward(self, day: date) -> float:
        return self.curve.instantaneous_forward(self.time(day))

    def repricing(self) -> list[tuple[str, float, float]]:
        """Each instrument's quote, the rate the finished curve implies, and the difference."""
        return [(item.label, item.quote, item.implied_rate(self.discount) - item.quote) for item in self.instruments]

    def rebuilt(self, quotes: Sequence[float]) -> InstrumentCurve:
        """The same instruments at new quotes - a scenario, or one leg of a finite difference."""
        if len(quotes) != len(self.instruments):
            raise CurveError("One quote per instrument")
        moved = tuple(_requote(item, quote) for item, quote in zip(self.instruments, quotes, strict=True))
        return build_curve(self.valuation_date, moved, interpolation=self.interpolation, name=self.name)

    def jacobian(self, bump: float = 1e-4) -> list[list[float]]:
        """d(zero rate at pillar j) / d(quote i), by central differences on a rebuilt curve."""
        if self._jacobian is None:
            base = [item.quote for item in self.instruments]
            pillars = [self.time(day) for day in self.pillars]
            rows: list[list[float]] = []
            for index in range(len(base)):
                up = self.rebuilt([q + bump * (k == index) for k, q in enumerate(base)])
                down = self.rebuilt([q - bump * (k == index) for k, q in enumerate(base)])
                rows.append(
                    [
                        (
                            up.curve.zero_rate(t, Compounding.CONTINUOUS)
                            - down.curve.zero_rate(t, Compounding.CONTINUOUS)
                        )
                        / (2 * bump)
                        for t in pillars
                    ]
                )
            self._jacobian = rows
        return self._jacobian

    def bucketed_dv01(self, value: Callable[[InstrumentCurve], float], bump: float = 1e-4) -> list[tuple[str, float]]:
        """The change in ``value`` for a one basis point rise in each quote, the others held."""
        base = [item.quote for item in self.instruments]
        result: list[tuple[str, float]] = []
        for index, item in enumerate(self.instruments):
            up = self.rebuilt([q + bump * (k == index) for k, q in enumerate(base)])
            down = self.rebuilt([q - bump * (k == index) for k, q in enumerate(base)])
            result.append((item.label, (value(up) - value(down)) / 2 * (1e-4 / bump)))
        return result


def _requote(item: Instrument, quote: float) -> Instrument:
    if isinstance(item, Deposit):
        return Deposit(item.label, quote, item.start, item.end, item.day_count)
    return OvernightIndexSwap(item.label, quote, item.periods, item.day_count)


def build_curve(
    valuation_date: date,
    instruments: Sequence[Instrument],
    *,
    interpolation: InterpolationMethod | str = InterpolationMethod.LOG_LINEAR,
    name: str = "curve",
    tolerance: float = 1e-14,
    max_passes: int = 60,
) -> InstrumentCurve:
    """Bootstrap a continuously compounded zero curve that reprices every instrument.

    Pillars are the instruments' last relevant dates, and times are ACT/365F from the
    valuation date. Log-linear interpolation on discount factors is local, so one
    sequential pass is exact. Other methods are iterated to a fixed point.
    """
    method = InterpolationMethod(interpolation) if not isinstance(interpolation, InterpolationMethod) else interpolation
    ordered = tuple(sorted(instruments, key=lambda item: item.pillar))
    if not ordered:
        raise CurveError("A curve needs at least one instrument")
    pillars = [item.pillar for item in ordered]
    if len(set(pillars)) != len(pillars):
        raise CurveError("Two instruments share a pillar date; drop one")
    if pillars[0] <= valuation_date:
        raise CurveError("Every instrument must end after the valuation date")
    times = [float(year_fraction(valuation_date, day, CURVE_DAY_COUNT)) for day in pillars]

    def make(nodes: list[float], rates: list[float]) -> YieldCurve:
        return YieldCurve(
            valuation_date,
            nodes,
            rates,
            compounding=Compounding.CONTINUOUS,
            interpolation=method,
            day_count=CURVE_DAY_COUNT,
            name=name,
        )

    def solve_node(index: int, nodes: list[float], rates: list[float]) -> float:
        item = ordered[index]

        def objective(candidate: float) -> float:
            trial = make(nodes, [*rates[:index], candidate, *rates[index + 1 :]])

            def discount(day: date) -> float:
                return trial.discount_factor(float(year_fraction(valuation_date, day, CURVE_DAY_COUNT)))

            return item.implied_rate(discount) - item.quote

        guess = rates[index - 1] if index else item.quote
        return solve(objective, guess, bracket=(-0.5, 1.5), tolerance=tolerance, label=f"{item.label} pillar")

    rates: list[float] = []
    for index, item in enumerate(ordered):
        rates.append(item.quote)
        rates[index] = solve_node(index, times[: index + 1], rates)

    passes = 1
    if method not in _LOCAL:
        for passes in range(2, max_passes + 1):  # noqa: B007 - the count is reported
            previous = list(rates)
            for index in range(len(ordered)):
                rates[index] = solve_node(index, times, rates)
            if max(abs(new - old) for new, old in zip(rates, previous, strict=True)) < 1e-13:
                break
        else:  # pragma: no cover
            raise CurveError(f"{name}: the bootstrap did not converge in {max_passes} passes")

    return InstrumentCurve(valuation_date, ordered, method, make(times, rates), passes, name)


# ---------------------------------------------------------------------------- a SOFR curve
SOFR_TENORS: tuple[str, ...] = (
    "1W", "1M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y",
    "7Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y", "50Y",
)  # fmt: skip


def sofr_curve(
    valuation_date: date,
    quotes: Sequence[float],
    *,
    tenors: Sequence[str] = SOFR_TENORS,
    interpolation: InterpolationMethod | str = InterpolationMethod.LOG_LINEAR,
    calendar: str = "SIFMA",
    payment_lag: int = 0,
) -> InstrumentCurve:
    """A USD SOFR discount curve from a strip of OIS quotes, one per tenor."""
    if len(quotes) != len(tenors):
        raise CurveError("One SOFR quote per tenor")
    swaps = [
        overnight_index_swap(valuation_date, tenor, rate, calendar=calendar, payment_lag=payment_lag)
        for tenor, rate in zip(tenors, quotes, strict=True)
    ]
    return build_curve(valuation_date, swaps, interpolation=interpolation, name="USD SOFR")


def swap_value_on(curve: InstrumentCurve, swap: OvernightIndexSwap, notional: float) -> float:
    """A swap's value on a (possibly bumped) curve - the pricer a DV01 needs."""
    return swap.value(curve.discount, notional)


def par_rate_on(curve: InstrumentCurve, swap: OvernightIndexSwap) -> float:
    return swap.implied_rate(curve.discount)


def zero_rates_at(curve: InstrumentCurve, days: Sequence[date]) -> list[float]:
    return [curve.zero_rate(day) for day in days]


def forward_curve(
    curve: InstrumentCurve, horizon_years: float = 30.0, step_days: int = 7
) -> tuple[list[float], list[float]]:
    """Instantaneous forwards on a weekly grid, for plotting the shape a curve implies."""
    days = range(step_days, int(horizon_years * 365.25), step_days)
    times = [day / 365.0 for day in days]
    return times, [curve.curve.instantaneous_forward(t) for t in times]


def log_discount_factors(curve: InstrumentCurve) -> list[float]:
    return [math.log(curve.discount(day)) for day in curve.pillars]
