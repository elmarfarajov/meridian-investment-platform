"""Brinson-Fachler attribution, currency separated, linked over time by Cariño.

The active return - portfolio less benchmark - is explained segment by segment
(a sector, or a region) as three decisions:

* **Allocation** - holding more or less of a segment than the benchmark:
  ``(wp - wb) x (Rb_s - Rb)``. Overweighting a segment is rewarded only if the
  segment beat the benchmark as a whole; this is the Brinson-Fachler form,
  which unlike the original Brinson-Hood-Beebower does not reward overweighting
  a segment that merely went up with the market.
* **Selection** - picking better securities within the segment:
  ``wb x (Rp_s - Rb_s)``.
* **Interaction** - the cross term, ``(wp - wb) x (Rp_s - Rb_s)``.

Local returns are attributed this way; the **currency** effect is kept apart,
because a manager who picks German stocks well should not be credited or
blamed for the euro. Per currency it is the portfolio's currency contribution
less the benchmark's. **Costs** - commissions, fees, unreclaimable withholding -
are the portfolio's own and have no benchmark counterpart.

Each day the effects add up *exactly* to that day's active return. Over many days
they do not, because returns compound and effects add: the arithmetic sum of
daily effects misses the compounding. Cariño's method rescales each day's
effects by

    k_t = [ln(1 + R_t) - ln(1 + B_t)] / (R_t - B_t)   against   K = [ln(1 + R) - ln(1 + B)] / (R - B)

so that the linked effects sum to the compounded active return ``R - B`` with
nothing left over. The size of what the unlinked sum misses is reported too.

**Funds** held by the portfolio are looked through to the benchmark's own
composition (a US index fund to the North American constituents, a world fund
to all of them), so an index fund does not appear as a segment the benchmark
does not have.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from ..core.exceptions import ValidationError
from ..domain.instruments import Bond, Equity, Fund, Instrument
from .benchmark import CASH, FIXED_INCOME, BenchmarkDay, region_of
from .contributions import Exposure, PortfolioDay

EFFECTS = ("allocation", "selection", "interaction")
LookThrough = Callable[[str, BenchmarkDay, str], dict[str, float]]


# ---------------------------------------------------------------------------- segmentation
def classify(instrument: Instrument, dimension: str) -> str | None:
    """The segment of a directly held security, or None for a fund to be looked through."""
    if isinstance(instrument, Fund):
        return None
    if isinstance(instrument, Bond):
        return FIXED_INCOME
    if dimension == "sector":
        return instrument.sector if isinstance(instrument, Equity) and instrument.sector else "Other"
    return region_of(instrument.country)


def benchmark_look_through(scope: Mapping[str, str | None]) -> LookThrough:
    """Look a fund through to the benchmark's equity constituents in its scope (a region, or everything)."""

    def shares(fund_id: str, day: BenchmarkDay, dimension: str) -> dict[str, float]:
        region = scope.get(fund_id)
        pieces = [
            piece
            for piece in day.pieces
            if piece.sector not in {FIXED_INCOME, CASH} and (region is None or piece.region == region)
        ]
        total = sum(piece.weight for piece in pieces)
        if total <= 0:
            return {"Other": 1.0}
        found: dict[str, float] = defaultdict(float)
        for piece in pieces:
            found[getattr(piece, dimension)] += piece.weight / total
        return dict(found)

    return shares


@dataclass(frozen=True, slots=True)
class Segmented:
    value: float = 0.0
    local: float = 0.0
    fx: float = 0.0


def segment_portfolio(
    day: PortfolioDay,
    benchmark: BenchmarkDay,
    instruments: Mapping[str, Instrument],
    dimension: str,
    look_through: LookThrough,
) -> tuple[dict[str, Segmented], dict[str, Segmented]]:
    """The day's exposures by segment and by currency (value, local result, currency result)."""
    segments: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    currencies: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])

    def add(segment: str, exposure: Exposure, share: float) -> None:
        bucket = segments[segment]
        bucket[0] += exposure.value * share
        bucket[1] += exposure.local * share
        bucket[2] += exposure.fx * share

    for exposure in day.exposures:
        money = currencies[exposure.currency]
        money[0] += exposure.value
        money[2] += exposure.fx
        if exposure.is_cash:
            add(CASH, exposure, 1.0)
            continue
        instrument = instruments[exposure.key]
        segment = classify(instrument, dimension)
        if segment is not None:
            add(segment, exposure, 1.0)
            continue
        for looked, share in look_through(exposure.key, benchmark, dimension).items():
            add(looked, exposure, share)
    return (
        {key: Segmented(*values) for key, values in segments.items()},
        {key: Segmented(*values) for key, values in currencies.items()},
    )


