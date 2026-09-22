"""Point-in-time market data: what was the value, and when did we know it.

Every market data record has two dates. The *value date* is the day the price
describes. The *knowledge time* is when the platform learned it. Most systems
keep only the first, and then overwrite a record when a vendor corrects it -
which destroys the answer to the question an auditor, a regulator or a backtest
eventually asks: *what did the book look like on the morning of the 14th, using
only what was known on the morning of the 14th?*

This module keeps both. A correction is a new record with a later knowledge
time, never an update, so any past state of knowledge can be reconstructed
exactly. The same idea removes look-ahead bias from a backtest: a strategy
evaluated on restated data is being given information it could not have had.

The store here is in memory and is the reference implementation; the database
table ``price_observations`` has the same shape and the repository answers the
same queries in SQL.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from ..core.decimals import Numeric, to_decimal
from ..core.exceptions import ValidationError
from .series import TimeSeries


def as_utc(moment: datetime) -> datetime:
    """Knowledge times are compared in UTC; a naive datetime is taken to be UTC already."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def end_of_day(day: date, hour: int = 23, minute: int = 59) -> datetime:
    """A knowledge time at the end of a calendar day, in UTC."""
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True, order=True)
class Observation:
    """One recorded value. Immutable: a correction is a new observation, not an edit.

    Ordering is by knowledge time first, so sorting a list of observations for the
    same value date puts them in the order the platform learned them.
    """

    recorded_at: datetime
    value_date: date
    value: Decimal
    key: str = field(compare=False)
    source: str = field(default="", compare=False)
    note: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recorded_at", as_utc(self.recorded_at))
        object.__setattr__(self, "value", to_decimal(self.value, field=f"{self.key}[{self.value_date}]"))
        if not self.key:
            raise ValidationError("an observation needs a key")
        if self.recorded_at.date() < self.value_date:
            raise ValidationError(
                f"{self.key}: a value for {self.value_date} cannot be known at {self.recorded_at.isoformat()}"
            )


@dataclass(frozen=True, slots=True)
class Revision:
    """A value that changed after it was first published."""

    key: str
    value_date: date
    first_value: Decimal
    first_known: datetime
    final_value: Decimal
    final_known: datetime
    versions: int

    @property
    def change(self) -> Decimal:
        return self.final_value - self.first_value

    @property
    def change_bps(self) -> float:
        if self.first_value == 0:
            return float("inf")
        return float(self.change / self.first_value) * 10_000

    @property
    def delay_days(self) -> int:
        return (self.final_known.date() - self.first_known.date()).days


