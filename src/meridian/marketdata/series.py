"""Dated series of prices and rates.

A price history is the input to almost everything above the ledger - valuation,
returns, risk, attribution - so the container is strict about the three things
that quietly corrupt it:

* **Order and uniqueness.** Dates are sorted and unique. A duplicated date is a
  load error, not something to average away.
* **Exactness.** Values are ``Decimal``, because a published mark ends up in a
  valuation. Analytics ask for ``floats()`` explicitly, which is where the
  boundary between the ledger and the maths sits (ADR 0008).
* **Staleness.** Carrying a price forward is sometimes right (a market holiday)
  and sometimes a lie (a feed that stopped). Every lookup that carries a value
  forward says how far it is prepared to carry it.
"""

from __future__ import annotations

import bisect
import itertools
import math
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from ..core.decimals import Numeric, to_decimal
from ..core.exceptions import ValidationError


class FillMethod(str, Enum):
    """How a missing date is filled when a series is reindexed."""

    NONE = "none"  # leave the gap
    PREVIOUS = "previous"  # carry the last value forward
    LINEAR = "linear"  # interpolate in calendar time between neighbours


@dataclass(frozen=True, slots=True)
class Point:
    """One dated value."""

    day: date
    value: Decimal


@dataclass(frozen=True, slots=True)
class AsOfValue:
    """A value looked up on or before a date, with how old it is.

    ``age_days`` is in calendar days. Callers that care about business days pass
    a calendar to :meth:`TimeSeries.as_of`, which counts them instead.
    """

    requested: date
    day: date
    value: Decimal
    age_days: int

    @property
    def is_exact(self) -> bool:
        return self.day == self.requested


