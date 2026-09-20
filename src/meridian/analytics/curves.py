"""Yield curves: discounting, forwards, and bootstrapping from par rates.

A curve is quoted as a handful of par yields - the coupon a bond would need to
trade at 100 for each maturity - and everything downstream needs discount factors
at arbitrary dates. Turning one into the other is bootstrapping: solve the
shortest instrument first, then use it to solve the next, and so on. Each step is
a small root-find, which is why this module sits on top of ``solvers``.

Two things are easy to get wrong and are handled explicitly:

*The zero curve is not the par curve.* When the curve slopes upwards the zero
rate is above the par rate at the same maturity, and the forward rate is above
both. Quoting one where another is meant misprices everything.

*Interpolation is a modelling choice.* The default here is log-linear on discount
factors, which is equivalent to assuming a constant forward rate between pillars.
It keeps discount factors positive and monotone by construction. See ADR 0007.

Rates are floats, deliberately: a curve is analytics, not a ledger entry. Cash
amounts are converted back to ``Decimal`` at the boundary. See ADR 0008.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from ..core.compounding import Compounding, discount_factor, forward_rate, zero_rate
from ..core.daycount import DayCountConvention, year_fraction
from ..core.exceptions import CurveError, ValidationError
from ..core.interpolation import InterpolationMethod, make_interpolator
from .solvers import solve

DEFAULT_DAY_COUNT = DayCountConvention.ACT_365F


@dataclass(frozen=True, slots=True)
class CurvePoint:
    """One quoted point on a curve."""

    years: float
    rate: float
    label: str = ""

    def __str__(self) -> str:
        name = self.label or f"{self.years:g}y"
        return f"{name}: {self.rate * 100:.4f}%"


def tenor_label(years: float) -> str:
    """A human tenor from a year fraction: 0.25 -> 3M, 10 -> 10Y."""
    if years < 1:
        months = round(years * 12)
        return f"{months}M" if months else f"{round(years * 365)}D"
    if abs(years - round(years)) < 1e-9:
        return f"{round(years)}Y"
    return f"{years:.2f}Y"


class YieldCurve:
    """A zero-coupon curve: pillar times in years, and the zero rates at them."""

    def __init__(
        self,
        valuation_date: date,
        years: Sequence[float],
        rates: Sequence[float],
        *,
        compounding: Compounding | str = Compounding.CONTINUOUS,
        interpolation: InterpolationMethod | str = InterpolationMethod.LOG_LINEAR,
        day_count: DayCountConvention = DEFAULT_DAY_COUNT,
        name: str = "zero curve",
    ) -> None:
        if len(years) != len(rates):
            raise CurveError("A curve needs one rate per pillar")
        if not years:
            raise CurveError("A curve needs at least one pillar")
        if any(value <= 0 for value in years):
            raise CurveError("Curve pillars must be positive year fractions")
        if any(later <= earlier for earlier, later in pairwise(years)):
            raise CurveError("Curve pillars must be strictly increasing")

        self.valuation_date = valuation_date
        self.years = tuple(float(value) for value in years)
        self.rates = tuple(float(value) for value in rates)
        self.compounding = Compounding(compounding) if not isinstance(compounding, Compounding) else compounding
        self.interpolation = (
            InterpolationMethod(interpolation) if not isinstance(interpolation, InterpolationMethod) else interpolation
        )
        self.day_count = day_count
        self.name = name

        self._pillar_factors = tuple(
            discount_factor(rate, years_, self.compounding) for years_, rate in zip(self.years, self.rates, strict=True)
        )
        if self.interpolation in {InterpolationMethod.LOG_LINEAR, InterpolationMethod.FLAT_FORWARD}:
            # Anchor at t=0, DF=1, so the short end extrapolates towards par rather than flat
            self._interpolator = make_interpolator(
                (0.0, *self.years), (1.0, *self._pillar_factors), InterpolationMethod.LOG_LINEAR
            )
            self._interpolates_factors = True
        else:
            self._interpolator = make_interpolator(self.years, self.rates, self.interpolation)
            self._interpolates_factors = False

    # ------------------------------------------------------------------ lookups

    def time_to(self, when: date | float) -> float:
        """Year fraction from the valuation date, accepting either a date or a number of years."""
        if isinstance(when, date):
            return float(year_fraction(self.valuation_date, when, self.day_count))
        return float(when)

    def discount_factor(self, when: date | float) -> float:
        years = self.time_to(when)
        if years <= 0:
            return 1.0
        if self._interpolates_factors:
            return self._interpolator(years)
        return discount_factor(self._interpolator(years), years, self.compounding)

    def zero_rate(self, when: date | float, compounding: Compounding | None = None) -> float:
        years = self.time_to(when)
        if years <= 0:
            return self.rates[0]
        return zero_rate(self.discount_factor(years), years, compounding or self.compounding)

    def forward_rate(
        self,
        start: date | float,
        end: date | float,
        compounding: Compounding | None = None,
    ) -> float:
        """The rate the curve implies between two future dates."""
        near, far = self.time_to(start), self.time_to(end)
        if far <= near:
            raise CurveError("A forward rate needs the far date after the near one")
        return forward_rate(
            self.discount_factor(near),
            self.discount_factor(far),
            near,
            far,
            compounding or self.compounding,
        )

    def instantaneous_forward(self, when: date | float, bump: float = 1e-4) -> float:
        """The limit of the forward rate as the window shrinks - the shape the curve really has."""
        years = max(self.time_to(when), 0.0)
        return self.forward_rate(years, years + bump, Compounding.CONTINUOUS)

    def par_rate(self, tenor: float, frequency: int = 2) -> float:
        """The coupon that would make a bond of this maturity price at par on this curve.

        Inside the first coupon period there is no coupon to pay, so the quote is a
        money-market rate on a simple basis - which is how the short end is quoted,
        and what keeps this consistent with the deposits used to bootstrap it.
        """
        if tenor <= 1.0 / frequency + 1e-9:
            factor = self.discount_factor(tenor)
            return (1.0 / factor - 1.0) / tenor
        times = self._coupon_times(tenor, frequency)
        if not times:
            raise CurveError(f"A {tenor}y par rate needs at least one coupon date")
        factors = [self.discount_factor(time) for time in times]
        annuity = sum(factors) / frequency
        if annuity <= 0:
            raise CurveError("Degenerate annuity; the curve cannot produce a par rate here")
        return (1.0 - factors[-1]) / annuity

    def _coupon_times(self, tenor: float, frequency: int) -> list[float]:
        """Coupon dates counted back from maturity, so any stub lands at the front."""
        if frequency <= 0:
            raise ValidationError("Coupon frequency must be positive")
        times: list[float] = []
        step = 1.0 / frequency
        time = tenor
        while time > 1e-9:
            times.append(time)
            time -= step
        return sorted(times)

    # ------------------------------------------------------------------ scenarios

    def shifted(self, basis_points: float) -> YieldCurve:
        """A parallel shift, which is how DV01 and duration are computed."""
        shift = basis_points / 10_000.0
        return YieldCurve(
            self.valuation_date,
            self.years,
            [rate + shift for rate in self.rates],
            compounding=self.compounding,
            interpolation=self.interpolation,
            day_count=self.day_count,
            name=f"{self.name} {basis_points:+.0f}bp",
        )

    def key_rate_shifted(self, pillar: int, basis_points: float) -> YieldCurve:
        """A triangular bump at one pillar, tapering to zero at its neighbours.

        This is what key-rate duration measures: the sensitivity of a portfolio to
        the curve twisting at one maturity rather than shifting everywhere at once.
        """
        if not 0 <= pillar < len(self.years):
            raise CurveError(f"Pillar {pillar} is outside the curve")
        shift = basis_points / 10_000.0
        bumped = list(self.rates)
        bumped[pillar] += shift
        return YieldCurve(
            self.valuation_date,
            self.years,
            bumped,
            compounding=self.compounding,
            interpolation=self.interpolation,
            day_count=self.day_count,
            name=f"{self.name} {tenor_label(self.years[pillar])} {basis_points:+.0f}bp",
        )

    # ------------------------------------------------------------------ output

    def points(self) -> tuple[CurvePoint, ...]:
        return tuple(
            CurvePoint(years, rate, tenor_label(years)) for years, rate in zip(self.years, self.rates, strict=True)
        )

    def sample(self, count: int = 120, horizon: float | None = None) -> tuple[list[float], list[float]]:
        """Evenly spaced points for plotting: times and zero rates."""
        end = horizon or self.years[-1]
        step = end / count
        times = [step * (index + 1) for index in range(count)]
        return times, [self.zero_rate(time) for time in times]

    def par_curve(self, frequency: int = 2, count: int = 40) -> tuple[list[float], list[float]]:
        """The par yields this zero curve implies, which is what the market quotes back."""
        end = self.years[-1]
        times = [end * (index + 1) / count for index in range(count)]
        return times, [self.par_rate(time, frequency) for time in times]

    def forward_curve(self, tenor: float = 0.25, count: int = 60) -> tuple[list[float], list[float]]:
        """Rolling forward rates of a fixed window, which show the shape the curve is pricing in."""
        end = max(self.years[-1] - tenor, tenor)
        times = [end * (index + 1) / count for index in range(count)]
        return times, [self.forward_rate(time, time + tenor) for time in times]

    def __repr__(self) -> str:
        return f"<YieldCurve {self.name} {len(self.years)} pillars {self.valuation_date.isoformat()}>"


def bootstrap_par_curve(
    valuation_date: date,
    tenors: Sequence[float],
    par_rates: Sequence[float],
    *,
    frequency: int = 2,
    compounding: Compounding = Compounding.CONTINUOUS,
    interpolation: InterpolationMethod | str = InterpolationMethod.LOG_LINEAR,
    name: str = "bootstrapped",
) -> YieldCurve:
    """Build a zero curve from quoted par yields, one instrument at a time.

    Tenors shorter than one coupon period are treated as money-market deposits and
    discounted simply, which is what the market does. Longer tenors are solved so
    that a par bond of that maturity prices exactly to 100 on the curve built so
    far - the definition of a par yield.
    """
    if len(tenors) != len(par_rates):
        raise CurveError("Bootstrapping needs one par rate per tenor")
    if not tenors:
        raise CurveError("Bootstrapping needs at least one instrument")

    times: list[float] = []
    rates: list[float] = []
    period = 1.0 / frequency

    for tenor, par in zip(tenors, par_rates, strict=True):
        tenor = float(tenor)
        par = float(par)
        if times and tenor <= times[-1]:
            raise CurveError("Bootstrapping instruments must be in increasing maturity order")

        if tenor <= period + 1e-9:  # a single payment: price it as a deposit
            factor = 1.0 / (1.0 + par * tenor)
            rates.append(zero_rate(factor, tenor, compounding))
            times.append(tenor)
            continue

        def objective(candidate: float, tenor: float = tenor, par: float = par) -> float:
            trial = YieldCurve(
                valuation_date,
                [*times, tenor],
                [*rates, candidate],
                compounding=compounding,
                interpolation=interpolation,
            )
            return trial.par_rate(tenor, frequency) - par

        guess = rates[-1] if rates else par
        rates.append(solve(objective, guess, bracket=(-0.5, 1.5), label=f"{tenor_label(tenor)} bootstrap"))
        times.append(tenor)

    return YieldCurve(
        valuation_date,
        times,
        rates,
        compounding=compounding,
        interpolation=interpolation,
        name=name,
    )


def flat_curve(
    valuation_date: date,
    rate: float,
    *,
    horizon: float = 30.0,
    compounding: Compounding | str = Compounding.CONTINUOUS,
) -> YieldCurve:
    """A flat curve, which is the right null hypothesis for testing a pricer."""
    return YieldCurve(
        valuation_date,
        [0.25, 1.0, 2.0, 5.0, 10.0, horizon],
        [rate] * 6,
        compounding=compounding,
        name=f"flat {rate * 100:.2f}%",
    )
