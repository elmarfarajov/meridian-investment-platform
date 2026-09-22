"""The quality rules.

Each rule answers one narrow question about one series and says which quality
dimension the answer belongs to. Rules are small, independent and
configurable, because every desk tunes them differently: a threshold that is
right for a large-cap equity is wrong for a high-yield bond, and the rule has
to be retunable without being rewritten.

Rules report problems; they never repair them. Repair is a decision with an
audit trail (who overrode which price, why, on whose authority) and belongs to
the pricing workflow, not to a validation pass.
"""

from __future__ import annotations

import itertools
import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction

from .context import SeriesContext
from .findings import Dimension, Finding, Severity
from .robust import rolling_robust_z


class Rule(ABC):
    """One check. Subclasses set ``name`` and ``dimension`` and implement :meth:`check`."""

    name: str = "rule"
    dimension: Dimension = Dimension.VALIDITY
    description: str = ""

    @abstractmethod
    def check(self, context: SeriesContext) -> list[Finding]: ...

    def finding(
        self,
        context: SeriesContext,
        day: date,
        severity: Severity,
        message: str,
        **extra: object,
    ) -> Finding:
        return Finding(
            rule=self.name,
            key=context.key,
            day=day,
            severity=severity,
            dimension=self.dimension,
            message=message,
            source=context.source,
            **extra,  # type: ignore[arg-type]
        )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


def _runs(days: Sequence[date], calendar_days: Sequence[date]) -> list[list[date]]:
    """Group ``days`` into runs that are consecutive within ``calendar_days``."""
    position = {day: index for index, day in enumerate(calendar_days)}
    runs: list[list[date]] = []
    for day in sorted(days):
        if runs and position.get(day, -2) == position.get(runs[-1][-1], -5) + 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    return runs


# ---------------------------------------------------------------------------- validity
class NonPositivePrice(Rule):
    """A price of zero or below. Almost always a placeholder a vendor sent for 'no data'."""

    name = "non_positive_price"
    dimension = Dimension.VALIDITY
    description = "Close of zero or below"

    def check(self, context: SeriesContext) -> list[Finding]:
        return [
            self.finding(
                context,
                quote.day,
                Severity.CRITICAL,
                f"close is {quote.close}; a zero is usually a vendor's placeholder for a missing value",
                observed=float(quote.close),
            )
            for quote in context.quotes
            if quote.close <= 0
        ]


class NonTradingDayPrint(Rule):
    """A price dated on a day the instrument's own exchange was shut."""

    name = "non_trading_day"
    dimension = Dimension.VALIDITY
    description = "Price on a weekend or exchange holiday"

    def check(self, context: SeriesContext) -> list[Finding]:
        findings: list[Finding] = []
        for day in context.days:
            if context.calendar.is_business_day(day):
                continue
            reason = context.calendar.holiday_name(day) or day.strftime("%A")
            findings.append(
                self.finding(
                    context,
                    day,
                    Severity.ERROR,
                    f"price on a closed day ({reason}, {context.calendar.name}); likely a mis-dated record",
                )
            )
        return findings


class CrossedQuote(Rule):
    """A bid above the ask cannot trade and cannot be a mid."""

    name = "crossed_quote"
    dimension = Dimension.VALIDITY
    description = "Bid above ask"

    def check(self, context: SeriesContext) -> list[Finding]:
        findings: list[Finding] = []
        for quote in context.quotes:
            if quote.is_crossed:
                assert quote.bid is not None and quote.ask is not None
                findings.append(
                    self.finding(
                        context,
                        quote.day,
                        Severity.ERROR,
                        f"bid {quote.bid} above ask {quote.ask}",
                        observed=float(quote.bid - quote.ask),
                    )
                )
        return findings


