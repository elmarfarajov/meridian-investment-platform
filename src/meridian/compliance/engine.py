"""Evaluating a mandate against a snapshot.

For every rule the engine reports the **value** of its measure, whether that is
within the bound (``pass``), past the warning level (``warning``), outside the
bound (``breach``), or cannot be computed today (``not evaluable`` - a risk
metric before the risk model has enough history). It also reports:

* **utilisation** - how much of the limit is used: 0.93 is 93% of the way to
  an upper limit; above 1 is a breach. For a lower limit it is limit / value,
  so the same number means the same thing on both sides;
* **headroom** - how far the value can move before the limit, in the
  measure's own units;
* **contributors** - the holdings or groups that make up the value, largest
  first: what a portfolio manager has to sell to cure a breach.

A holding that lacks an attribute a condition refers to does not match it: a
bond without a sector is not "in Energy", and an equity without a rating is
not "below BBB-". That is the rule a mandate intends; the reverse would flag
every stock as junk.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .language import (
    And,
    Comparison,
    ConcentrationSum,
    Condition,
    CountOf,
    Literal,
    Mandate,
    MaxGroupWeight,
    Membership,
    Metric,
    NoHoldings,
    Or,
    Rule,
    WeightOf,
)
from .snapshot import Attribute, Holding, Snapshot, rating_score

EPSILON = 1e-12
STATUSES: tuple[str, ...] = ("pass", "warning", "breach", "not evaluable")


# ---------------------------------------------------------------------------- conditions
def _comparable(field: str, value: Attribute | Literal) -> float | str | None:
    if value is None:
        return None
    if field == "rating":
        return float(rating_score(str(value)))
    if isinstance(value, Decimal | int | float):
        return float(value)
    return str(value)


def _compare(left: float | str, operator: str, right: float | str) -> bool:
    if isinstance(left, str) != isinstance(right, str):
        return False
    if operator == "=":
        return left == right
    if operator == "!=":
        return left != right
    if isinstance(left, str) or isinstance(right, str):
        return False  # ordering is defined for numbers and ratings only
    if operator == "<":
        return left < right - EPSILON
    if operator == "<=":
        return left <= right + EPSILON
    if operator == ">":
        return left > right + EPSILON
    return left >= right - EPSILON


def matches(condition: Condition | None, holding: Holding) -> bool:
    if condition is None:
        return True
    if isinstance(condition, And):
        return all(matches(part, holding) for part in condition.parts)
    if isinstance(condition, Or):
        return any(matches(part, holding) for part in condition.parts)
    if isinstance(condition, Comparison):
        left = _comparable(condition.field, holding.attribute(condition.field))
        right = _comparable(condition.field, condition.value)
        return left is not None and right is not None and _compare(left, condition.operator, right)
    assert isinstance(condition, Membership)
    left = _comparable(condition.field, holding.attribute(condition.field))
    if left is None:
        return False
    found = any(left == _comparable(condition.field, value) for value in condition.values)
    return not found if condition.negated else found


# ---------------------------------------------------------------------------- results
@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    value: float | None
    status: str
    utilisation: float | None
    headroom: float | None
    contributors: tuple[tuple[str, float], ...] = ()
    group: str | None = None  # the heaviest group, for "max weight by"

    @property
    def is_breach(self) -> bool:
        return self.status == "breach"


@dataclass(frozen=True)
class ComplianceReport:
    day: date
    mandate: Mandate
    results: tuple[RuleResult, ...] = field(default_factory=tuple)

    def result(self, rule_id: str) -> RuleResult:
        return next(item for item in self.results if item.rule.rule_id == rule_id)

    def count(self, status: str) -> int:
        return sum(1 for item in self.results if item.status == status)

    @property
    def breaches(self) -> tuple[RuleResult, ...]:
        return tuple(item for item in self.results if item.status == "breach")

    @property
    def compliant(self) -> bool:
        return not any(item.is_breach and item.rule.severity == "hard" for item in self.results)


# ---------------------------------------------------------------------------- measures
def _holdings(snapshot: Snapshot, look_through: bool) -> tuple[Holding, ...]:
    return snapshot.expanded() if look_through else snapshot.holdings


def _groups(holdings: Sequence[Holding], group_by: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for holding in holdings:
        label = holding.attribute(group_by)
        if label is not None:
            totals[str(label)] += holding.weight
    return dict(totals)


def _by_key(holdings: Sequence[Holding]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for holding in holdings:
        totals[holding.key] += holding.weight
    return dict(totals)


def measure(rule: Rule, snapshot: Snapshot) -> tuple[float | None, tuple[tuple[str, float], ...], str | None]:
    """The rule's value on a snapshot, its contributors (largest first) and, for groupings, the heaviest group."""
    spec = rule.measure
    if isinstance(spec, Metric):
        value = snapshot.metrics.get(spec.name)
        return (None if value is None or math.isnan(value) else float(value)), (), None
    selected = [holding for holding in _holdings(snapshot, spec.look_through) if matches(spec.filter, holding)]
    if isinstance(spec, WeightOf | NoHoldings):
        parts = sorted(_by_key(selected).items(), key=lambda item: -abs(item[1]))
        return sum(value for _, value in parts), tuple(parts), None
    if isinstance(spec, CountOf):
        keys = _by_key(selected)
        return float(len(keys)), tuple(sorted(keys.items(), key=lambda item: -item[1])), None
    groups = sorted(_groups(selected, spec.group_by).items(), key=lambda item: -item[1])
    if isinstance(spec, MaxGroupWeight):
        if not groups:
            return 0.0, (), None
        return groups[0][1], tuple(groups), groups[0][0]
    assert isinstance(spec, ConcentrationSum)
    above = [(label, value) for label, value in groups if value > float(spec.threshold) + EPSILON]
    return sum(value for _, value in above), tuple(above), None


