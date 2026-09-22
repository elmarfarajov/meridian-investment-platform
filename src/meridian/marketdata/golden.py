"""The golden copy: one published price per instrument per day, from several sources.

A pricing desk does not pick a vendor and trust it. For every instrument and
day it collects every source's value, discards the ones the quality checks
withheld, compares the rest, and publishes one price with a record of how it
was chosen. Disagreement beyond a tolerance becomes a *price challenge* - a
question put to the vendors - rather than being silently resolved.

Two policies are supported, and the difference between them is a judgement
the firm has to make explicitly:

``PRIORITY``
    Take the highest-ranked source whose value is within tolerance of the
    consensus. Reproducible and explainable ("we use the exchange close"), and
    the consensus stops a single bad source from winning just because it ranks
    first.
``MEDIAN``
    Take the median of the in-tolerance values. More robust to any one source,
    but the published number may be a value no vendor sent.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from ..core.exceptions import ValidationError
from .quotes import MarketDataset, Quote
from .series import TimeSeries


class GoldenMethod(str, Enum):
    PRIORITY = "priority"
    MEDIAN = "median"


@dataclass(frozen=True, slots=True)
class PricingPolicy:
    """How to turn several sources' values into one."""

    ranking: tuple[str, ...]
    tolerance_bps: float = 25.0
    method: GoldenMethod = GoldenMethod.PRIORITY
    min_sources: int = 1

    def __post_init__(self) -> None:
        if not self.ranking:
            raise ValidationError("a pricing policy needs a source ranking")
        if self.tolerance_bps <= 0:
            raise ValidationError("the tolerance must be positive")
        if self.min_sources < 1:
            raise ValidationError("at least one source is required")

    def rank(self, source: str) -> int:
        return self.ranking.index(source) if source in self.ranking else len(self.ranking)


@dataclass(frozen=True, slots=True)
class GoldenPrice:
    """One published price and the evidence behind it."""

    instrument_id: str
    day: date
    value: Decimal
    currency: str
    method: GoldenMethod
    source: str
    candidates: tuple[tuple[str, Decimal], ...]
    excluded: tuple[tuple[str, str], ...]  # (source, reason)
    dispersion_bps: float
    challenged: bool
    reason: str = ""

    @property
    def source_count(self) -> int:
        return len(self.candidates)


@dataclass
class GoldenCopy:
    prices: list[GoldenPrice] = field(default_factory=list)
    unpriced: list[tuple[str, date, str]] = field(default_factory=list)  # (instrument, day, reason)

    def series(self, instrument_id: str) -> TimeSeries:
        return TimeSeries(
            ((price.day, price.value) for price in self.prices if price.instrument_id == instrument_id),
            name=instrument_id,
        )

    def challenges(self) -> list[GoldenPrice]:
        return [price for price in self.prices if price.challenged]

    def source_share(self) -> dict[str, int]:
        """How many published prices each source supplied - or ``median`` for blended values."""
        return dict(sorted(Counter(price.source for price in self.prices).items()))

    def dispersion(self, instrument_id: str | None = None) -> list[float]:
        return [
            price.dispersion_bps
            for price in self.prices
            if (instrument_id is None or price.instrument_id == instrument_id) and price.source_count > 1
        ]

    def __len__(self) -> int:
        return len(self.prices)


def _bps(value: Decimal, reference: Decimal) -> float:
    return float((value - reference) / reference) * 10_000 if reference else float("inf")


