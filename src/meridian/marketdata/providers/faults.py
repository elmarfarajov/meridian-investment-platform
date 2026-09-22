"""Deliberately broken data, with a record of exactly how it was broken.

A quality rule that has only ever seen clean data has not been tested. The
injector takes a clean synthetic history and damages it in the specific ways
real feeds fail, keeping a ledger of every fault it introduced. The quality
engine is then scored against that ledger - recall (did it find what was
planted?) and precision (how much of what it flagged was real?) - which turns
"the rules look sensible" into a number.

The fault catalogue is the one operations teams actually see:

``STALE_RUN``
    The vendor stops updating and resends yesterday's close.
``SPIKE``
    A bad tick: one print far from the market that reverts the next day.
``MISSING_RUN``
    Days the exchange traded but the feed delivered nothing.
``UNRECORDED_SPLIT``
    The price falls by exactly the split ratio, but nobody loaded the event.
``UNIT_ERROR``
    A London price delivered in pence instead of pounds - a factor of 100.
``CROSSED_QUOTE``
    A bid above the ask.
``HOLIDAY_PRINT``
    A price on a day the exchange was closed.
``NON_POSITIVE``
    A zero where a price should be, the classic placeholder for "no data".
``FX_TRIANGLE_BREAK``
    A cross rate that no longer agrees with its two legs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

import numpy as np

from ...core.calendars import TradingCalendar, get_calendar
from ...core.exceptions import ValidationError
from ..quotes import FxQuote, MarketDataset, Quote


class FaultKind(str, Enum):
    STALE_RUN = "stale_run"
    SPIKE = "spike"
    MISSING_RUN = "missing_run"
    UNRECORDED_SPLIT = "unrecorded_split"
    UNIT_ERROR = "unit_error"
    CROSSED_QUOTE = "crossed_quote"
    HOLIDAY_PRINT = "holiday_print"
    NON_POSITIVE = "non_positive"
    FX_TRIANGLE_BREAK = "fx_triangle_break"

    @property
    def applies_to_fx(self) -> bool:
        return self is FaultKind.FX_TRIANGLE_BREAK


@dataclass(frozen=True, slots=True)
class FaultSpec:
    """Where to put one fault. ``index`` counts observations of that instrument, not calendar days."""

    kind: FaultKind
    key: str
    index: int
    length: int = 1
    magnitude: float | None = None


@dataclass(frozen=True, slots=True)
class InjectedFault:
    """The ground truth for one fault: what, where, over which dates."""

    kind: FaultKind
    key: str
    start: date
    end: date
    detail: str

    def overlaps(self, start: date, end: date, *, slack_days: int = 0) -> bool:
        return start <= self.end + timedelta(days=slack_days) and end >= self.start - timedelta(days=slack_days)


_DEFAULT_MAGNITUDE: dict[FaultKind, float] = {
    FaultKind.SPIKE: 0.18,
    FaultKind.UNRECORDED_SPLIT: 3.0,
    FaultKind.UNIT_ERROR: 100.0,
    FaultKind.FX_TRIANGLE_BREAK: 0.0035,
}
_DEFAULT_LENGTH: dict[FaultKind, int] = {
    FaultKind.STALE_RUN: 5,
    FaultKind.MISSING_RUN: 4,
    FaultKind.UNIT_ERROR: 3,
}


class FaultInjector:
    """Applies a list of :class:`FaultSpec` to a dataset and reports what it did."""

    def __init__(self, specs: Sequence[FaultSpec], *, seed: int = 11) -> None:
        self.specs = list(specs)
        self.seed = seed

    @classmethod
    def random_plan(
        cls,
        dataset: MarketDataset,
        *,
        kinds: Sequence[FaultKind] = tuple(kind for kind in FaultKind if not kind.applies_to_fx),
        per_instrument: int = 3,
        fx_pairs: Sequence[str] = (),
        fx_breaks: int = 2,
        warmup: int = 30,
        spacing: int = 18,
        seed: int = 11,
    ) -> FaultInjector:
        """A reproducible random plan: faults spaced apart and clear of the warm-up window.

        Spacing matters for honest scoring. Two faults a day apart are one mess
        rather than two tests, and a fault inside the first month would be judged
        by a rolling window that has not filled yet.
        """
        rng = np.random.default_rng(seed)
        specs: list[FaultSpec] = []
        rotation = 0
        for instrument_id in dataset.instruments:
            count = len(dataset.for_instrument(instrument_id))
            slots = list(range(warmup, count - spacing, spacing))
            if not slots:
                continue
            chosen = sorted(rng.choice(len(slots), size=min(per_instrument, len(slots)), replace=False).tolist())
            for slot in chosen:
                kind = kinds[rotation % len(kinds)]
                rotation += 1
                offset = int(rng.integers(0, max(1, spacing // 3)))
                specs.append(FaultSpec(kind, instrument_id, slots[slot] + offset))
        for pair in fx_pairs:
            count = len(dataset.fx.get(pair.upper(), []))
            if count <= warmup + spacing:
                continue
            for index in sorted(rng.choice(range(warmup, count - spacing), size=fx_breaks, replace=False).tolist()):
                specs.append(FaultSpec(FaultKind.FX_TRIANGLE_BREAK, pair.upper(), int(index)))
        return cls(specs, seed=seed)

    def apply(
        self,
        dataset: MarketDataset,
        calendars: Mapping[str, TradingCalendar | str] | None = None,
    ) -> tuple[MarketDataset, list[InjectedFault]]:
        """A damaged copy of ``dataset`` and the ledger of every fault introduced."""
        rng = np.random.default_rng(self.seed)
        quotes = {key: list(items) for key, items in dataset.quotes.items()}
        fx = {key: list(items) for key, items in dataset.fx.items()}
        faults: list[InjectedFault] = []
        calendar_map = dict(calendars or {})

        # Faults that delete or insert rows would shift the indexes of later specs,
        # so each instrument's specs are applied from the last index to the first.
        for spec in sorted(self.specs, key=lambda item: (item.key, -item.index)):
            if spec.kind.applies_to_fx:
                if spec.key not in fx:
                    raise ValidationError(f"no FX series {spec.key} to damage")
                faults.append(self._fx_break(fx[spec.key], spec))
                continue
            if spec.key not in quotes:
                raise ValidationError(f"no quotes for {spec.key} to damage")
            calendar = get_calendar(calendar_map.get(spec.key, "XNYS"))
            faults.append(self._damage(quotes[spec.key], spec, calendar, rng))

        damaged = MarketDataset.from_records(
            (quote for items in quotes.values() for quote in items),
            (rate for items in fx.values() for rate in items),
        )
        return damaged, sorted(faults, key=lambda fault: (fault.key, fault.start))

    # ------------------------------------------------------------------ individual faults
    def _damage(
        self, items: list[Quote], spec: FaultSpec, calendar: TradingCalendar, rng: np.random.Generator
    ) -> InjectedFault:
        items.sort(key=lambda quote: quote.day)
        length = spec.length if spec.length > 1 else _DEFAULT_LENGTH.get(spec.kind, 1)
        index = spec.index
        if not 1 <= index < len(items) - length:
            raise ValidationError(f"{spec.key}: fault index {index} is outside the series")
        magnitude = spec.magnitude if spec.magnitude is not None else _DEFAULT_MAGNITUDE.get(spec.kind, 0.0)
        first, last = items[index].day, items[index + length - 1].day

        if spec.kind is FaultKind.STALE_RUN:
            frozen = items[index - 1]
            for position in range(index, index + length):
                items[position] = items[position].with_close(frozen.close, bid=frozen.bid, ask=frozen.ask)
            return InjectedFault(spec.kind, spec.key, first, last, f"{length} days repeating {frozen.close}")

        if spec.kind is FaultKind.SPIKE:
            sign = 1 if rng.random() < 0.5 else -1
            factor = Decimal(repr(1 + sign * magnitude))
            original = items[index]
            items[index] = original.with_close((original.close * factor).quantize(original.close))
            return InjectedFault(spec.kind, spec.key, first, first, f"close moved {sign * magnitude:+.0%} for one day")

        if spec.kind is FaultKind.MISSING_RUN:
            del items[index : index + length]
            return InjectedFault(spec.kind, spec.key, first, last, f"{length} trading days dropped")

        if spec.kind is FaultKind.UNRECORDED_SPLIT:
            ratio = Decimal(repr(magnitude))
            for position in range(index, len(items)):
                quote = items[position]
                items[position] = quote.with_close(
                    (quote.close / ratio).quantize(quote.close),
                    bid=(quote.bid / ratio).quantize(quote.bid) if quote.bid is not None else None,
                    ask=(quote.ask / ratio).quantize(quote.ask) if quote.ask is not None else None,
                )
            return InjectedFault(spec.kind, spec.key, first, first, f"price divided by {magnitude:g} with no event")

        if spec.kind is FaultKind.UNIT_ERROR:
            factor = Decimal(repr(magnitude))
            for position in range(index, index + length):
                quote = items[position]
                items[position] = quote.with_close(
                    quote.close * factor,
                    bid=quote.bid * factor if quote.bid is not None else None,
                    ask=quote.ask * factor if quote.ask is not None else None,
                )
            return InjectedFault(spec.kind, spec.key, first, last, f"{length} days quoted {magnitude:g}x too high")

        if spec.kind is FaultKind.CROSSED_QUOTE:
            quote = items[index]
            if quote.bid is None or quote.ask is None:
                raise ValidationError(f"{spec.key}: a crossed quote needs a bid and an ask")
            width = quote.ask - quote.bid
            items[index] = quote.with_close(quote.close, bid=quote.ask + width, ask=quote.bid)
            return InjectedFault(spec.kind, spec.key, first, first, "bid and ask swapped and widened")

        if spec.kind is FaultKind.HOLIDAY_PRINT:
            closed = self._closed_day_near(items, index, calendar)
            template = max((quote for quote in items if quote.day < closed), key=lambda quote: quote.day)
            items.append(template.with_close(template.close, day=closed))
            items.sort(key=lambda quote: quote.day)
            return InjectedFault(spec.kind, spec.key, closed, closed, f"print on a closed day ({closed:%a})")

        if spec.kind is FaultKind.NON_POSITIVE:
            items[index] = items[index].with_close(Decimal(0), bid=None, ask=None)
            return InjectedFault(spec.kind, spec.key, first, first, "close delivered as zero")

        raise ValidationError(f"{spec.kind.value} cannot be applied to an instrument")  # pragma: no cover

    @staticmethod
    def _closed_day_near(items: list[Quote], index: int, calendar: TradingCalendar) -> date:
        """The first day after the fault position on which the exchange was shut and no quote exists."""
        existing = {quote.day for quote in items}
        day = items[index].day + timedelta(days=1)
        for _ in range(21):
            if not calendar.is_business_day(day) and day not in existing:
                return day
            day += timedelta(days=1)
        raise ValidationError("no closed day found near the fault position")  # pragma: no cover

    @staticmethod
    def _fx_break(items: list[FxQuote], spec: FaultSpec) -> InjectedFault:
        items.sort(key=lambda rate: rate.day)
        magnitude = spec.magnitude if spec.magnitude is not None else _DEFAULT_MAGNITUDE[FaultKind.FX_TRIANGLE_BREAK]
        original = items[spec.index]
        items[spec.index] = FxQuote(
            base=original.base,
            quote=original.quote,
            day=original.day,
            rate=(original.rate * Decimal(repr(1 + magnitude))).quantize(original.rate),
            source=original.source,
        )
        return InjectedFault(
            FaultKind.FX_TRIANGLE_BREAK,
            spec.key,
            original.day,
            original.day,
            f"cross moved {magnitude * 10_000:.0f} bp away from its legs",
        )
