"""Run every rule over a dataset and turn the findings into a verdict.

The engine does three things the individual rules cannot:

1. **Builds a market proxy.** For each instrument it takes the median
   event-adjusted return of *every other* instrument on the same day. The
   outlier rules score returns net of that proxy, so a broad sell-off is not
   mistaken for thirty simultaneous bad ticks. Leaving the instrument itself
   out of its own proxy stops a bad print from diluting the evidence against
   itself.
2. **Scores every series** on each quality dimension as the share of expected
   observations untouched by a finding of that dimension, and combines the
   dimensions with fixed weights into one number with a traffic light.
3. **Decides what may be published.** Any point touched by an error or worse
   is withheld from the golden copy until someone signs it off.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from ..core.calendars import TradingCalendar, get_calendar
from ..domain.corporate_actions import CorporateAction
from ..marketdata.quotes import MarketDataset
from ..marketdata.series import TimeSeries
from .context import SeriesContext
from .findings import DIMENSION_WEIGHTS, Dimension, Finding, Severity
from .fx_rules import FxInverseRule, FxTriangleRule
from .rules import MissingDays, RobustOutlier, Rule, SpikeReversal, StaleMark, default_rules

GREEN_THRESHOLD = 0.995
AMBER_THRESHOLD = 0.98


@dataclass(frozen=True, slots=True)
class SeriesScore:
    """How good one series is, overall and per dimension."""

    key: str
    source: str
    expected: int
    observed: int
    dimensions: dict[Dimension, float]
    overall: float
    counts: dict[Severity, int]

    @property
    def status(self) -> str:
        if self.counts.get(Severity.CRITICAL, 0):
            return "red"
        if self.overall >= GREEN_THRESHOLD:
            return "green"
        if self.overall >= AMBER_THRESHOLD:
            return "amber"
        return "red"

    @property
    def coverage(self) -> float:
        return self.observed / self.expected if self.expected else 1.0

    @property
    def total_findings(self) -> int:
        return sum(self.counts.values())


@dataclass
class QualityReport:
    """Everything one quality run found."""

    run_id: str
    as_of: date
    findings: list[Finding]
    scores: list[SeriesScore]
    fx_residuals: dict[str, list[tuple[date, float]]] = field(default_factory=dict)
    expected_days: dict[str, tuple[date, ...]] = field(default_factory=dict)

    # ------------------------------------------------------------------ slices
    def for_key(self, key: str) -> list[Finding]:
        return [finding for finding in self.findings if finding.key == key]

    def by_rule(self) -> dict[str, int]:
        return dict(sorted(Counter(finding.rule for finding in self.findings).items()))

    def by_severity(self) -> dict[Severity, int]:
        counts = Counter(finding.severity for finding in self.findings)
        return {severity: counts.get(severity, 0) for severity in Severity}

    def by_dimension(self) -> dict[Dimension, int]:
        counts = Counter(finding.dimension for finding in self.findings)
        return {dimension: counts.get(dimension, 0) for dimension in Dimension}

    def by_rule_and_severity(self) -> dict[str, dict[Severity, int]]:
        table: dict[str, dict[Severity, int]] = defaultdict(lambda: dict.fromkeys(Severity, 0))
        for finding in self.findings:
            table[finding.rule][finding.severity] += 1
        return dict(sorted(table.items()))

    def score(self, key: str, source: str | None = None) -> SeriesScore:
        for item in self.scores:
            if item.key == key and (source is None or item.source == source):
                return item
        raise KeyError(key)

    @property
    def overall(self) -> float:
        """Observation-weighted average score across every series."""
        total = sum(item.expected for item in self.scores)
        if not total:
            return 1.0
        return sum(item.overall * item.expected for item in self.scores) / total

    def blocking(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity.blocks_publication]

    def blocked_points(self) -> set[tuple[str, str, date]]:
        """(key, source, day) triples that must not be published without sign-off.

        Blocking is per source: a bad print from one vendor withholds that
        vendor's value, not the instrument, so the golden copy can still be
        built from the sources that were clean that day.
        """
        blocked: set[tuple[str, str, date]] = set()
        for finding in self.blocking():
            days = self.expected_days.get(finding.key, ())
            covered = [day for day in days if finding.day <= day <= finding.last_day]
            for day in covered or [finding.day]:
                blocked.add((finding.key, finding.source, day))
        return blocked

    def summary_rows(self) -> list[tuple[str, str, int, int, str, str, int, int]]:
        """(key, source, observed, expected, coverage, score, errors, warnings) per series."""
        rows = []
        for item in sorted(self.scores, key=lambda score: (score.overall, score.key)):
            errors = item.counts.get(Severity.ERROR, 0) + item.counts.get(Severity.CRITICAL, 0)
            rows.append(
                (
                    item.key,
                    item.source,
                    item.observed,
                    item.expected,
                    f"{item.coverage:.1%}",
                    f"{item.overall:.2%}",
                    errors,
                    item.counts.get(Severity.WARNING, 0),
                )
            )
        return rows


def attach_market_proxy(contexts: Sequence[SeriesContext], *, minimum: int = 3) -> None:
    """Give each context the leave-one-out cross-sectional median of the others' adjusted returns.

    With fewer than ``minimum + 1`` series there is no meaningful cross-section
    and the contexts are left without a proxy.
    """
    if len(contexts) <= minimum:
        return
    by_day: dict[date, list[tuple[int, float]]] = defaultdict(list)
    for index, context in enumerate(contexts):
        for day, value in context.adjusted_returns:
            by_day[day].append((index, value))
    for index, context in enumerate(contexts):
        proxy: dict[date, float] = {}
        for day, entries in by_day.items():
            others = [value for owner, value in entries if owner != index]
            if len(others) >= minimum:
                proxy[day] = statistics.median(others)
        context.market = proxy
        context.__dict__.pop("residual_returns", None)  # drop a cached value computed without the proxy


def fx_series_rules() -> list[Rule]:
    """The subset of series rules that make sense for an FX rate: no bid, no ask, no corporate actions."""
    return [MissingDays(), StaleMark(min_repeats=2), RobustOutlier(threshold=10.0), SpikeReversal(threshold=6.0)]


class QualityEngine:
    """Apply rules to every series in a dataset and score the result."""

    def __init__(
        self,
        rules: Sequence[Rule] | None = None,
        *,
        fx_rules: Sequence[FxTriangleRule | FxInverseRule] | None = None,
        fx_rules_per_series: Sequence[Rule] | None = None,
        use_market_proxy: bool = True,
        pivot: str = "USD",
    ) -> None:
        self.rules = list(rules) if rules is not None else default_rules()
        self.fx_rules: list[FxTriangleRule | FxInverseRule] = (
            list(fx_rules) if fx_rules is not None else [FxTriangleRule(pivot=pivot), FxInverseRule()]
        )
        self.fx_series_rules = list(fx_rules_per_series) if fx_rules_per_series is not None else fx_series_rules()
        self.use_market_proxy = use_market_proxy

    def check(self, context: SeriesContext) -> list[Finding]:
        findings: list[Finding] = []
        for rule in self.rules:
            findings.extend(rule.check(context))
        return sorted(findings, key=lambda item: (item.day, item.rule))

    def run(
        self,
        dataset: MarketDataset,
        *,
        calendars: Mapping[str, TradingCalendar | str] | None = None,
        actions: Sequence[CorporateAction] = (),
        as_of: date | None = None,
        run_id: str | None = None,
        default_calendar: str = "XNYS",
    ) -> QualityReport:
        calendar_map = {key: get_calendar(value) for key, value in (calendars or {}).items()}
        resolved_as_of = as_of or max(dataset.days(), default=date.today())

        contexts: list[SeriesContext] = []
        for instrument_id in dataset.instruments:
            quotes = dataset.for_instrument(instrument_id)
            for source in sorted({quote.source for quote in quotes}):
                contexts.append(
                    SeriesContext.build(
                        instrument_id,
                        [quote for quote in quotes if quote.source == source],
                        calendar_map.get(instrument_id, get_calendar(default_calendar)),
                        as_of=resolved_as_of,
                        source=source,
                        actions=actions,
                    )
                )
        if self.use_market_proxy:
            attach_market_proxy(contexts)

        findings: list[Finding] = []
        scores: list[SeriesScore] = []
        expected: dict[str, tuple[date, ...]] = {}
        for context in contexts:
            found = self.check(context)
            findings.extend(found)
            scores.append(self._score(context, found))
            expected[context.key] = context.expected_days

        fx_series = {pair: dataset.fx_series(pair) for pair in dataset.pairs}
        residuals: dict[str, list[tuple[date, float]]] = {}
        for fx_rule in self.fx_rules:
            fx_found = fx_rule.check(fx_series)
            findings.extend(fx_found)
            if isinstance(fx_rule, FxTriangleRule):
                residuals = fx_rule.residuals(fx_series)
        for pair, series in fx_series.items():
            context = SeriesContext.from_series(pair, series, "WEEKEND", as_of=resolved_as_of)
            found = [finding for rule in self.fx_series_rules for finding in rule.check(context)]
            found += [finding for finding in findings if finding.key == pair]
            findings.extend(finding for finding in found if finding.rule not in {"fx_triangle", "fx_inverse"})
            scores.append(self._score(context, found))
            expected[pair] = context.expected_days

        findings.sort(key=lambda item: (item.key, item.day, item.rule))
        return QualityReport(
            run_id=run_id or uuid.uuid4().hex[:12],
            as_of=resolved_as_of,
            findings=findings,
            scores=scores,
            fx_residuals=residuals,
            expected_days=expected,
        )

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _score(context: SeriesContext, findings: Sequence[Finding]) -> SeriesScore:
        expected_days = context.expected_days
        expected_count = max(len(expected_days), 1)
        affected: dict[Dimension, set[date]] = defaultdict(set)
        for finding in findings:
            covered = {day for day in expected_days if finding.day <= day <= finding.last_day}
            if not covered:  # a print on a closed day, or a lateness measured at the valuation date
                span = int(finding.observed) if finding.rule == "late_mark" and finding.observed else 1
                covered = {finding.day} if span <= 1 else set(expected_days[-span:])
            affected[finding.dimension] |= covered
        dimensions = {
            dimension: max(0.0, 1.0 - len(affected.get(dimension, set())) / expected_count) for dimension in Dimension
        }
        overall = sum(dimensions[dimension] * weight for dimension, weight in DIMENSION_WEIGHTS.items())
        counts = Counter(finding.severity for finding in findings)
        expected_set = set(expected_days)
        return SeriesScore(
            key=context.key,
            source=context.source,
            expected=len(expected_days),
            observed=sum(1 for day in context.days if day in expected_set),
            dimensions=dimensions,
            overall=overall,
            counts={severity: counts.get(severity, 0) for severity in Severity},
        )


def run_quality(
    dataset: MarketDataset,
    calendars: Mapping[str, TradingCalendar | str] | None = None,
    *,
    actions: Sequence[CorporateAction] = (),
    as_of: date | None = None,
) -> QualityReport:
    """One-call convenience with the default rule set."""
    return QualityEngine().run(dataset, calendars=calendars, actions=actions, as_of=as_of)


def series_report(key: str, series: TimeSeries, calendar: str = "XNYS") -> list[Finding]:
    """Run the default rules on one bare series, for ad-hoc checks from the CLI or a notebook."""
    return QualityEngine().check(SeriesContext.from_series(key, series, calendar))