# ---------------------------------------------------------------------------- one day
@dataclass(frozen=True)
class SegmentDay:
    segment: str
    wp: float
    wb: float
    rp: float | None  # portfolio local return in the segment, None where it held nothing
    rb: float | None
    allocation: float
    selection: float
    interaction: float

    @property
    def total(self) -> float:
        return self.allocation + self.selection + self.interaction


@dataclass(frozen=True)
class AttributionDay:
    day: date
    portfolio: float
    benchmark: float
    segments: dict[str, SegmentDay]
    currency: dict[str, float]  # portfolio less benchmark currency contribution, per currency
    costs: float
    currency_weights: dict[str, tuple[float, float]] = field(default_factory=dict)

    @property
    def active(self) -> float:
        return self.portfolio - self.benchmark

    @property
    def explained(self) -> float:
        return sum(item.total for item in self.segments.values()) + sum(self.currency.values()) + self.costs

    @property
    def residual(self) -> float:
        return self.active - self.explained

    def effect(self, name: str) -> float:
        if name == "currency":
            return sum(self.currency.values())
        if name == "costs":
            return self.costs
        return float(sum(getattr(item, name) for item in self.segments.values()))


def attribute_day(
    day: PortfolioDay,
    benchmark: BenchmarkDay,
    instruments: Mapping[str, Instrument],
    *,
    dimension: str = "sector",
    look_through: LookThrough,
) -> AttributionDay:
    if day.day != benchmark.day:
        raise ValidationError(f"portfolio day {day.day} against benchmark day {benchmark.day}")
    segmented, by_currency = segment_portfolio(day, benchmark, instruments, dimension, look_through)
    capital = day.capital if day.capital > 0 else 1.0
    bench: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    bench_currency: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for piece in benchmark.pieces:
        bucket = bench[getattr(piece, dimension)]
        bucket[0] += piece.weight
        bucket[1] += piece.weight * piece.local
        bucket[2] += piece.weight * piece.fx
        bench_currency[piece.currency][0] += piece.weight
        bench_currency[piece.currency][1] += piece.weight * piece.fx
    bench_local = sum(values[1] for values in bench.values())
    segments: dict[str, SegmentDay] = {}
    for name in sorted(set(segmented) | set(bench)):
        mine = segmented.get(name, Segmented())
        wp, contribution = mine.value / capital, mine.local / capital
        wb, bench_contribution = bench[name][0], bench[name][1]
        rb = bench_contribution / wb if wb > 0 else None
        reference = rb if rb is not None else bench_local
        allocation = (wp - wb) * (reference - bench_local)
        beyond = contribution - wp * reference  # selection + interaction, exactly
        rp = contribution / wp if wp > 0 else None
        if rp is not None:
            selection = wb * (rp - reference)
            interaction = beyond - selection
        else:
            selection, interaction = beyond, 0.0
        segments[name] = SegmentDay(name, wp, wb, rp, rb, allocation, selection, interaction)
    currency = {
        code: by_currency.get(code, Segmented()).fx / capital - bench_currency.get(code, [0.0, 0.0])[1]
        for code in sorted(set(by_currency) | set(bench_currency))
    }
    weights = {
        code: (by_currency.get(code, Segmented()).value / capital, bench_currency.get(code, [0.0, 0.0])[0])
        for code in sorted(set(by_currency) | set(bench_currency))
    }
    return AttributionDay(day.day, day.rate, benchmark.rate, segments, currency, day.costs / capital, weights)


# ---------------------------------------------------------------------------- linking
def carino_factor(portfolio: float, benchmark: float) -> float:
    """ln(1+R) - ln(1+B) over R - B; its limit 1/(1+R) where the two are equal."""
    if abs(portfolio - benchmark) < 1e-15:
        return 1.0 / (1.0 + portfolio)
    return (math.log1p(portfolio) - math.log1p(benchmark)) / (portfolio - benchmark)


@dataclass(frozen=True)
class SegmentResult:
    segment: str
    average_wp: float
    average_wb: float
    portfolio_return: float  # linked local return of the portfolio's holdings in the segment
    benchmark_return: float
    allocation: float
    selection: float
    interaction: float

    @property
    def total(self) -> float:
        return self.allocation + self.selection + self.interaction