class BitemporalStore:
    """An append-only store answering "as known at" queries.

    Keys are free-form strings - an instrument and a price type, say
    ``"US-AAPL:close"`` - so the same store holds prices, FX fixings and
    index levels.
    """

    def __init__(self, observations: Iterable[Observation] = ()) -> None:
        self._records: dict[str, dict[date, list[Observation]]] = defaultdict(lambda: defaultdict(list))
        self._count = 0
        for observation in observations:
            self.add(observation)

    # ------------------------------------------------------------------ writing
    def add(self, observation: Observation) -> Observation:
        versions = self._records[observation.key][observation.value_date]
        for existing in versions:
            if existing.recorded_at == observation.recorded_at and existing.value != observation.value:
                raise ValidationError(
                    f"{observation.key} {observation.value_date}: two different values recorded at the same "
                    f"instant ({existing.value} and {observation.value}); knowledge times must be distinct"
                )
            if existing.recorded_at == observation.recorded_at:
                return existing  # an exact resend is idempotent
        versions.append(observation)
        versions.sort()
        self._count += 1
        return observation

    def record(
        self,
        key: str,
        value_date: date,
        value: Numeric,
        recorded_at: datetime,
        *,
        source: str = "",
        note: str = "",
    ) -> Observation:
        return self.add(
            Observation(
                recorded_at=recorded_at,
                value_date=value_date,
                value=to_decimal(value, field=key),
                key=key,
                source=source,
                note=note,
            )
        )

    def record_series(
        self, key: str, series: TimeSeries, *, lag_days: int = 0, hour: int = 22, source: str = ""
    ) -> int:
        """Record a whole series as if each value were learned ``lag_days`` after its value date."""
        for point in series:
            known = end_of_day(point.day + timedelta(days=lag_days), hour, 0)
            self.record(key, point.day, point.value, known, source=source)
        return len(series)

    # ------------------------------------------------------------------ reading
    def __len__(self) -> int:
        return self._count

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))

    def versions(self, key: str, value_date: date) -> tuple[Observation, ...]:
        """Every value ever recorded for one date, in the order it was learned."""
        return tuple(self._records.get(key, {}).get(value_date, ()))

    def value(self, key: str, value_date: date, *, known_at: datetime | None = None) -> Decimal | None:
        """The value for one date as it was known at ``known_at`` (latest knowledge if omitted)."""
        observation = self._latest(self._records.get(key, {}).get(value_date, []), known_at)
        return observation.value if observation else None

    def as_known_at(
        self,
        key: str,
        known_at: datetime | None = None,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> TimeSeries:
        """The whole series as it stood at one moment of knowledge.

        Dates the platform had not yet heard of at ``known_at`` are simply absent,
        which is exactly how the series looked at the time.
        """
        points: list[tuple[date, Decimal]] = []
        for value_date, versions in self._records.get(key, {}).items():
            if (start and value_date < start) or (end and value_date > end):
                continue
            observation = self._latest(versions, known_at)
            if observation is not None:
                points.append((value_date, observation.value))
        return TimeSeries(points, name=key)

    def first_published(self, key: str) -> TimeSeries:
        """Each date at the value it was first published with - the view a live system actually had."""
        points = [(day, versions[0].value) for day, versions in self._records.get(key, {}).items() if versions]
        return TimeSeries(points, name=f"{key} (first print)")

    def revisions(self, key: str | None = None) -> list[Revision]:
        """Every date whose value changed after first publication."""
        keys = [key] if key is not None else list(self._records)
        found: list[Revision] = []
        for item in keys:
            for value_date, versions in sorted(self._records.get(item, {}).items()):
                if len(versions) < 2 or versions[0].value == versions[-1].value:
                    continue
                found.append(
                    Revision(
                        key=item,
                        value_date=value_date,
                        first_value=versions[0].value,
                        first_known=versions[0].recorded_at,
                        final_value=versions[-1].value,
                        final_known=versions[-1].recorded_at,
                        versions=len(versions),
                    )
                )
        return found

    def knowledge_times(self, key: str) -> tuple[datetime, ...]:
        """Every distinct moment at which the series for ``key`` changed."""
        moments = {
            observation.recorded_at for versions in self._records.get(key, {}).values() for observation in versions
        }
        return tuple(sorted(moments))

    @staticmethod
    def _latest(versions: Sequence[Observation], known_at: datetime | None) -> Observation | None:
        if not versions:
            return None
        if known_at is None:
            return versions[-1]
        cutoff = as_utc(known_at)
        candidate: Observation | None = None
        for observation in versions:  # sorted by knowledge time
            if observation.recorded_at <= cutoff:
                candidate = observation
            else:
                break
        return candidate


def lookahead_error(store: BitemporalStore, key: str, known_at: datetime) -> list[tuple[date, float]]:
    """Per date, how far today's restated value is from what was known at ``known_at``, in basis points.

    A non-zero entry is information a backtest run on today's data would have
    used but a live strategy at ``known_at`` could not have had.
    """
    then = store.as_known_at(key, known_at)
    now = store.as_known_at(key)
    errors: list[tuple[date, float]] = []
    for point in then:
        current = now.get(point.day)
        if current is None or point.value == 0:
            continue
        errors.append((point.day, float((current - point.value) / point.value) * 10_000))
    return errors
