"""The mandate language: what a rule *is*, independent of the text it was written in.

An investment management agreement says things like "no more than 10% of the
fund in any one issuer" or "only investment-grade bonds". Written in prose,
those sentences are checked by people, differently by different people. The
mandate language makes each one a small, exact program:

    rule issuer_limit "Single issuer" hard
        max weight by issuer with look-through <= 10% warn at 9%

The parser (:mod:`.parser`) turns text into the objects defined here, and
:func:`to_text` turns them back. The two are inverses - a property test
generates thousands of random rules and requires ``parse(to_text(rule)) == rule``
- so a rule stored in the database as text is the same rule that was checked.

A rule is a **measure** (what to compute on the portfolio), a **bound** (the
limit), a **severity** (a hard limit blocks a trade; a soft one needs an
override) and optionally a **warning level**, the early-warning line
compliance officers watch before the limit itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.exceptions import ValidationError

#: Fields a filter or a grouping can refer to.
FIELDS: tuple[str, ...] = (
    "asset_class",
    "sector",
    "industry",
    "issuer",
    "country",
    "currency",
    "rating",
    "instrument",
    "days_to_liquidate",
    "weight",
)
#: Portfolio-level measures supplied by the risk model and the benchmark.
METRICS: tuple[str, ...] = ("tracking_error", "volatility", "var_99", "beta", "active_share")
GROUPABLE: tuple[str, ...] = ("sector", "industry", "issuer", "country", "currency", "instrument", "asset_class")

Literal = str | Decimal


# ---------------------------------------------------------------------------- conditions
@dataclass(frozen=True)
class Comparison:
    field: str
    operator: str  # = != < <= > >=
    value: Literal


@dataclass(frozen=True)
class Membership:
    field: str
    values: tuple[Literal, ...]
    negated: bool = False


@dataclass(frozen=True)
class And:
    parts: tuple[Condition, ...]


@dataclass(frozen=True)
class Or:
    parts: tuple[Condition, ...]


Condition = Comparison | Membership | And | Or


# ---------------------------------------------------------------------------- measures
@dataclass(frozen=True)
class WeightOf:
    """The total weight of the holdings the filter selects (all holdings if none)."""

    filter: Condition | None = None
    look_through: bool = False


@dataclass(frozen=True)
class MaxGroupWeight:
    """The weight of the heaviest group - issuer, sector, country - among the selected holdings."""

    group_by: str
    filter: Condition | None = None
    look_through: bool = False


@dataclass(frozen=True)
class ConcentrationSum:
    """The combined weight of the groups each weighing more than ``threshold`` (UCITS 5/10/40)."""

    group_by: str
    threshold: Decimal
    filter: Condition | None = None
    look_through: bool = False


@dataclass(frozen=True)
class CountOf:
    """The number of holdings the filter selects."""

    filter: Condition | None = None
    look_through: bool = False


@dataclass(frozen=True)
class NoHoldings:
    """None of the selected holdings may be held: the measure is their weight, the limit zero."""

    filter: Condition
    look_through: bool = False


@dataclass(frozen=True)
class Metric:
    """A portfolio-level number from the risk model or the benchmark comparison."""

    name: str


Measure = WeightOf | MaxGroupWeight | ConcentrationSum | CountOf | NoHoldings | Metric


# ---------------------------------------------------------------------------- bounds
@dataclass(frozen=True)
class Bound:
    """``lower <= value <= upper``; either side may be open. ``strict`` makes a side exclusive."""

    lower: Decimal | None = None
    upper: Decimal | None = None
    strict: bool = False
    exact: bool = False

    def __post_init__(self) -> None:
        if self.lower is None and self.upper is None:
            raise ValidationError("a bound needs at least one side")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValidationError(f"the bound {self.lower} to {self.upper} is empty")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    measure: Measure
    bound: Bound
    severity: str = "hard"  # hard | soft
    title: str | None = None
    warn_at: Decimal | None = None

    def __post_init__(self) -> None:
        if self.severity not in ("hard", "soft"):
            raise ValidationError(f"{self.rule_id}: severity must be hard or soft")
        if isinstance(self.measure, NoHoldings) and (self.bound.upper != 0 or self.bound.lower is not None):
            raise ValidationError(f"{self.rule_id}: 'no holdings' is bounded by zero")
        if self.warn_at is not None:
            if self.bound.lower is not None and self.bound.upper is not None:
                raise ValidationError(f"{self.rule_id}: a warning level needs a one-sided bound")
            limit = self.bound.upper if self.bound.upper is not None else self.bound.lower
            assert limit is not None
            wrong_side = self.warn_at > limit if self.bound.upper is not None else self.warn_at < limit
            if wrong_side:
                raise ValidationError(f"{self.rule_id}: the warning level must come before the limit")

    @property
    def name(self) -> str:
        return self.title or self.rule_id


@dataclass(frozen=True)
class Mandate:
    name: str
    version: int
    effective: date
    rules: tuple[Rule, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        identifiers = [rule.rule_id for rule in self.rules]
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            raise ValidationError(f"rule identifiers must be unique: {', '.join(duplicates)}")

    def rule(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise KeyError(rule_id)


# ---------------------------------------------------------------------------- back to text
def _number(value: Decimal, percent: bool) -> str:
    if percent:
        text = format((value * 100).normalize(), "f")
        return f"{text}%"
    return format(value.normalize(), "f")


def _literal(value: Literal, percent: bool = False) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    return _number(value, percent)


def _is_percent(field: str) -> bool:
    return field == "weight"


def condition_text(condition: Condition, *, nested: bool = False) -> str:
    if isinstance(condition, Comparison):
        return f"{condition.field} {condition.operator} {_literal(condition.value, _is_percent(condition.field))}"
    if isinstance(condition, Membership):
        values = ", ".join(_literal(value, _is_percent(condition.field)) for value in condition.values)
        return f"{condition.field} {'not in' if condition.negated else 'in'} ({values})"
    joiner = " and " if isinstance(condition, And) else " or "
    text = joiner.join(condition_text(part, nested=True) for part in condition.parts)
    return f"({text})" if nested else text


def _suffix(look_through: bool, filter: Condition | None) -> str:
    text = " with look-through" if look_through else ""
    if filter is not None:
        text += f" where {condition_text(filter)}"
    return text


def measure_text(measure: Measure) -> str:
    if isinstance(measure, WeightOf):
        return "weight" + _suffix(measure.look_through, measure.filter)
    if isinstance(measure, MaxGroupWeight):
        return f"max weight by {measure.group_by}" + _suffix(measure.look_through, measure.filter)
    if isinstance(measure, ConcentrationSum):
        return f"sum weight by {measure.group_by} above {_number(measure.threshold, True)}" + _suffix(
            measure.look_through, measure.filter
        )
    if isinstance(measure, CountOf):
        return "count" + _suffix(measure.look_through, measure.filter)
    if isinstance(measure, NoHoldings):
        return "no holdings" + _suffix(measure.look_through, measure.filter)
    return measure.name


def is_percentage(measure: Measure) -> bool:
    """Whether the measure's bound is naturally written as a percentage."""
    return not isinstance(measure, CountOf) and not (isinstance(measure, Metric) and measure.name == "beta")