class TimeSeries:
    """An immutable, sorted, gap-aware series of ``Decimal`` values."""

    __slots__ = ("_days", "_values", "name")

    def __init__(self, points: Iterable[tuple[date, Numeric]] = (), *, name: str = "") -> None:
        pairs = sorted(((day, to_decimal(value, field=f"{name or 'series'}[{day}]")) for day, value in points))
        days = [day for day, _ in pairs]
        for previous, current in itertools.pairwise(days):
            if previous == current:
                raise ValidationError(f"{name or 'series'}: duplicate observation on {current.isoformat()}")
        self._days: tuple[date, ...] = tuple(days)
        self._values: tuple[Decimal, ...] = tuple(value for _, value in pairs)
        self.name = name

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_mapping(cls, values: dict[date, Numeric], *, name: str = "") -> TimeSeries:
        return cls(values.items(), name=name)

    @classmethod
    def from_floats(
        cls, days: Sequence[date], values: Sequence[float], *, name: str = "", places: int = 6
    ) -> TimeSeries:
        """Build from analytics output, rounding to a fixed number of places on the way back into ``Decimal``."""
        if len(days) != len(values):
            raise ValidationError(f"{name or 'series'}: {len(days)} dates but {len(values)} values")
        quantum = Decimal(1).scaleb(-places)
        return cls(
            ((day, Decimal(repr(float(value))).quantize(quantum)) for day, value in zip(days, values, strict=True)),
            name=name,
        )

    def with_name(self, name: str) -> TimeSeries:
        return TimeSeries(zip(self._days, self._values, strict=True), name=name)

    # ------------------------------------------------------------------ container protocol
    def __len__(self) -> int:
        return len(self._days)

    def __bool__(self) -> bool:
        return bool(self._days)

    def __iter__(self) -> Iterator[Point]:
        for day, value in zip(self._days, self._values, strict=True):
            yield Point(day, value)

    def __contains__(self, day: object) -> bool:
        if not isinstance(day, date):
            return False
        index = bisect.bisect_left(self._days, day)
        return index < len(self._days) and self._days[index] == day

    def __getitem__(self, day: date) -> Decimal:
        index = bisect.bisect_left(self._days, day)
        if index < len(self._days) and self._days[index] == day:
            return self._values[index]
        raise KeyError(day)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TimeSeries):
            return NotImplemented
        return self._days == other._days and self._values == other._values

    def __hash__(self) -> int:
        return hash((self._days, self._values))

    def __repr__(self) -> str:
        span = f"{self._days[0]}..{self._days[-1]}" if self._days else "empty"
        return f"TimeSeries({self.name!r}, {len(self)} points, {span})"

    # ------------------------------------------------------------------ accessors
    @property
    def days(self) -> tuple[date, ...]:
        return self._days

    @property
    def values(self) -> tuple[Decimal, ...]:
        return self._values

    def floats(self) -> list[float]:
        """The values as floats, for analytics. This is the ``Decimal``/``float`` boundary."""
        return [float(value) for value in self._values]

    def get(self, day: date, default: Decimal | None = None) -> Decimal | None:
        try:
            return self[day]
        except KeyError:
            return default

    @property
    def first(self) -> Point:
        if not self._days:
            raise ValidationError(f"{self.name or 'series'} is empty")
        return Point(self._days[0], self._values[0])

    @property
    def last(self) -> Point:
        if not self._days:
            raise ValidationError(f"{self.name or 'series'} is empty")
        return Point(self._days[-1], self._values[-1])

    def as_of(self, day: date, *, max_age_days: int | None = None) -> AsOfValue | None:
        """The latest value on or before ``day``, or ``None`` if there is none fresh enough.

        This is the lookup valuation uses. ``max_age_days`` is the explicit answer to
        "how stale a price am I prepared to value a position at?" - without it a
        feed that died in March would keep valuing the book at March prices.
        """
        index = bisect.bisect_right(self._days, day) - 1
        if index < 0:
            return None
        found = self._days[index]
        age = (day - found).days
        if max_age_days is not None and age > max_age_days:
            return None
        return AsOfValue(requested=day, day=found, value=self._values[index], age_days=age)

    # ------------------------------------------------------------------ transformations
    def between(self, start: date | None = None, end: date | None = None) -> TimeSeries:
        """Inclusive slice."""
        low = 0 if start is None else bisect.bisect_left(self._days, start)
        high = len(self._days) if end is None else bisect.bisect_right(self._days, end)
        return TimeSeries(zip(self._days[low:high], self._values[low:high], strict=True), name=self.name)

    def map(self, function: Callable[[date, Decimal], Decimal]) -> TimeSeries:
        return TimeSeries(
            ((day, function(day, value)) for day, value in zip(self._days, self._values, strict=True)), name=self.name
        )

    def scale(self, factor: Numeric) -> TimeSeries:
        multiplier = to_decimal(factor, field="factor")
        return self.map(lambda _day, value: value * multiplier)

    def drop(self, days: Iterable[date]) -> TimeSeries:
        excluded = set(days)
        return TimeSeries(
            ((day, value) for day, value in zip(self._days, self._values, strict=True) if day not in excluded),
            name=self.name,
        )

    def replace(self, updates: dict[date, Numeric]) -> TimeSeries:
        """A copy with some values replaced or added."""
        merged: dict[date, Numeric] = dict(zip(self._days, self._values, strict=True))
        merged.update(updates)
        return TimeSeries(merged.items(), name=self.name)

    def reindex(
        self, days: Iterable[date], *, fill: FillMethod = FillMethod.NONE, limit: int | None = None
    ) -> TimeSeries:
        """Put the series onto another set of dates.

        ``limit`` caps how many consecutive target dates a value may be carried
        or interpolated across; beyond it the gap is left open, so a long outage
        stays visible instead of being papered over.
        """
        targets = sorted(set(days))
        result: list[tuple[date, Decimal]] = []
        carried = 0
        for day in targets:
            exact = self.get(day)
            if exact is not None:
                result.append((day, exact))
                carried = 0
                continue
            if fill is FillMethod.NONE:
                continue
            carried += 1
            if limit is not None and carried > limit:
                continue
            filled = self._fill(day, fill)
            if filled is not None:
                result.append((day, filled))
        return TimeSeries(result, name=self.name)

    def _fill(self, day: date, fill: FillMethod) -> Decimal | None:
        index = bisect.bisect_left(self._days, day)
        if index == 0:
            return None
        before_day, before_value = self._days[index - 1], self._values[index - 1]
        if fill is FillMethod.PREVIOUS:
            return before_value
        if index >= len(self._days):
            return None
        after_day, after_value = self._days[index], self._values[index]
        weight = Decimal((day - before_day).days) / Decimal((after_day - before_day).days)
        return before_value + (after_value - before_value) * weight

    def align(self, other: TimeSeries) -> tuple[TimeSeries, TimeSeries]:
        """Both series restricted to the dates they share."""
        common = set(self._days) & set(other._days)
        return (
            TimeSeries(((day, self[day]) for day in common), name=self.name),
            TimeSeries(((day, other[day]) for day in common), name=other.name),
        )

    # ------------------------------------------------------------------ returns
    def returns(self, *, log: bool = False) -> list[tuple[date, float]]:
        """Period returns between consecutive observations, dated at the later one.

        Returns are computed between *observations*, not between calendar days, so
        a gap in the data produces one multi-day return rather than a silent zero.
        Non-positive values have no meaningful return and are skipped.
        """
        results: list[tuple[date, float]] = []
        values = self.floats()
        for index in range(1, len(values)):
            previous, current = values[index - 1], values[index]
            if previous <= 0 or current <= 0:
                continue
            ratio = current / previous
            results.append((self._days[index], math.log(ratio) if log else ratio - 1.0))
        return results

    def cumulative_index(self, base: float = 100.0) -> list[tuple[date, float]]:
        """The series rebased so the first observation equals ``base``."""
        if not self._values:
            return []
        start = float(self._values[0])
        if start <= 0:
            raise ValidationError(f"{self.name or 'series'}: cannot rebase a series that starts at {start}")
        return [(day, float(value) / start * base) for day, value in zip(self._days, self._values, strict=True)]

    def max_drawdown(self) -> tuple[float, date | None, date | None]:
        """Largest peak-to-trough fall, with the peak and trough dates."""
        worst = 0.0
        peak_value = -math.inf
        peak_day: date | None = None
        result: tuple[float, date | None, date | None] = (0.0, None, None)
        for day, value in zip(self._days, self.floats(), strict=True):
            if value > peak_value:
                peak_value, peak_day = value, day
            if peak_value > 0:
                drawdown = value / peak_value - 1.0
                if drawdown < worst:
                    worst = drawdown
                    result = (drawdown, peak_day, day)
        return result


def merge_series(series: Sequence[TimeSeries], *, prefer: str = "first") -> TimeSeries:
    """Combine series that cover different periods; on overlap, ``prefer`` decides which wins."""
    if prefer not in {"first", "last"}:
        raise ValidationError("prefer must be 'first' or 'last'")
    merged: dict[date, Decimal] = {}
    ordered = series if prefer == "last" else list(reversed(series))
    for item in ordered:
        for point in item:
            merged[point.day] = point.value
    name = series[0].name if series else ""
    return TimeSeries(merged.items(), name=name)