@dataclass(frozen=True)
class AttributionResult:
    start: date
    end: date
    dimension: str
    portfolio: float
    benchmark: float
    segments: tuple[SegmentResult, ...]
    currency: dict[str, float]
    costs: float
    unlinked_total: float  # the plain sum of daily effects, for comparison
    days: tuple[AttributionDay, ...] = field(default_factory=tuple, repr=False)

    @property
    def active(self) -> float:
        return self.portfolio - self.benchmark

    def effect(self, name: str) -> float:
        if name == "currency":
            return sum(self.currency.values())
        if name == "costs":
            return self.costs
        return float(sum(getattr(item, name) for item in self.segments))

    @property
    def explained(self) -> float:
        return sum(self.effect(name) for name in (*EFFECTS, "currency", "costs"))

    @property
    def residual(self) -> float:
        return self.active - self.explained

    @property
    def linking_gap(self) -> float:
        """What the unlinked sum of daily effects misses: the reason linking is needed."""
        return self.active - self.unlinked_total

    def segment(self, name: str) -> SegmentResult:
        return next(item for item in self.segments if item.segment == name)


def link_attribution(days: Sequence[AttributionDay], dimension: str) -> AttributionResult:
    """Link daily effects over the period with Cariño's factors; the linked effects sum to R - B exactly."""
    if not days:
        raise ValidationError("attribution needs at least one day")
    total_p = math.prod(1.0 + item.portfolio for item in days) - 1.0
    total_b = math.prod(1.0 + item.benchmark for item in days) - 1.0
    big_k = carino_factor(total_p, total_b)
    scaled: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    currency: dict[str, float] = defaultdict(float)
    costs = 0.0
    unlinked = 0.0
    weights: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    growth_p: dict[str, float] = defaultdict(lambda: 1.0)
    growth_b: dict[str, float] = defaultdict(lambda: 1.0)
    for item in days:
        factor = carino_factor(item.portfolio, item.benchmark) / big_k
        for name, segment in item.segments.items():
            for effect in EFFECTS:
                scaled[name][effect] += getattr(segment, effect) * factor
            weights[name][0] += segment.wp
            weights[name][1] += segment.wb
            if segment.rp is not None:
                growth_p[name] *= 1.0 + segment.rp
            if segment.rb is not None:
                growth_b[name] *= 1.0 + segment.rb
        for code, value in item.currency.items():
            currency[code] += value * factor
        costs += item.costs * factor
        unlinked += item.explained
    count = len(days)
    segments = tuple(
        SegmentResult(
            name,
            weights[name][0] / count,
            weights[name][1] / count,
            growth_p[name] - 1.0,
            growth_b[name] - 1.0,
            scaled[name]["allocation"],
            scaled[name]["selection"],
            scaled[name]["interaction"],
        )
        for name in sorted(scaled, key=lambda key: -abs(sum(scaled[key].values())))
    )
    return AttributionResult(
        days[0].day,
        days[-1].day,
        dimension,
        total_p,
        total_b,
        segments,
        dict(currency),
        costs,
        unlinked,
        tuple(days),
    )


def attribute(
    portfolio: Sequence[PortfolioDay],
    benchmark: Sequence[BenchmarkDay],
    instruments: Mapping[str, Instrument],
    *,
    dimension: str = "sector",
    look_through: LookThrough,
    start: date | None = None,
    end: date | None = None,
) -> AttributionResult:
    """Attribute the active return over ``(start, end]`` by sector or by region."""
    if dimension not in {"sector", "region"}:
        raise ValidationError("attribution is by sector or by region")
    bench = {item.day: item for item in benchmark}
    chosen = [item for item in portfolio if (start is None or item.day > start) and (end is None or item.day <= end)]
    missing = [item.day for item in chosen if item.day not in bench]
    if missing:
        raise ValidationError(f"no benchmark return on {missing[0]}")
    days = [
        attribute_day(item, bench[item.day], instruments, dimension=dimension, look_through=look_through)
        for item in chosen
    ]
    return link_attribution(days, dimension)


def monthly(result: AttributionResult) -> list[AttributionResult]:
    """The same attribution linked month by month, for a calendar of effects."""
    months: dict[tuple[int, int], list[AttributionDay]] = defaultdict(list)
    for item in result.days:
        months[(item.day.year, item.day.month)].append(item)
    return [link_attribution(items, result.dimension) for _, items in sorted(months.items())]