# ---------------------------------------------------------------------------- completeness
@dataclass
class MissingDays(Rule):
    """Trading days of the instrument's own calendar with no price.

    Judged against the *instrument's* calendar, not a generic weekday grid: a
    London stock with no price on the late-May bank holiday is complete, and one
    with no price on the US Memorial Day is not.
    """

    error_after: int = 3
    name = "missing_days"
    dimension = Dimension.COMPLETENESS
    description = "Expected trading days with no price"

    def check(self, context: SeriesContext) -> list[Finding]:
        present = set(context.days)
        missing = [day for day in context.expected_days if day not in present]
        findings: list[Finding] = []
        for run in _runs(missing, context.expected_days):
            severity = Severity.ERROR if len(run) >= self.error_after else Severity.WARNING
            label = "day" if len(run) == 1 else "consecutive days"
            findings.append(
                self.finding(
                    context,
                    run[0],
                    severity,
                    f"{len(run)} {label} with no price on {context.calendar.name}",
                    end_day=run[-1],
                    observed=float(len(run)),
                )
            )
        return findings


# ---------------------------------------------------------------------------- timeliness
@dataclass
class StaleMark(Rule):
    """A close repeated unchanged across consecutive trading days.

    One unchanged day happens (a thinly traded name, a price on a round
    number). Two in a row on a liquid instrument almost never does - the
    probability that a stock moving 1.5% a day closes on the same cent three
    times running is of the order of one in a million - so ``min_repeats``
    defaults to two.
    """

    min_repeats: int = 2
    error_after: int = 4
    name = "stale_mark"
    dimension = Dimension.TIMELINESS
    description = "Close unchanged across consecutive days"

    def check(self, context: SeriesContext) -> list[Finding]:
        points = [point for point in context.series if point.value > 0]
        findings: list[Finding] = []
        run: list[date] = []
        for previous, current in itertools.pairwise(points):
            if current.value == previous.value:
                run.append(current.day)
                continue
            findings.extend(self._close_run(context, run, previous.value))
            run = []
        if points:
            findings.extend(self._close_run(context, run, points[-1].value))
        return findings

    def _close_run(self, context: SeriesContext, run: list[date], value: Decimal) -> list[Finding]:
        if len(run) < self.min_repeats:
            return []
        severity = Severity.ERROR if len(run) >= self.error_after else Severity.WARNING
        return [
            self.finding(
                context,
                run[0],
                severity,
                f"close unchanged at {value} for {len(run)} further trading days",
                end_day=run[-1],
                observed=float(len(run)),
            )
        ]


@dataclass
class LateMark(Rule):
    """The newest price is older than the valuation date allows."""

    max_lag_days: int = 1
    name = "late_mark"
    dimension = Dimension.TIMELINESS
    description = "Latest price older than the valuation date allows"

    def check(self, context: SeriesContext) -> list[Finding]:
        if not context.series:
            return []
        last = context.series.last.day
        if last >= context.as_of:
            return []
        lag = context.calendar.business_days_between(last, context.as_of)
        if lag <= self.max_lag_days:
            return []
        return [
            self.finding(
                context,
                context.as_of,
                Severity.ERROR,
                f"latest price is from {last.isoformat()}, {lag} trading days before the valuation date",
                observed=float(lag),
                expected=float(self.max_lag_days),
            )
        ]


# ---------------------------------------------------------------------------- accuracy
@dataclass
class RobustOutlier(Rule):
    """A return far outside the recent distribution, judged by median and MAD.

    Scored on event-adjusted returns net of the market proxy, over a trailing
    window that excludes the day being judged. The default threshold is high
    on purpose: returns have fat tails, and a rule that fires on every genuine
    four-sigma day is a rule the desk learns to ignore.
    """

    threshold: float = 9.0
    window: int = 60
    min_periods: int = 20
    name = "robust_outlier"
    dimension = Dimension.ACCURACY
    description = "Return far outside the trailing robust range"

    def check(self, context: SeriesContext) -> list[Finding]:
        returns = context.residual_returns
        scores = rolling_robust_z([value for _, value in returns], self.window, min_periods=self.min_periods)
        findings: list[Finding] = []
        for (day, value), score in zip(returns, scores, strict=True):
            if score is None or abs(score) < self.threshold:
                continue
            findings.append(
                self.finding(
                    context,
                    day,
                    Severity.ERROR,
                    f"return of {math.expm1(value):+.2%} is {abs(score):.1f} robust deviations from the recent median",
                    observed=value,
                    score=score if math.isfinite(score) else math.copysign(999.0, score),
                )
            )
        return findings


