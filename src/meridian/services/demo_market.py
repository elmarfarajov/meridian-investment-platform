"""The demonstration market, end to end.

One function builds everything the Day 2 charts and commands need from a
single seed: the synthetic market for the demonstration book, three vendors'
views of it, a known set of planted faults, and the pricing run over the
result. Keeping it in one place is what makes the gallery, the CLI and the
tests show the *same* market rather than three similar ones.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ..domain.corporate_actions import CorporateAction
from ..marketdata.bitemporal import BitemporalStore, end_of_day
from ..marketdata.golden import GoldenMethod, PricingPolicy
from ..marketdata.providers import (
    DEFAULT_VENDORS,
    FaultInjector,
    FaultKind,
    FaultSpec,
    InjectedFault,
    StaticProvider,
    SyntheticHistory,
    cross_rates,
    demo_market,
    vendor_panel,
)
from ..marketdata.quotes import FxQuote, MarketDataset
from ..persistence.repositories import UnitOfWork
from ..quality.engine import QualityEngine, QualityReport
from ..quality.evaluation import DetectionScore, KindScore, RuleScore, evaluate
from ..quality.findings import Finding
from ..refdata.xref import CrossReference, demo_cross_reference, xref_from_instruments
from ..seed import demo_instruments
from .pricing import EndOfDayPricing, PricingRunResult

DEMO_START = date(2024, 4, 1)
DEMO_END = date(2026, 9, 18)
DEMO_CROSSES: tuple[tuple[str, str], ...] = (("EUR", "GBP"), ("EUR", "CHF"), ("GBP", "JPY"))

#: Faults placed by hand where the charts can show them clearly. Indexes count
#: observations of that instrument from the start of the history.
SHOWCASE_FAULTS: tuple[FaultSpec, ...] = (
    FaultSpec(FaultKind.STALE_RUN, "US-MSFT", 330, length=6),
    FaultSpec(FaultKind.SPIKE, "US-MSFT", 402, magnitude=0.16),
    FaultSpec(FaultKind.MISSING_RUN, "US-MSFT", 470, length=5),
    FaultSpec(FaultKind.UNIT_ERROR, "GB-BAE", 250, length=3),
    FaultSpec(FaultKind.UNRECORDED_SPLIT, "US-JNJ", 520, magnitude=2.0),
    FaultSpec(FaultKind.CROSSED_QUOTE, "DE-BAYN", 300),
    FaultSpec(FaultKind.HOLIDAY_PRINT, "US-AAPL", 300),
    FaultSpec(FaultKind.NON_POSITIVE, "CH-ROG", 350),
    FaultSpec(FaultKind.SPIKE, "IE-IWDA", 180, magnitude=-0.12),
    FaultSpec(FaultKind.FX_TRIANGLE_BREAK, "EURGBP", 420, magnitude=0.004),
)


@dataclass
class DemoMarket:
    history: SyntheticHistory
    clean: MarketDataset
    damaged: MarketDataset
    faults: list[InjectedFault]
    calendars: dict[str, str]

    @property
    def actions(self) -> tuple[CorporateAction, ...]:
        return self.history.corporate_actions


def _with_crosses(dataset: MarketDataset) -> MarketDataset:
    legs: list[FxQuote] = [rate for items in dataset.fx.values() for rate in items]
    crosses = [rate for base, quote in DEMO_CROSSES for rate in cross_rates(legs, base, quote)]
    return MarketDataset.from_records((quote for items in dataset.quotes.values() for quote in items), legs + crosses)


def build_demo_market(
    *,
    start: date = DEMO_START,
    end: date = DEMO_END,
    seed: int = 7,
    faults: Sequence[FaultSpec] = SHOWCASE_FAULTS,
) -> DemoMarket:
    history = demo_market(seed).generate(start, end)
    clean = _with_crosses(history.dataset)
    calendars = {key: spec.calendar for key, spec in history.specs.items()}
    damaged, planted = FaultInjector(list(faults)).apply(clean, calendars)
    return DemoMarket(history, clean, damaged, planted, calendars)


def demo_policy(method: GoldenMethod = GoldenMethod.PRIORITY) -> PricingPolicy:
    return PricingPolicy(ranking=tuple(vendor.name for vendor in DEFAULT_VENDORS), tolerance_bps=25.0, method=method)


def demo_vendor_dataset(market: DemoMarket, *, seed: int = 23) -> MarketDataset:
    """The three vendors' views of the damaged market: faults reach the exchange feed, noise reaches the rest."""
    exchange, *others = DEFAULT_VENDORS
    primary = vendor_panel(market.damaged, [exchange], seed=seed)
    secondary = vendor_panel(market.clean, others, seed=seed + 1)
    fx = [rate for items in market.damaged.fx.values() for rate in items]
    return MarketDataset.from_records(
        [quote for dataset in (primary, secondary) for items in dataset.quotes.values() for quote in items], fx
    )


