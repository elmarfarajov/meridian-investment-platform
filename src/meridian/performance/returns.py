"""Rates of return: time-weighted, money-weighted, and the approximations in between.

Two questions are asked of a portfolio's return, and they have different answers:

* **How well was the money managed?** The time-weighted return removes the
  effect of the client's deposits and withdrawals, so a manager is not flattered
  by money that arrived just before a rally or blamed for money withdrawn at the
  bottom. It is the return GIPS requires and the one benchmarks are compared with.
  With a valuation every day it is exact: each day's return is the investment
  result over the capital at risk, and the days are chained geometrically.
* **How did the client's money do?** The money-weighted return - the internal
  rate of return of the client's own cash flows - does include the timing of
  those flows, because the client chose it. For a client who added half a million
  just before a fall, it is lower than the time-weighted return, and both are
  right.

The Modified Dietz method approximates the time-weighted return from only the
opening and closing values and the flows, weighting each flow by the part of the
period it was invested. It is what firms used before daily valuation was cheap,
and its error against the true daily figure is shown rather than assumed.

Returns are floats: this is analytics, not the ledger (ADR 0008). The daily
inputs come from the exact value bridge of Day 3, so every day's return
reconciles to the book.

Flows are taken at the **start of the day**: money deposited on a day is at risk
from that day's close, which is how the demonstration account traded it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ..accounting.bridge import ValueBridge
from ..analytics.solvers import solve
from ..core.exceptions import ValidationError

DAYS_PER_YEAR = 365.25
TRADING_DAYS = 252


@dataclass(frozen=True, slots=True)
class DailyReturn:
    """One day's return with the numbers it was computed from (base currency)."""

    day: date
    opening: float
    flows: float
    closing: float
    result: float  # investment result: everything that was not a flow

    @property
    def capital(self) -> float:
        """The money at risk during the day: opening value plus the day's flows."""
        return self.opening + self.flows

    @property
    def rate(self) -> float:
        return self.result / self.capital if self.capital > 0 else 0.0


def daily_returns(bridges: Sequence[ValueBridge]) -> list[DailyReturn]:
    """One return per valuation day from the Day 3 daily value bridges."""
    return [
        DailyReturn(
            step.end,
            float(step.opening),
            float(step.flows),
            float(step.closing),
            float(step.investment_result),
        )
        for step in bridges
    ]


def link(returns: Iterable[float]) -> float:
    """Geometric linking: the return of a sequence of sub-period returns."""
    total = 1.0
    for value in returns:
        total *= 1.0 + value
    return total - 1.0


def annualise(total: float, start: date, end: date) -> float:
    """Annualised equivalent of a return earned between two dates; periods under a year are not annualised."""
    years = (end - start).days / DAYS_PER_YEAR
    if years < 1.0:
        return total
    return float((1.0 + total) ** (1.0 / years) - 1.0)


@dataclass(frozen=True)
class ReturnSeries:
    """A daily return series with the period arithmetic reporting needs."""

    days: tuple[date, ...]
    rates: tuple[float, ...]
    name: str = "portfolio"

    def __post_init__(self) -> None:
        if len(self.days) != len(self.rates):
            raise ValidationError("a return series needs one rate per day")
        if any(later <= earlier for earlier, later in zip(self.days, self.days[1:], strict=False)):
            raise ValidationError("return series days must be strictly increasing")

    @classmethod
    def from_daily(cls, items: Sequence[DailyReturn], name: str = "portfolio") -> ReturnSeries:
        return cls(tuple(item.day for item in items), tuple(item.rate for item in items), name)

    def __len__(self) -> int:
        return len(self.days)

    @property
    def start(self) -> date:
        """The valuation date the first return is measured from (the day before the first return day)."""
        return self.days[0] - timedelta(days=1)

    def between(self, start: date, end: date) -> ReturnSeries:
        """Returns for days in ``(start, end]``: from the close of ``start`` to the close of ``end``."""
        pairs = [(day, rate) for day, rate in zip(self.days, self.rates, strict=True) if start < day <= end]
        return ReturnSeries(tuple(day for day, _ in pairs), tuple(rate for _, rate in pairs), self.name)

    def total(self, start: date | None = None, end: date | None = None) -> float:
        series = self if start is None and end is None else self.between(start or date.min, end or date.max)
        return link(series.rates)

    def index(self, base: float = 100.0) -> list[tuple[date, float]]:
        """Growth of ``base`` invested at the start."""
        level = base
        points = [(self.start, base)]
        for day, rate in zip(self.days, self.rates, strict=True):
            level *= 1.0 + rate
            points.append((day, level))
        return points

    def drawdowns(self) -> list[tuple[date, float]]:
        """Distance below the running peak of the growth index, as a (negative) fraction."""
        peak = -math.inf
        found: list[tuple[date, float]] = []
        for day, level in self.index(1.0):
            peak = max(peak, level)
            found.append((day, level / peak - 1.0))
        return found

    def monthly(self) -> list[tuple[date, float]]:
        """One linked return per calendar month, keyed by the month's last return day."""
        months: dict[tuple[int, int], list[tuple[date, float]]] = {}
        for day, rate in zip(self.days, self.rates, strict=True):
            months.setdefault((day.year, day.month), []).append((day, rate))
        return [(items[-1][0], link(rate for _, rate in items)) for _, items in sorted(months.items())]

    def yearly(self) -> list[tuple[int, float]]:
        years: dict[int, list[float]] = {}
        for day, rate in zip(self.days, self.rates, strict=True):
            years.setdefault(day.year, []).append(rate)
        return [(year, link(rates)) for year, rates in sorted(years.items())]