def bound_text(rule: Rule) -> str:
    if isinstance(rule.measure, NoHoldings):
        return ""
    percent = is_percentage(rule.measure)
    bound = rule.bound
    if bound.exact:
        assert bound.upper is not None
        return f"= {_number(bound.upper, percent)}"
    if bound.lower is not None and bound.upper is not None:
        return f"between {_number(bound.lower, percent)} and {_number(bound.upper, percent)}"
    if bound.upper is not None:
        return f"{'<' if bound.strict else '<='} {_number(bound.upper, percent)}"
    assert bound.lower is not None
    return f"{'>' if bound.strict else '>='} {_number(bound.lower, percent)}"


def to_text(rule: Rule) -> str:
    """The rule as it would be written in a mandate file."""
    title = f' "{rule.title}"' if rule.title else ""
    body = measure_text(rule.measure)
    limit = bound_text(rule)
    text = f"rule {rule.rule_id}{title} {rule.severity}\n    {body}" + (f" {limit}" if limit else "")
    if rule.warn_at is not None:
        text += f" warn at {_number(rule.warn_at, is_percentage(rule.measure))}"
    return text


def mandate_text(mandate: Mandate) -> str:
    header = f'mandate "{mandate.name}" version {mandate.version} effective {mandate.effective.isoformat()}'
    return "\n\n".join([header, *(to_text(rule) for rule in mandate.rules)]) + "\n"