def utilisation(rule: Rule, value: float) -> float:
    bound = rule.bound
    ratios: list[float] = []
    if bound.upper is not None:
        upper = float(bound.upper)
        ratios.append(value / upper if upper > 0 else (0.0 if value <= EPSILON else math.inf))
    if bound.lower is not None and not bound.exact:
        lower = float(bound.lower)
        ratios.append(lower / value if value > 0 else (0.0 if lower <= 0 else math.inf))
    return max(ratios)


def headroom(rule: Rule, value: float) -> float:
    bound = rule.bound
    rooms: list[float] = []
    if bound.upper is not None:
        rooms.append(float(bound.upper) - value)
    if bound.lower is not None:
        rooms.append(value - float(bound.lower))
    return min(rooms)


def within(rule: Rule, value: float) -> bool:
    bound = rule.bound
    if bound.exact:
        assert bound.upper is not None
        return abs(value - float(bound.upper)) <= EPSILON
    if bound.upper is not None:
        upper = float(bound.upper)
        if value > upper + EPSILON or (bound.strict and value >= upper - EPSILON):
            return False
    if bound.lower is not None:
        lower = float(bound.lower)
        if value < lower - EPSILON or (bound.strict and value <= lower + EPSILON):
            return False
    return True


def warned(rule: Rule, value: float) -> bool:
    if rule.warn_at is None:
        return False
    level = float(rule.warn_at)
    return value >= level - EPSILON if rule.bound.upper is not None else value <= level + EPSILON


def evaluate(rule: Rule, snapshot: Snapshot) -> RuleResult:
    value, contributors, group = measure(rule, snapshot)
    if value is None:
        return RuleResult(rule, None, "not evaluable", None, None)
    if not within(rule, value):
        status = "breach"
    elif warned(rule, value):
        status = "warning"
    else:
        status = "pass"
    return RuleResult(rule, value, status, utilisation(rule, value), headroom(rule, value), contributors, group)


def check(mandate: Mandate, snapshot: Snapshot) -> ComplianceReport:
    return ComplianceReport(snapshot.day, mandate, tuple(evaluate(rule, snapshot) for rule in mandate.rules))
