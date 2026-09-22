"""The end-of-day pricing run.

This is the process a fund administrator's pricing team runs every evening,
reduced to its essential steps:

1. **Collect** every source's quotes for the instruments in the book.
2. **Record** each one as a raw observation with the time it was received -
   before anyone has judged it - so the evidence survives whatever happens
   next.
3. **Validate** every source's series with the quality engine.
4. **Build the golden copy** from the values that passed, by the pricing
   policy, and raise a challenge wherever the sources disagree.
5. **Publish** the golden prices and FX rates to the tables valuation reads,
   and store the quality run so that tomorrow's dashboard can show today's
   exceptions.

Steps 2 and 5 only happen when a unit of work is supplied; without one the run
is a dry run, which is how the CLI previews a load and how the tests exercise
the logic without a database.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ..core.calendars import TradingCalendar
from ..domain.corporate_actions import CorporateAction
from ..marketdata.golden import GoldenCopy, PricingPolicy, build_golden_copy
from ..marketdata.providers.base import MarketDataProvider
from ..marketdata.quotes import FxQuote, MarketDataset
from ..observability import get_logger
from ..persistence.repositories import UnitOfWork
from ..quality.engine import QualityEngine, QualityReport

log = get_logger(__name__)


@dataclass
class PricingRunResult:
    run_id: str
    as_of: date
    dataset: MarketDataset
    report: QualityReport
    golden: GoldenCopy
    observations_recorded: int = 0
    prices_published: int = 0
    fx_published: int = 0
    sources: dict[str, int] = field(default_factory=dict)

    @property
    def withheld(self) -> int:
        return len(self.golden.unpriced)

    @property
    def challenges(self) -> int:
        return len(self.golden.challenges())

    def summary(self) -> list[tuple[str, str]]:
        return [
            ("run", self.run_id),
            ("as of", self.as_of.isoformat()),
            ("sources", ", ".join(f"{name} ({count})" for name, count in sorted(self.sources.items()))),
            ("raw observations", f"{len(self.dataset):,}"),
            ("quality findings", f"{len(self.report.findings):,} ({len(self.report.blocking()):,} blocking)"),
            ("quality score", f"{self.report.overall:.2%}"),
            ("golden prices", f"{len(self.golden):,}"),
            ("price challenges", f"{self.challenges:,}"),
            ("withheld, no clean source", f"{self.withheld:,}"),
            (
                "written to the database",
                f"{self.observations_recorded:,} observations, "
                f"{self.prices_published:,} prices, {self.fx_published:,} FX rates",
            ),
        ]


class EndOfDayPricing:
    """Collect, record, validate, reconcile and publish."""

    def __init__(
        self,
        providers: Sequence[MarketDataProvider],
        policy: PricingPolicy,
        *,
        engine: QualityEngine | None = None,
    ) -> None:
        self.providers = list(providers)
        self.policy = policy
        self.engine = engine or QualityEngine()

    def collect(
        self, instrument_ids: Sequence[str], start: date, end: date, pairs: Sequence[str] = ()
    ) -> MarketDataset:
        dataset = MarketDataset()
        for provider in self.providers:
            quotes = provider.quotes(instrument_ids, start, end)
            fx = provider.fx_quotes(pairs, start, end) if pairs else []
            dataset.extend(quotes, fx)
            log.info("pricing.collected", source=provider.name, quotes=len(quotes), fx=len(fx))
        return dataset

    def run(
        self,
        instrument_ids: Sequence[str],
        start: date,
        end: date,
        *,
        calendars: Mapping[str, TradingCalendar | str],
        actions: Sequence[CorporateAction] = (),
        pairs: Sequence[str] = (),
        unit_of_work: UnitOfWork | None = None,
        received_at: datetime | None = None,
        run_id: str | None = None,
    ) -> PricingRunResult:
        identifier = run_id or uuid.uuid4().hex[:12]
        dataset = self.collect(instrument_ids, start, end, pairs)
        report = self.engine.run(dataset, calendars=calendars, actions=actions, as_of=end, run_id=identifier)
        golden = build_golden_copy(dataset, self.policy, blocked=report.blocked_points())
        result = PricingRunResult(
            run_id=identifier,
            as_of=end,
            dataset=dataset,
            report=report,
            golden=golden,
            sources=_source_counts(dataset),
        )
        if unit_of_work is not None:
            self._persist(result, unit_of_work, received_at or datetime.now(timezone.utc))
        log.info(
            "pricing.completed",
            run_id=identifier,
            golden=len(golden),
            challenges=result.challenges,
            withheld=result.withheld,
            score=round(report.overall, 4),
        )
        return result

    def _persist(self, result: PricingRunResult, unit_of_work: UnitOfWork, received_at: datetime) -> None:
        for items in result.dataset.quotes.values():
            result.observations_recorded += unit_of_work.observations.record_many(
                items, received_at, run_id=result.run_id
            )
        result.prices_published = unit_of_work.prices.upsert_many(
            (price.instrument_id, price.day, price.value, price.currency, f"golden:{price.source}"[:32])
            for price in result.golden.prices
        )
        blocked = result.report.blocked_points()
        result.fx_published = unit_of_work.fx_rates.upsert_many(
            (rate.base, rate.quote, rate.day, rate.rate, rate.source)
            for pair, rates in result.dataset.fx.items()
            for rate in _first_per_day(rates)
            if (pair, "", rate.day) not in blocked and (pair, rate.source, rate.day) not in blocked
        )
        unit_of_work.flush()
        unit_of_work.quality.save(result.report)
        unit_of_work.flush()


def _source_counts(dataset: MarketDataset) -> dict[str, int]:
    """Records per source, prices and FX together."""
    counts: dict[str, int] = {}
    for items in dataset.quotes.values():
        for quote in items:
            counts[quote.source] = counts.get(quote.source, 0) + 1
    for rates in dataset.fx.values():
        for rate in rates:
            counts[rate.source] = counts.get(rate.source, 0) + 1
    return counts


def _first_per_day(rates: Sequence[FxQuote]) -> list[FxQuote]:
    seen: dict[date, FxQuote] = {}
    for rate in rates:
        seen.setdefault(rate.day, rate)
    return [seen[day] for day in sorted(seen)]
