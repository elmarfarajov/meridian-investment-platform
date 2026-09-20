"""Compounding conventions and the time value of money.

A quoted interest rate means nothing without the compounding it is quoted on. 5%
annually, 5% semi-annually and 5% continuously are three different amounts of
money, and the difference over ten years on a large notional is not small. Every
rate that crosses a boundary in this platform therefore carries its convention,
and conversions go through :func:`convert_rate` rather than being assumed.

This module is deliberately `float` rather than `Decimal`. It is analytics, not
accounting: a discount factor is the output of an exponential, it is never a
posted amount, and it is used inside iterative solvers where exact decimal
arithmetic buys nothing and costs a great deal. Anything that becomes a cash
amount is converted back to `Decimal` at the boundary. See ADR 0008.
"""

from __future__ import annotations

import math
from enum import Enum

from .exceptions import ValidationError


class Compounding(str, Enum):
    """How often interest is compounded within a year."""

    SIMPLE = "simple"
    ANNUAL = "annual"
    SEMI_ANNUAL = "semi_annual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"
    CONTINUOUS = "continuous"

    @property
    def periods_per_year(self) -> int | None:
        """``None`` for simple and continuous compounding, which have no period count."""
        return {
            Compounding.SIMPLE: None,
            Compounding.ANNUAL: 1,
            Compounding.SEMI_ANNUAL: 2,
            Compounding.QUARTERLY: 4,
            Compounding.MONTHLY: 12,
            Compounding.CONTINUOUS: None,
        }[self]

    @classmethod
    def from_frequency(cls, periods_per_year: int) -> Compounding:
        mapping = {
            1: cls.ANNUAL,
            2: cls.SEMI_ANNUAL,
            4: cls.QUARTERLY,
            12: cls.MONTHLY,
        }
        if periods_per_year not in mapping:
            raise ValidationError(f"No compounding convention for {periods_per_year} periods a year")
        return mapping[periods_per_year]


def discount_factor(rate: float, years: float, compounding: Compounding = Compounding.CONTINUOUS) -> float:
    """The present value of one unit paid in ``years`` years."""
    if years == 0:
        return 1.0
    if compounding is Compounding.CONTINUOUS:
        return math.exp(-rate * years)
    if compounding is Compounding.SIMPLE:
        denominator = 1.0 + rate * years
        if denominator <= 0:
            raise ValidationError("Simple discounting is undefined for this rate and horizon")
        return 1.0 / denominator
    periods = compounding.periods_per_year
    assert periods is not None  # narrowed by the branches above
    base = 1.0 + rate / periods
    if base <= 0:
        raise ValidationError("Compounded discounting is undefined for this rate")
    return float(base ** (-periods * years))


def zero_rate(factor: float, years: float, compounding: Compounding = Compounding.CONTINUOUS) -> float:
    """Invert a discount factor back into a rate on the given convention."""
    if factor <= 0:
        raise ValidationError("A discount factor must be positive")
    if years <= 0:
        raise ValidationError("A zero rate needs a positive horizon")
    if compounding is Compounding.CONTINUOUS:
        return -math.log(factor) / years
    if compounding is Compounding.SIMPLE:
        return (1.0 / factor - 1.0) / years
    periods = compounding.periods_per_year
    assert periods is not None
    return float(periods * (factor ** (-1.0 / (periods * years)) - 1.0))


def convert_rate(rate: float, years: float, source: Compounding, target: Compounding) -> float:
    """Restate a rate from one compounding convention to another, leaving the money unchanged."""
    if source is target:
        return rate
    return zero_rate(discount_factor(rate, years, source), years, target)


def forward_rate(
    near_factor: float,
    far_factor: float,
    near_years: float,
    far_years: float,
    compounding: Compounding = Compounding.CONTINUOUS,
) -> float:
    """The rate implied between two horizons by two discount factors."""
    if far_years <= near_years:
        raise ValidationError("The far horizon must be beyond the near one")
    span = far_years - near_years
    return zero_rate(far_factor / near_factor, span, compounding)


def future_value(present: float, rate: float, years: float, compounding: Compounding = Compounding.ANNUAL) -> float:
    return present / discount_factor(rate, years, compounding)


def present_value(future: float, rate: float, years: float, compounding: Compounding = Compounding.ANNUAL) -> float:
    return future * discount_factor(rate, years, compounding)


def annuity_factor(rate: float, periods: int, periods_per_year: int = 1) -> float:
    """Present value of one unit paid every period for ``periods`` periods."""
    if periods <= 0:
        raise ValidationError("An annuity needs at least one period")
    per_period = rate / periods_per_year
    if abs(per_period) < 1e-12:
        return float(periods)
    return (1.0 - (1.0 + per_period) ** (-periods)) / per_period


def effective_annual_rate(nominal: float, compounding: Compounding) -> float:
    """The rate that, compounded annually, produces the same growth over one year."""
    return convert_rate(nominal, 1.0, compounding, Compounding.ANNUAL)


def compounding_comparison(rate: float, years: float) -> dict[Compounding, tuple[float, float]]:
    """Discount factor and effective annual rate for one nominal rate under each convention.

    This is the table that answers "does the convention matter?" - at 5% over ten
    years, the spread between simple and continuous discounting is over nine cents
    in the dollar.
    """
    result: dict[Compounding, tuple[float, float]] = {}
    for convention in Compounding:
        result[convention] = (
            discount_factor(rate, years, convention),
            effective_annual_rate(rate, convention),
        )
    return result