@dataclass(frozen=True)
class PeriodReturn:
    label: str
    start: date
    end: date
    total: float

    @property
    def annualised(self) -> float:
        return annualise(self.total, self.start, self.end)

    @property
    def is_annualised(self) -> bool:
        return (self.end - self.start).days >= DAYS_PER_YEAR


def standard_periods(series: ReturnSeries, as_of: date | None = None) -> list[PeriodReturn]:
    """Month, quarter and year to date, one year, and since inception, the way a factsheet shows them."""
    end = as_of or series.days[-1]
    inception = series.start
    quarter_month = 3 * ((end.month - 1) // 3) + 1
    candidates = [
        ("MTD", date(end.year, end.month, 1) - timedelta(days=1)),
        ("QTD", date(end.year, quarter_month, 1) - timedelta(days=1)),
        ("YTD", date(end.year, 1, 1) - timedelta(days=1)),
        ("1 year", date(end.year - 1, end.month, min(end.day, 28))),
        ("Since inception", inception),
    ]
    return [
        PeriodReturn(label, max(start, inception), end, series.total(max(start, inception), end))
        for label, start in candidates
        if start >= inception or label == "Since inception"
    ]


# ---------------------------------------------------------------------------- approximations
def modified_dietz(
    opening: float, closing: float, flows: Sequence[tuple[date, float]], start: date, end: date
) -> float:
    """(closing - opening - flows) / (opening + time-weighted flows), flows weighted by the time they were invested.

    A flow on day ``t`` of a period of ``T`` days is weighted ``(T - t) / T``
    with ``t`` counted from the start - the start-of-day convention used by the
    daily returns, so that for a one-day period the two methods agree exactly.
    """
    length = (end - start).days
    if length <= 0:
        raise ValidationError("a Modified Dietz period needs end after start")
    net = sum(amount for _, amount in flows)
    weighted = sum(amount * (length - ((day - start).days - 1)) / length for day, amount in flows)
    denominator = opening + weighted
    if denominator <= 0:
        raise ValidationError("the Modified Dietz denominator is not positive: no capital was at risk")
    return (closing - opening - net) / denominator


def xirr(cash_flows: Sequence[tuple[date, float]], *, guess: float = 0.05) -> float:
    """The annual rate at which the flows' present value is zero (investor's view: money in negative).

    Solved by safeguarded Newton inside a bracket (``analytics.solvers``), so a
    stream with no root raises rather than returning a plausible wrong number.
    """
    if len(cash_flows) < 2:
        raise ValidationError("an internal rate of return needs at least two cash flows")
    if not (any(amount < 0 for _, amount in cash_flows) and any(amount > 0 for _, amount in cash_flows)):
        raise ValidationError("an internal rate of return needs flows of both signs")
    origin = min(day for day, _ in cash_flows)
    times = [((day - origin).days / DAYS_PER_YEAR, amount) for day, amount in cash_flows]

    def value(rate: float) -> float:
        return float(sum(amount / (1.0 + rate) ** years for years, amount in times))

    def derivative(rate: float) -> float:
        return float(sum(-years * amount / (1.0 + rate) ** (years + 1.0) for years, amount in times))

    return solve(value, guess, derivative=derivative, bracket=(-0.99, 10.0), label="money-weighted return")


@dataclass(frozen=True)
class MoneyWeightedReturn:
    start: date
    end: date
    annual: float

    @property
    def period(self) -> float:
        """The IRR expressed over the period rather than per year."""
        years = (self.end - self.start).days / DAYS_PER_YEAR
        return float((1.0 + self.annual) ** years - 1.0)


def money_weighted_return(
    opening: float, closing: float, flows: Sequence[tuple[date, float]], start: date, end: date
) -> MoneyWeightedReturn:
    """The client's own IRR: the opening value and each deposit paid in, the closing value taken out.

    ``flows`` are from the portfolio's point of view (a deposit is positive), as
    the value bridge reports them; they are negated into the investor's view.
    """
    stream: list[tuple[date, float]] = []
    if opening:
        stream.append((start, -opening))
    stream.extend((day, -amount) for day, amount in flows)
    stream.append((end, closing))
    return MoneyWeightedReturn(start, end, xirr(stream))


def flows_of(bridges: Sequence[ValueBridge]) -> list[tuple[date, float]]:
    """The external flows in a run of daily bridges, dated."""
    return [(step.end, float(step.flows)) for step in bridges if step.flows]
