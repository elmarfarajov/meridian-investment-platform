"""Meridian's rates engine reconciled against QuantLib.

QuantLib is the open-source library that banks, vendors and regulators use as the
reference implementation of fixed income conventions. Agreeing with it is not proof
of being right, but disagreeing with it is always worth an explanation. This module
compares the two on the same inputs and treats every difference like a break in a
reconciliation. It is either fixed, or listed in :data:`KNOWN_DIFFERENCES` with the
reason and the evidence for which side is right.

Comparisons:

- **calendars**: every weekday from 1990 (1999 for TARGET) to 2060, six markets;
- **day counts**: 20,000 generated date pairs per convention, month ends
  oversampled;
- **bonds**: accrued interest, clean price from yield, modified duration and
  convexity on generated bonds, in ACT/ACT ICMA and 30/360 US;
- **gilts**: nine months of settlement dates on a conventional gilt, through two
  ex-dividend periods;
- **curves**: a 20-instrument SOFR OIS strip, bootstrapped both ways, discount
  factors compared at the pillars and every 13 days between them.

QuantLib is a development dependency; nothing in the platform needs it at run time.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..analytics.bonds import FixedRateBond
from ..analytics.curve_building import SOFR_TENORS, InstrumentCurve, sofr_curve
from ..core.calendars import get_calendar
from ..core.daycount import DayCountConvention, year_fraction
from ..marketdata.rates_history import illustrative_sofr_quotes


def _quantlib() -> Any:
    import QuantLib as ql

    return ql


def _ql_date(ql: Any, day: date) -> Any:
    return ql.Date(day.day, day.month, day.year)


# ---------------------------------------------------------------------------- known differences
@dataclass(frozen=True, slots=True)
class KnownDifference:
    """A class of disagreement with QuantLib, why it arises, and which side the evidence favours."""

    area: str
    subject: str
    applies: Callable[[date], bool]
    reason: str
    evidence: str
    label: str = ""


def _japan_equinox_before_2000(day: date) -> bool:
    return day.year < 2000 and day.month in (3, 9)


def _japan_substitute_before_2007(day: date) -> bool:
    return day.year < 2007 and day.month == 5 and day.day == 6


KNOWN_DIFFERENCES: tuple[KnownDifference, ...] = (
    KnownDifference(
        "calendars",
        "XETR",
        lambda day: day.month == 12 and day.day == 31,
        "Meridian closes Xetra on New Year's Eve; QuantLib's Xetra calendar trades.",
        "Deutsche Boerse's published Xetra trading calendar lists 31 December as a non-trading day.",
        "Xetra closes on New Year's Eve (Deutsche Boerse)",
    ),
    KnownDifference(
        "calendars",
        "XTKS",
        _japan_equinox_before_2000,
        "QuantLib's equinox formula for 1980-1999 is a day early in several years.",
        "Meeus's algorithm (Astronomical Algorithms, ch. 27) puts the 1990 vernal equinox at 21:19 UTC on "
        "20 March - 21 March in Tokyo - which is when Japan observed it.",
        "QuantLib's equinox a day early before 2000",
    ),
    KnownDifference(
        "calendars",
        "XTKS",
        _japan_substitute_before_2007,
        "QuantLib applies the 2007 substitute-holiday rule to earlier years.",
        "Before the 2005 amendment took effect in 2007, a Sunday holiday was substituted only by the "
        "Monday after it, so 6 May was a business day in 1992, 1997, 1998 and 2003.",
        "QuantLib's 2007 substitute rule applied earlier",
    ),
    KnownDifference(
        "bonds",
        "30/360 US settling on the 31st",
        lambda day: day.day == 31,
        "30/360 is not additive. QuantLib times the first coupon as (last coupon to next) minus "
        "(last coupon to settlement), which counts the 31st as the 31st when it ends a period.",
        "SIFMA's Standard Securities Calculation Methods count DSC from settlement, so the 31st is the 30th; "
        "summing QuantLib's own day counter from settlement reproduces Meridian's price exactly.",
        "30/360 is not additive",
    ),
)


def explain(area: str, subject: str, day: date) -> KnownDifference | None:
    for difference in KNOWN_DIFFERENCES:
        if difference.area == area and difference.subject == subject and difference.applies(day):
            return difference
    return None


# ---------------------------------------------------------------------------- results
@dataclass(frozen=True)
class Check:
    """One comparison: how many cases, the largest difference, and the breaks that are explained."""

    area: str
    name: str
    cases: int
    max_error: float
    tolerance: float
    explained: int = 0
    unexplained: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.max_error <= self.tolerance and not self.unexplained


@dataclass(frozen=True)
class CalendarComparison:
    calendar: str
    start: date
    end: date
    weekdays: int
    closed_only_by_meridian: tuple[date, ...]
    closed_only_by_quantlib: tuple[date, ...]

    def breaks(self) -> Iterator[tuple[date, str]]:
        for day in self.closed_only_by_meridian:
            yield day, "Meridian closed"
        for day in self.closed_only_by_quantlib:
            yield day, "QuantLib closed"

    def unexplained(self) -> tuple[str, ...]:
        return tuple(
            f"{day} {side}" for day, side in sorted(self.breaks()) if explain("calendars", self.calendar, day) is None
        )


# ---------------------------------------------------------------------------- calendars
def _quantlib_calendars(ql: Any) -> dict[str, tuple[Any, date]]:
    return {
        "XNYS": (ql.UnitedStates(ql.UnitedStates.NYSE), date(1990, 1, 1)),
        "SIFMA": (ql.UnitedStates(ql.UnitedStates.GovernmentBond), date(1990, 1, 1)),
        "XLON": (ql.UnitedKingdom(ql.UnitedKingdom.Exchange), date(1990, 1, 1)),
        "TARGET": (ql.TARGET(), date(1999, 1, 4)),  # TARGET opened on 4 January 1999
        "XETR": (ql.Germany(ql.Germany.Xetra), date(1999, 1, 1)),
        "XTKS": (ql.Japan(), date(1990, 1, 1)),
    }


def compare_calendars(end: date = date(2060, 12, 31)) -> list[CalendarComparison]:
    """Every weekday in the window: closed in one calendar and open in the other."""
    ql = _quantlib()
    results = []
    for name, (theirs, start) in _quantlib_calendars(ql).items():
        ours = get_calendar(name)
        only_ours: list[date] = []
        only_theirs: list[date] = []
        weekdays = 0
        day = start
        while day <= end:
            if day.weekday() < 5:
                weekdays += 1
                open_here = ours.is_business_day(day)
                open_there = theirs.isBusinessDay(_ql_date(ql, day))
                if open_there and not open_here:
                    only_ours.append(day)
                elif open_here and not open_there:
                    only_theirs.append(day)
            day += timedelta(days=1)
        results.append(CalendarComparison(name, start, end, weekdays, tuple(only_ours), tuple(only_theirs)))
    return results


# ---------------------------------------------------------------------------- day counts
_DAY_COUNTS = {
    DayCountConvention.ACT_360: lambda ql: ql.Actual360(),
    DayCountConvention.ACT_365F: lambda ql: ql.Actual365Fixed(),
    DayCountConvention.ACT_365_25: lambda ql: ql.Actual36525(),
    DayCountConvention.ACT_ACT_ISDA: lambda ql: ql.ActualActual(ql.ActualActual.ISDA),
    DayCountConvention.THIRTY_360_US: lambda ql: ql.Thirty360(ql.Thirty360.USA),
    DayCountConvention.THIRTY_360_BOND_BASIS: lambda ql: ql.Thirty360(ql.Thirty360.BondBasis),
    DayCountConvention.THIRTY_E_360: lambda ql: ql.Thirty360(ql.Thirty360.European),
    DayCountConvention.THIRTY_E_360_ISDA: lambda ql: ql.Thirty360(ql.Thirty360.German),
}


def _date_pairs(count: int, seed: int) -> Iterator[tuple[date, date]]:
    rng = random.Random(seed)
    for _ in range(count):
        start = date(1995, 1, 1) + timedelta(days=rng.randrange(0, 20_000))
        end = start + timedelta(days=rng.randrange(1, 4_000))
        if rng.random() < 0.15:  # month ends, and February's in particular, are where conventions differ
            start = date(start.year, start.month % 12 + 1, 1) - timedelta(days=1) if start.month != 12 else start
        if rng.random() < 0.15:
            end = date(end.year, 3, 1) - timedelta(days=1)
        if end > start:
            yield start, end


def compare_day_counts(count: int = 20_000, seed: int = 1) -> list[Check]:
    ql = _quantlib()
    pairs = list(_date_pairs(count, seed))
    checks = []
    for convention, factory in _DAY_COUNTS.items():
        theirs = factory(ql)
        worst = max(
            abs(float(year_fraction(start, end, convention)) - theirs.yearFraction(_ql_date(ql, a), _ql_date(ql, b)))
            for start, end in pairs
            for a, b in [(start, end)]
        )
        checks.append(Check("day counts", convention.value, len(pairs), worst, 1e-12))
    return checks


# ---------------------------------------------------------------------------- bonds
def _bond_cases(trials: int, seed: int) -> Iterator[tuple[date, date, float, int, DayCountConvention, date, float]]:
    rng = random.Random(seed)
    for _ in range(trials):
        issue = date(2010, 1, 1) + timedelta(days=rng.randrange(0, 4_000))
        issue = issue.replace(day=min(issue.day, 27))  # month-end rolls are a schedule question, tested elsewhere
        years = rng.choice([2, 3, 5, 7, 10, 20, 30])
        maturity = date(issue.year + years, issue.month, issue.day)
        coupon = rng.choice([0.5, 1.25, 2.875, 4.0, 6.5]) / 100
        frequency = rng.choice([1, 2])
        convention = rng.choice([DayCountConvention.ACT_ACT_ICMA, DayCountConvention.THIRTY_360_US])
        settlement = issue + timedelta(days=rng.randrange(1, (maturity - issue).days - 10))
        yield issue, maturity, coupon, frequency, convention, settlement, rng.uniform(0.001, 0.08)


def compare_bonds(trials: int = 400, seed: int = 7) -> list[Check]:
    """Yield-based analytics on generated bonds, with QuantLib set to the street convention.

    QuantLib discounts to payment dates and Meridian, like the street, to nominal coupon
    dates. The comparison therefore uses unadjusted payments, so both measure the same
    thing.
    """
    ql = _quantlib()
    tolerances = {"accrued interest": 1e-12, "clean price": 1e-10, "modified duration": 1e-10, "convexity": 1e-8}
    worst: dict[tuple[str, str], float] = {}
    cases: dict[tuple[str, str], int] = {}
    explained: dict[tuple[str, str], int] = {}
    for issue, maturity, coupon, frequency, convention, settlement, ytm in _bond_cases(trials, seed):
        ours = FixedRateBond.create(
            issue_date=issue,
            maturity=maturity,
            coupon_rate=coupon,
            frequency="annual" if frequency == 1 else "semi_annual",
            day_count=convention,
        )
        schedule = ql.Schedule(
            _ql_date(ql, issue),
            _ql_date(ql, maturity),
            ql.Period(12 // frequency, ql.Months),
            ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            ql.Unadjusted,
            ql.Unadjusted,
            ql.DateGeneration.Backward,
            False,
        )
        icma = convention is DayCountConvention.ACT_ACT_ICMA
        accrual = ql.ActualActual(ql.ActualActual.ISMA, schedule) if icma else ql.Thirty360(ql.Thirty360.USA)
        theirs = ql.FixedRateBond(0, 100.0, schedule, [coupon], accrual, ql.Unadjusted)
        when = _ql_date(ql, settlement)
        ql.Settings.instance().evaluationDate = when
        rate = ql.InterestRate(
            ytm,
            ql.ActualActual(ql.ActualActual.ISMA) if icma else accrual,
            ql.Compounded,
            ql.Annual if frequency == 1 else ql.Semiannual,
        )
        rows = {
            "accrued interest": (ours.accrued_interest(settlement), theirs.accruedAmount(when)),
            "clean price": (
                ours.clean_price_from_yield(ytm, settlement),
                ql.BondFunctions.cleanPrice(theirs, rate, when),
            ),
            "modified duration": (
                ours.modified_duration(ytm, settlement),
                ql.BondFunctions.duration(theirs, rate, ql.Duration.Modified, when),
            ),
            "convexity": (ours.convexity(ytm, settlement), ql.BondFunctions.convexity(theirs, rate, when)),
        }
        on_the_31st = not icma and explain("bonds", "30/360 US settling on the 31st", settlement) is not None
        for measure, (mine, reference) in rows.items():
            key = (convention.value, measure)
            if on_the_31st and measure != "accrued interest":
                explained[key] = explained.get(key, 0) + 1
                continue
            cases[key] = cases.get(key, 0) + 1
            worst[key] = max(worst.get(key, 0.0), abs(mine - reference))
    return [
        Check("bonds", f"{convention} {measure}", cases[key], worst[key], tolerances[measure], explained.get(key, 0))
        for key in sorted(cases)
        for convention, measure in [key]
    ]


def compare_gilt(start: date = date(2025, 12, 1), end: date = date(2026, 9, 1)) -> list[Check]:
    """A conventional gilt through two ex-dividend periods: accrued, clean price and duration."""
    ql = _quantlib()
    issue, maturity, coupon, ytm = date(2023, 1, 31), date(2034, 7, 31), 0.04625, 0.045
    ours = FixedRateBond.gilt(issue_date=issue, maturity=maturity, coupon_rate=coupon)
    london = ql.UnitedKingdom(ql.UnitedKingdom.Exchange)
    schedule = ql.Schedule(
        _ql_date(ql, issue), _ql_date(ql, maturity), ql.Period(ql.Semiannual), london,
        ql.Unadjusted, ql.Unadjusted, ql.DateGeneration.Backward, True,
    )  # fmt: skip
    theirs = ql.FixedRateBond(
        0, 100.0, schedule, [coupon], ql.ActualActual(ql.ActualActual.ISMA, schedule), ql.Unadjusted, 100.0,
        _ql_date(ql, issue), london, ql.Period(7, ql.Days), london, ql.Unadjusted, False,
    )  # fmt: skip
    worst = {"accrued interest": 0.0, "clean price": 0.0, "modified duration": 0.0}
    days = ex_days = 0
    day = start
    while day < end:
        when = _ql_date(ql, day)
        if london.isBusinessDay(when):
            ql.Settings.instance().evaluationDate = when
            rate = ql.InterestRate(ytm, ql.ActualActual(ql.ActualActual.ISMA), ql.Compounded, ql.Semiannual)
            pairs = {
                "accrued interest": (ours.accrued_interest(day), theirs.accruedAmount(when)),
                "clean price": (ours.clean_price_from_yield(ytm, day), ql.BondFunctions.cleanPrice(theirs, rate, when)),
                "modified duration": (
                    ours.modified_duration(ytm, day),
                    ql.BondFunctions.duration(theirs, rate, ql.Duration.Modified, when),
                ),
            }
            for key, (mine, reference) in pairs.items():
                worst[key] = max(worst[key], abs(mine - reference))
            days += 1
            ex_days += ours.is_ex_dividend(day)
        day += timedelta(days=1)
    return [
        Check("gilts", f"gilt {key} ({ex_days} of {days} days ex)", days, value, 1e-10) for key, value in worst.items()
    ]


# ---------------------------------------------------------------------------- curves
def quantlib_sofr_curve(valuation_date: date, quotes: list[float], payment_lag: int = 0) -> Any:
    ql = _quantlib()
    ql.Settings.instance().evaluationDate = _ql_date(ql, valuation_date)
    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    index = ql.OvernightIndex("SOFR", 0, ql.USDCurrency(), calendar, ql.Actual360())
    helpers = [
        ql.OISRateHelper(
            2,
            ql.Period(tenor),
            ql.QuoteHandle(ql.SimpleQuote(quote)),
            index,
            ql.YieldTermStructureHandle(),
            False,
            payment_lag,
            ql.Following,
            ql.Annual,
            calendar,
        )
        for tenor, quote in zip(SOFR_TENORS, quotes, strict=True)
    ]
    return ql.PiecewiseLogLinearDiscount(_ql_date(ql, valuation_date), helpers, ql.Actual365Fixed()), helpers


def compare_sofr_curve(valuation_date: date = date(2026, 9, 30)) -> list[Check]:
    ql = _quantlib()
    quotes = list(illustrative_sofr_quotes(valuation_date))
    checks = []
    for lag in (0, 2):
        ours: InstrumentCurve = sofr_curve(valuation_date, quotes, payment_lag=lag)
        theirs, helpers = quantlib_sofr_curve(valuation_date, quotes, lag)
        dates = list(ours.pillars)
        day = valuation_date + timedelta(days=1)
        while day < ours.pillars[-1]:
            dates.append(day)
            day += timedelta(days=13)
        worst = max(abs(ours.discount(item) - theirs.discount(_ql_date(ql, item))) for item in dates)
        mismatched = tuple(
            f"{mine} vs {helper.pillarDate()}"
            for mine, helper in zip(ours.pillars, helpers, strict=True)
            if _ql_date(ql, mine) != helper.pillarDate()
        )
        name = f"SOFR OIS discount factors, payment lag {lag}"
        checks.append(Check("curves", name, len(dates), worst, 1e-11, 0, mismatched))
    return checks


def monotone_convex_variant(valuation_date: date = date(2026, 9, 30)) -> dict[str, float]:
    """How far QuantLib's blended convex-monotone curve sits from pure Hagan-West, in forward basis points."""
    ql = _quantlib()
    quotes = list(illustrative_sofr_quotes(valuation_date))
    ours = sofr_curve(valuation_date, quotes, interpolation="monotone_convex")
    _, helpers = quantlib_sofr_curve(valuation_date, quotes)
    theirs = ql.PiecewiseConvexMonotoneForward(_ql_date(ql, valuation_date), helpers, ql.Actual365Fixed())
    theirs.enableExtrapolation()
    times = [week / 52 for week in range(1, 52 * 49)]
    gaps = [
        abs(ours.curve.instantaneous_forward(t) - theirs.forwardRate(t, t, ql.Continuous, ql.NoFrequency).rate())
        for t in times
    ]
    return {
        "max_forward_gap_bp": max(gaps) * 1e4,
        "mean_forward_gap_bp": sum(gaps) / len(gaps) * 1e4,
        "passes": ours.iterations,
    }


def reconciliation() -> list[Check]:
    """Every comparison, as checks a test or a chart can read."""
    checks: list[Check] = []
    for comparison in compare_calendars():
        breaks = list(comparison.breaks())
        checks.append(
            Check(
                "calendars",
                comparison.calendar,
                comparison.weekdays,
                0.0,
                0.0,
                explained=len(breaks) - len(comparison.unexplained()),
                unexplained=comparison.unexplained(),
            )
        )
    checks += compare_day_counts()
    checks += compare_bonds()
    checks += compare_gilt()
    checks += compare_sofr_curve()
    return checks