def choose_price(
    instrument_id: str,
    day: date,
    quotes: Sequence[Quote],
    policy: PricingPolicy,
    *,
    blocked_sources: Iterable[str] = (),
) -> GoldenPrice | tuple[str, date, str]:
    """Choose one value for one instrument and day, or say why none could be published."""
    blocked = set(blocked_sources)
    excluded: list[tuple[str, str]] = [
        (quote.source, "withheld by a quality check") for quote in quotes if quote.source in blocked
    ]
    usable = [quote for quote in quotes if quote.source not in blocked and quote.close > 0]
    excluded += [(quote.source, "non-positive") for quote in quotes if quote.source not in blocked and quote.close <= 0]
    if len(usable) < policy.min_sources:
        return (instrument_id, day, f"{len(usable)} usable source(s), policy needs {policy.min_sources}")

    values = sorted(quote.close for quote in usable)
    consensus = Decimal(str(statistics.median(values)))
    dispersion = _bps(values[-1], consensus) - _bps(values[0], consensus) if len(values) > 1 else 0.0
    inside = [quote for quote in usable if abs(_bps(quote.close, consensus)) <= policy.tolerance_bps]
    outside = [quote for quote in usable if quote not in inside]
    excluded += [(quote.source, f"{_bps(quote.close, consensus):+.0f} bp from consensus") for quote in outside]

    if not inside:
        # every source disagrees with every other: publish nothing rather than guess
        return (instrument_id, day, f"no two sources within {policy.tolerance_bps:g} bp")

    if policy.method is GoldenMethod.MEDIAN and len(inside) > 1:
        value = Decimal(str(statistics.median(quote.close for quote in inside)))
        source = "median"
    else:
        best = min(inside, key=lambda quote: (policy.rank(quote.source), quote.source))
        value, source = best.close, best.source

    challenged = bool(outside) or (len(usable) == 1 and len(quotes) > 1)
    reason = ""
    if outside:
        reason = "; ".join(f"{quote.source} {_bps(quote.close, consensus):+.0f} bp" for quote in outside)
    elif challenged:
        reason = "single usable source"
    return GoldenPrice(
        instrument_id=instrument_id,
        day=day,
        value=value,
        currency=usable[0].currency,
        method=policy.method,
        source=source,
        candidates=tuple(sorted((quote.source, quote.close) for quote in usable)),
        excluded=tuple(excluded),
        dispersion_bps=abs(dispersion),
        challenged=challenged,
        reason=reason,
    )


def build_golden_copy(
    dataset: MarketDataset,
    policy: PricingPolicy,
    *,
    blocked: Iterable[tuple[str, str, date]] = (),
) -> GoldenCopy:
    """One price per instrument and day from every source in ``dataset``.

    ``blocked`` holds (instrument, source, day) triples the quality run withheld.
    """
    withheld: dict[tuple[str, date], set[str]] = defaultdict(set)
    for key, source, day in blocked:
        withheld[(key, day)].add(source)

    copy = GoldenCopy()
    for instrument_id in dataset.instruments:
        by_day: dict[date, list[Quote]] = defaultdict(list)
        for quote in dataset.for_instrument(instrument_id):
            by_day[quote.day].append(quote)
        for day in sorted(by_day):
            outcome = choose_price(
                instrument_id, day, by_day[day], policy, blocked_sources=withheld.get((instrument_id, day), ())
            )
            if isinstance(outcome, GoldenPrice):
                copy.prices.append(outcome)
            else:
                copy.unpriced.append(outcome)
    return copy


def compare_to_reference(
    copy: GoldenCopy, reference: MarketDataset, sources: MarketDataset | None = None
) -> dict[str, list[float]]:
    """Error of the golden copy, and of each raw source, against a known truth, in basis points.

    Only possible with synthetic data, where the truth is known - which is the
    point: it measures what the consensus buys over trusting any one vendor.
    Source errors are measured on everything each source sent, including the
    values the quality checks withheld.
    """
    errors: dict[str, list[float]] = defaultdict(list)
    truth = {(quote.instrument_id, quote.day): quote.close for items in reference.quotes.values() for quote in items}
    for price in copy.prices:
        actual = truth.get((price.instrument_id, price.day))
        if actual is not None:
            errors["golden"].append(_bps(price.value, actual))
    for items in sources.quotes.values() if sources is not None else ():
        for quote in items:
            actual = truth.get((quote.instrument_id, quote.day))
            if actual is not None and quote.close > 0:
                errors[quote.source].append(_bps(quote.close, actual))
    return dict(errors)
