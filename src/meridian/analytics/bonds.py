"""Fixed income analytics: price, yield, accrued interest, duration and convexity.

This is the arithmetic a fixed income desk runs on, and most of it is older than
the computers it runs on. The parts that repay care:

*Clean versus dirty price.* Bonds are quoted clean - without accrued interest -
but they settle dirty. A valuation that forgets the accrued is wrong by up to a
full coupon, and it is wrong in a way that looks plausible.

*Yield to maturity is an internal rate of return*, not a return. It assumes every
coupon is reinvested at the yield itself, which is a strong assumption and the
reason a yield is a quoting convention rather than a forecast.

*Duration is a first derivative.* It is a linear approximation to a convex
function, so it always overestimates the loss from a rise in yields and
underestimates the gain from a fall. Convexity is the second-order correction,
and for a large move it is not a rounding error.

*Discounting off a curve is not the same as discounting at a yield.* The yield is
one number for the whole bond; the curve prices each cash flow at its own rate.
Both are implemented here, and the difference between them is the bond's spread.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.compounding import Compounding
from ..core.daycount import DayCountConvention, year_fraction
from ..core.decimals import to_decimal
from ..core.enums import Frequency
from ..core.exceptions import ValidationError
from ..core.schedules import Schedule, generate_schedule
from .curves import YieldCurve
from .solvers import solve


@dataclass(frozen=True, slots=True)
class CashFlow:
    """One payment: when it lands, how much, and what it is."""

    payment_date: date
    amount: float
    kind: str = "coupon"
    accrual_start: date | None = None
    accrual_end: date | None = None

    def years_from(self, valuation_date: date, day_count: DayCountConvention) -> float:
        return float(year_fraction(valuation_date, self.payment_date, day_count))

    def as_money(self) -> Decimal:
        """Back to exact decimal at the boundary, because this one becomes a posting."""
        return to_decimal(round(self.amount, 10))


@dataclass(frozen=True)
class FixedRateBond:
    """A plain vanilla fixed coupon bond."""

    face_value: float
    coupon_rate: float
    schedule: Schedule
    day_count: DayCountConvention = DayCountConvention.THIRTY_360_US
    settlement_lag: int = 1
    name: str = "bond"

    @classmethod
    def create(
        cls,
        *,
        issue_date: date,
        maturity: date,
        coupon_rate: float,
        face_value: float = 100.0,
        frequency: Frequency | str = Frequency.SEMI_ANNUAL,
        calendar: str = "SIFMA",
        day_count: DayCountConvention = DayCountConvention.THIRTY_360_US,
        name: str = "bond",
    ) -> FixedRateBond:
        schedule = generate_schedule(issue_date, maturity, frequency, calendar=calendar)
        return cls(
            face_value=face_value,
            coupon_rate=coupon_rate,
            schedule=schedule,
            day_count=day_count,
            name=name,
        )

    # ------------------------------------------------------------------ structure

    @property
    def frequency(self) -> int:
        return self.schedule.frequency.periods_per_year

    @property
    def maturity(self) -> date:
        return self.schedule.end

    @property
    def coupon_amount(self) -> float:
        return self.face_value * self.coupon_rate / self.frequency

    def cash_flows(self, settlement: date | None = None) -> tuple[CashFlow, ...]:
        """Every payment still to come, with the redemption folded into the last one."""
        periods = self.schedule.periods if settlement is None else self.schedule.remaining(settlement)
        flows: list[CashFlow] = []
        for index, period in enumerate(periods):
            fraction = float(
                year_fraction(
                    period.start,
                    period.end,
                    self.day_count,
                    period_start=period.start,
                    period_end=period.end,
                    frequency=self.frequency,
                    calendar=self.schedule.calendar_name,
                    end_is_maturity=period.end == self.maturity,
                )
            )
            amount = self.face_value * self.coupon_rate * fraction
            is_final = index == len(periods) - 1 and period.end == self.maturity
            flows.append(
                CashFlow(
                    payment_date=period.payment_date,
                    amount=amount + (self.face_value if is_final else 0.0),
                    kind="coupon+redemption" if is_final else "coupon",
                    accrual_start=period.start,
                    accrual_end=period.end,
                )
            )
        return tuple(flows)

    # ------------------------------------------------------------------ accrued

    def accrued_interest(self, settlement: date) -> float:
        """Interest earned by the seller but not yet paid, on the bond's own convention."""
        period = self.schedule.period_containing(settlement)
        if period is None or settlement <= period.start:
            return 0.0
        earned = float(
            year_fraction(
                period.start,
                settlement,
                self.day_count,
                period_start=period.start,
                period_end=period.end,
                frequency=self.frequency,
                calendar=self.schedule.calendar_name,
            )
        )
        return self.face_value * self.coupon_rate * earned

    def days_accrued(self, settlement: date) -> tuple[int, int]:
        """Days accrued and days in the period - the fraction printed on a confirmation."""
        period = self.schedule.period_containing(settlement)
        if period is None:
            return 0, 0
        return (settlement - period.start).days, period.days

    # ------------------------------------------------------------------ pricing

    def dirty_price_from_yield(self, ytm: float, settlement: date) -> float:
        """Present value of the remaining flows, discounted at one yield."""
        flows = self.cash_flows(settlement)
        if not flows:
            raise ValidationError(f"{self.name} has no cash flows left after {settlement}")
        frequency = self.frequency
        return float(
            sum(
                flow.amount / (1.0 + ytm / frequency) ** periods
                for flow, periods in zip(flows, self.period_grid(settlement), strict=True)
            )
        )

    def clean_price_from_yield(self, ytm: float, settlement: date) -> float:
        return self.dirty_price_from_yield(ytm, settlement) - self.accrued_interest(settlement)

    def period_grid(self, settlement: date) -> list[float]:
        """Time to each remaining flow, counted in coupon periods.

        This is the street convention (ISMA): the first flow is a fraction *w* of a
        period away, where *w* is the unexpired part of the current coupon period,
        and every later flow is one whole period after the one before. Measuring in
        periods rather than in ACT/365 years is what makes a bond priced at its own
        coupon come out at exactly 100 on a coupon date, rather than at 99.97.
        """
        periods = self.schedule.remaining(settlement)
        if not periods:
            return []
        first = periods[0]
        span = (first.end - first.start).days
        unexpired = 1.0 if settlement <= first.start or span <= 0 else (first.end - settlement).days / span
        return [unexpired + index for index in range(len(periods))]

    def yield_to_maturity(self, clean_price: float, settlement: date, guess: float = 0.05) -> float:
        """The single discount rate that reproduces the quoted price."""
        target = clean_price + self.accrued_interest(settlement)

        def objective(rate: float) -> float:
            return self.dirty_price_from_yield(rate, settlement) - target

        return solve(objective, guess, bracket=(-0.5, 2.0), label=f"{self.name} yield")

    def price_from_curve(self, curve: YieldCurve, settlement: date | None = None) -> float:
        """Every cash flow discounted at its own point on the curve."""
        settlement = settlement or curve.valuation_date
        return sum(flow.amount * curve.discount_factor(flow.payment_date) for flow in self.cash_flows(settlement))

    def spread_to_curve(self, clean_price: float, curve: YieldCurve, settlement: date | None = None) -> float:
        """The parallel shift of the curve that reproduces the price - the z-spread."""
        settlement = settlement or curve.valuation_date
        target = clean_price + self.accrued_interest(settlement)
        flows = self.cash_flows(settlement)

        def objective(spread: float) -> float:
            total = 0.0
            for flow in flows:
                years = flow.years_from(curve.valuation_date, curve.day_count)
                base = curve.zero_rate(years, Compounding.CONTINUOUS)
                total += flow.amount * math.exp(-(base + spread) * years)
            return total - target

        return solve(objective, 0.0, bracket=(-0.2, 0.5), label=f"{self.name} z-spread")

    # ------------------------------------------------------------------ risk

    def macaulay_duration(self, ytm: float, settlement: date) -> float:
        """The weighted average time to the cash flows, in years."""
        flows = self.cash_flows(settlement)
        frequency = self.frequency
        price = self.dirty_price_from_yield(ytm, settlement)
        if price <= 0:
            raise ValidationError("Duration is undefined for a non-positive price")
        weighted = 0.0
        for flow, periods in zip(flows, self.period_grid(settlement), strict=True):
            present = flow.amount / (1.0 + ytm / frequency) ** periods
            weighted += present * periods / frequency
        return weighted / price

    def modified_duration(self, ytm: float, settlement: date) -> float:
        """Percentage price change for a one-unit change in yield."""
        return self.macaulay_duration(ytm, settlement) / (1.0 + ytm / self.frequency)

    def convexity(self, ytm: float, settlement: date) -> float:
        """The second derivative of price with respect to yield, scaled by price."""
        flows = self.cash_flows(settlement)
        frequency = self.frequency
        price = self.dirty_price_from_yield(ytm, settlement)
        total = 0.0
        for flow, periods in zip(flows, self.period_grid(settlement), strict=True):
            present = flow.amount / (1.0 + ytm / frequency) ** periods
            total += present * periods * (periods + 1) / (1.0 + ytm / frequency) ** 2
        return total / (price * frequency**2)

    def dv01(self, ytm: float, settlement: date) -> float:
        """Price change for one basis point, per 100 of face - the desk's unit of risk."""
        up = self.dirty_price_from_yield(ytm + 0.0001, settlement)
        down = self.dirty_price_from_yield(ytm - 0.0001, settlement)
        return (down - up) / 2.0

    def price_change_estimate(self, ytm: float, settlement: date, shift_bp: float) -> tuple[float, float, float]:
        """Actual, duration-only and duration-plus-convexity estimates of a price move.

        The gap between the three is the clearest demonstration of why convexity is
        not optional once a move is large.
        """
        shift = shift_bp / 10_000.0
        base = self.dirty_price_from_yield(ytm, settlement)
        actual = self.dirty_price_from_yield(ytm + shift, settlement) - base
        duration = -self.modified_duration(ytm, settlement) * shift * base
        with_convexity = duration + 0.5 * self.convexity(ytm, settlement) * shift**2 * base
        return actual, duration, with_convexity

    def key_rate_durations(self, curve: YieldCurve, settlement: date | None = None) -> list[tuple[str, float]]:
        """Sensitivity to a bump at each curve pillar, rather than to a parallel shift."""
        settlement = settlement or curve.valuation_date
        base = self.price_from_curve(curve, settlement)
        results: list[tuple[str, float]] = []
        for index, years in enumerate(curve.years):
            bumped = curve.key_rate_shifted(index, 1.0)
            moved = self.price_from_curve(bumped, settlement)
            results.append((f"{years:g}y", (base - moved) / base * 10_000.0 if base else 0.0))
        return results

    def __str__(self) -> str:
        return f"{self.name} {self.coupon_rate * 100:.3f}% {self.maturity.isoformat()}"


def price_yield_curve(
    bond: FixedRateBond,
    settlement: date,
    low: float = -0.01,
    high: float = 0.15,
    count: int = 80,
) -> tuple[list[float], list[float]]:
    """The price-yield relationship, for plotting the convexity of the curve."""
    step = (high - low) / (count - 1)
    yields = [low + step * index for index in range(count)]
    return yields, [bond.clean_price_from_yield(rate, settlement) for rate in yields]


def portfolio_duration(
    positions: Sequence[tuple[FixedRateBond, float, float]],
    settlement: date,
) -> tuple[float, float]:
    """Market-value weighted duration and convexity of a list of (bond, yield, market value)."""
    total = sum(value for _, _, value in positions)
    if total <= 0:
        raise ValidationError("Portfolio duration needs a positive market value")
    duration = sum(bond.modified_duration(ytm, settlement) * value for bond, ytm, value in positions) / total
    convexity = sum(bond.convexity(ytm, settlement) * value for bond, ytm, value in positions) / total
    return duration, convexity