@dataclass
class SpikeReversal(Rule):
    """A large move that is undone the next day: the signature of a bad tick.

    A genuine price shock persists; a mis-keyed print does not. Requiring the
    reversal makes this rule far more precise than the outlier test alone, at
    the cost of only being able to judge a day once the next one has arrived.
    """

    threshold: float = 5.0
    reversal: float = 0.6
    window: int = 60
    min_periods: int = 20
    name = "spike_reversal"
    dimension = Dimension.ACCURACY
    description = "Large move reversed the next day"

    def check(self, context: SeriesContext) -> list[Finding]:
        returns = context.residual_returns
        values = [value for _, value in returns]
        scores = rolling_robust_z(values, self.window, min_periods=self.min_periods)
        findings: list[Finding] = []
        for index in range(len(returns) - 1):
            score = scores[index]
            if score is None or abs(score) < self.threshold:
                continue
            move, following = values[index], values[index + 1]
            if move * following >= 0 or abs(following) < self.reversal * abs(move):
                continue
            day = returns[index][0]
            findings.append(
                self.finding(
                    context,
                    day,
                    Severity.ERROR,
                    f"{math.expm1(move):+.2%} then {math.expm1(following):+.2%} the next day; "
                    "the print looks like a bad tick",
                    observed=move,
                    score=score if math.isfinite(score) else math.copysign(999.0, score),
                )
            )
        return findings


# ---------------------------------------------------------------------------- consistency
#: Ratios that a genuine capital event or a unit error produces, with a label for each.
_JUMP_CANDIDATES: tuple[tuple[Fraction, str], ...] = (
    (Fraction(100), "a unit error (x100: pence against pounds, or cents against dollars)"),
    (Fraction(1, 100), "a unit error (x100: pence against pounds, or cents against dollars)"),
    *((Fraction(1, ratio), f"an unrecorded {ratio}-for-1 split") for ratio in (2, 3, 4, 5, 8, 10, 20)),
    *((Fraction(ratio), f"an unrecorded 1-for-{ratio} reverse split") for ratio in (2, 3, 4, 5, 8, 10, 20)),
    (Fraction(2, 3), "an unrecorded 3-for-2 split"),
)


@dataclass
class UnexplainedJump(Rule):
    """A price change matching a split ratio or a unit error, with no event to explain it.

    Also checks the converse: an event on file whose ex-date shows no matching
    move, which usually means the event was loaded with the wrong date.
    """

    tolerance: float = 0.06
    minimum_move: float = 0.30
    name = "unexplained_jump"
    dimension = Dimension.CONSISTENCY
    description = "Move matching a split ratio or unit error with no event on file"

    def check(self, context: SeriesContext) -> list[Finding]:
        findings: list[Finding] = []
        points = [point for point in context.series if point.value > 0]
        for previous, current in itertools.pairwise(points):
            ratio = float(current.value / previous.value)
            events = context.actions_by_date.get(current.day, [])
            capital = [event for event in events if event.action_type.is_capital_change]
            if capital:
                findings.extend(self._check_event(context, current.day, previous.value, ratio, capital))
                continue
            if abs(math.log(ratio)) < math.log(1 + self.minimum_move):
                continue
            for candidate, label in _JUMP_CANDIDATES:
                if abs(ratio / float(candidate) - 1) <= self.tolerance:
                    findings.append(
                        self.finding(
                            context,
                            current.day,
                            Severity.ERROR,
                            f"price moved {ratio - 1:+.1%} ({previous.value} to {current.value}), "
                            f"consistent with {label}",
                            observed=ratio,
                            expected=float(candidate),
                        )
                    )
                    break
        return findings

    def _check_event(
        self, context: SeriesContext, day: date, cum_price: Decimal, ratio: float, events: Sequence[object]
    ) -> list[Finding]:
        factor = float(context.event_factor(day, cum_price))
        if factor == 1 or abs(ratio / factor - 1) <= max(self.tolerance, 0.25):
            return []
        return [
            self.finding(
                context,
                day,
                Severity.WARNING,
                f"a capital event goes ex today with factor {factor:.4f}, but the price moved {ratio - 1:+.1%}; "
                "check the event's ex-date",
                observed=ratio,
                expected=factor,
            )
        ]