def run_demo_pricing(
    market: DemoMarket,
    *,
    unit_of_work: UnitOfWork | None = None,
    method: GoldenMethod = GoldenMethod.PRIORITY,
    backfill: bool = False,
) -> PricingRunResult:
    vendors = demo_vendor_dataset(market)
    providers = [
        StaticProvider(
            source,
            [quote for items in vendors.quotes.values() for quote in items if quote.source == source],
            [rate for items in vendors.fx.values() for rate in items] if source == "exchange" else [],
        )
        for source in (vendor.name for vendor in DEFAULT_VENDORS)
    ]
    pricing = EndOfDayPricing(providers, demo_policy(method))
    instruments = sorted(market.clean.instruments)
    return pricing.run(
        instruments,
        market.history.market_factor[0][0],
        market.history.market_factor[-1][0],
        calendars=market.calendars,
        actions=market.actions,
        pairs=market.clean.pairs,
        unit_of_work=unit_of_work,
        backfill=backfill,
    )


def demo_reference_data() -> CrossReference:
    """The book's own identifiers plus the illustrative history of renames and reuse."""
    reference = demo_cross_reference()
    already_described = {entry.instrument_id for entry in reference.entries()}
    for entry in xref_from_instruments(demo_instruments(), valid_from=date(2024, 1, 2)).entries():
        if entry.instrument_id not in already_described:
            reference.add(entry)
    return reference


def demo_quality_report(market: DemoMarket) -> QualityReport:
    """The quality run over the damaged single feed: the view the dashboard and the fault charts show."""
    return QualityEngine().run(market.damaged, calendars=market.calendars, actions=market.actions, run_id="demo")


def demo_detection_scores(seeds: Sequence[int] = (7, 11, 19), *, per_instrument: int = 4) -> DetectionScore:
    """Recall and precision pooled over several independently seeded markets with random fault plans."""
    kinds: dict[FaultKind, list[int]] = {}
    rules: dict[str, list[int]] = {}
    missed: list[InjectedFault] = []
    false_alarms: list[Finding] = []
    for seed in seeds:
        market = build_demo_market(seed=seed, faults=())
        plan = FaultInjector.random_plan(
            market.clean, per_instrument=per_instrument, fx_pairs=[f"{a}{b}" for a, b in DEMO_CROSSES], seed=seed
        )
        damaged, faults = plan.apply(market.clean, market.calendars)
        report = QualityEngine().run(damaged, calendars=market.calendars, actions=market.actions)
        score = evaluate(report.findings, faults)
        for item in score.kinds:
            totals = kinds.setdefault(item.kind, [0, 0])
            totals[0] += item.planted
            totals[1] += item.detected
        for rule in score.rules:
            totals = rules.setdefault(rule.rule, [0, 0])
            totals[0] += rule.flagged
            totals[1] += rule.true_positives
        missed.extend(score.missed)
        false_alarms.extend(score.false_alarms)
    return DetectionScore(
        kinds=[KindScore(kind, planted, detected) for kind, (planted, detected) in kinds.items()],
        rules=[RuleScore(rule, flagged, hits) for rule, (flagged, hits) in sorted(rules.items())],
        missed=missed,
        false_alarms=false_alarms,
    )


def demo_revision_store(market: DemoMarket, *, instrument_id: str = "US-AAPL", days: int = 90) -> BitemporalStore:
    """A vendor feed with the corrections real feeds carry: wrong first prints fixed a few days later.

    Every value is first published at 22:00 UTC on its own date. Eight first
    prints are wrong and corrected one to three days later; three dates are
    published two days late. The pattern is fixed, not random, so the chart
    and its caption always agree.
    """
    series = market.clean.close_series(instrument_id)
    window = list(series)[-days:]
    errors = {6: 0.042, 15: -0.018, 23: 0.027, 38: -0.055, 47: 0.013, 58: -0.031, 71: 0.022, 83: -0.016}
    delays = {6: 1, 15: 2, 23: 1, 38: 3, 47: 1, 58: 2, 71: 1, 83: 3}
    late = {30: 2, 52: 2, 64: 2}
    store = BitemporalStore()
    key = f"{instrument_id}:close"
    for index, point in enumerate(window):
        first_known = end_of_day(point.day + timedelta(days=late.get(index, 0)), 22, 0)
        if index in errors:
            wrong = (point.value * Decimal(repr(1 + errors[index]))).quantize(point.value)
            store.record(key, point.day, wrong, first_known, source="vendor", note="first print")
            corrected = end_of_day(point.day + timedelta(days=delays[index]), 9, 30)
            store.record(key, point.day, point.value, corrected, source="vendor", note="correction")
        else:
            store.record(key, point.day, point.value, first_known, source="vendor")
    return store