@dataclass
class CloseOutsideQuote(Rule):
    """A close outside its own bid and ask, by more than a tolerance."""

    tolerance_bps: float = 50.0
    name = "close_outside_quote"
    dimension = Dimension.CONSISTENCY
    description = "Close outside the day's bid-ask range"

    def check(self, context: SeriesContext) -> list[Finding]:
        findings: list[Finding] = []
        margin = Decimal(repr(self.tolerance_bps / 10_000))
        for quote in context.quotes:
            if quote.bid is None or quote.ask is None or quote.is_crossed or quote.close <= 0:
                continue
            low, high = quote.bid * (1 - margin), quote.ask * (1 + margin)
            if low <= quote.close <= high:
                continue
            reference = quote.bid if quote.close < quote.bid else quote.ask
            distance = float((quote.close - reference) / reference) * 10_000
            findings.append(
                self.finding(
                    context,
                    quote.day,
                    Severity.WARNING,
                    f"close {quote.close} is {abs(distance):,.0f} bp outside the {quote.bid}/{quote.ask} quote",
                    observed=distance,
                )
            )
        return findings


@dataclass
class WideSpread(Rule):
    """A quoted spread far wider than the instrument's own norm."""

    multiple: float = 6.0
    floor_bps: float = 25.0
    name = "wide_spread"
    dimension = Dimension.ACCURACY
    description = "Spread far wider than usual"

    def check(self, context: SeriesContext) -> list[Finding]:
        spreads = [
            (quote.day, spread)
            for quote in context.quotes
            if not quote.is_crossed and (spread := quote.spread_bps) is not None
        ]
        if len(spreads) < 10:
            return []
        typical = sorted(value for _, value in spreads)[len(spreads) // 2]
        limit = max(self.floor_bps, self.multiple * typical)
        return [
            self.finding(
                context,
                day,
                Severity.WARNING,
                f"spread {value:,.1f} bp against a typical {typical:,.1f} bp",
                observed=value,
                expected=typical,
            )
            for day, value in spreads
            if value > limit
        ]


def default_rules() -> list[Rule]:
    """The rule set the end-of-day pricing run applies to every instrument."""
    return [
        NonPositivePrice(),
        NonTradingDayPrint(),
        CrossedQuote(),
        MissingDays(),
        StaleMark(),
        LateMark(),
        RobustOutlier(),
        SpikeReversal(),
        UnexplainedJump(),
        CloseOutsideQuote(),
        WideSpread(),
    ]


def rule_catalogue(rules: Sequence[Rule] | None = None) -> list[tuple[str, str, str]]:
    """(name, dimension, description) for every rule, for the CLI and the docs."""
    return [(rule.name, rule.dimension.value, rule.description) for rule in (rules or default_rules())]


__all__ = [
    "CloseOutsideQuote",
    "CrossedQuote",
    "LateMark",
    "MissingDays",
    "NonPositivePrice",
    "NonTradingDayPrint",
    "RobustOutlier",
    "Rule",
    "SpikeReversal",
    "StaleMark",
    "UnexplainedJump",
    "WideSpread",
    "default_rules",
    "rule_catalogue",
]
