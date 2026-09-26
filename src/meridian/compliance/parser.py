"""From mandate text to rules, with Lark.

The grammar (``grammar.lark``, next to this module) is LALR(1): parsing is
linear in the length of the text and every syntax error is reported with its
line and column and what was expected there - which matters, because the
people who write mandates are compliance officers, not programmers.

Percentages are read exactly as ``Decimal`` (``9.5%`` is ``0.095``, never
``0.0949999...``): a limit is a contract term, and the comparison at the limit
must not depend on binary rounding.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import lru_cache
from importlib import resources

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedInput, VisitError

from ..core.exceptions import ValidationError
from .language import (
    GROUPABLE,
    And,
    Bound,
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


class MandateSyntaxError(ValidationError):
    """A mandate that does not parse, with where and why."""

    def __init__(self, message: str, line: int, column: int) -> None:
        super().__init__(f"line {line}, column {column}: {message}")
        self.line = line
        self.column = column


@lru_cache(maxsize=1)
def _parser() -> Lark:
    grammar = resources.files(__package__).joinpath("grammar.lark").read_text(encoding="utf-8")
    return Lark(grammar, parser="lalr", maybe_placeholders=False, propagate_positions=True)


def _number(token: Token) -> Decimal:
    text = str(token)
    if text.endswith("%"):
        return Decimal(text[:-1]) / 100
    return Decimal(text)


class _Builder(Transformer):
    """Turns the parse tree into :mod:`.language` objects."""

    # ---- terminals
    def STRING(self, token: Token) -> str:
        return str(token)[1:-1]

    def PERCENT(self, token: Token) -> Decimal:
        return _number(token)

    def DECIMAL_NUMBER(self, token: Token) -> Decimal:
        return _number(token)

    def FIELD(self, token: Token) -> str:
        return str(token)

    # ---- conditions
    @v_args(inline=True)
    def comparator(self, token: Token) -> str:
        return str(token)

    @v_args(inline=True)
    def comparison(self, field: str, operator: str, value: Literal) -> Comparison:
        return Comparison(field, operator, value)

    def membership(self, items: list[object]) -> Membership:
        field = str(items[0])
        negated = len(items) > 1 and isinstance(items[1], Token) and items[1].type == "NOT"
        values = tuple(item for item in items[2 if negated else 1 :] if isinstance(item, str | Decimal))
        return Membership(field, values, negated)

    def conjunction(self, parts: list[Condition]) -> Condition:
        return And(tuple(parts))

    def disjunction(self, parts: list[Condition]) -> Condition:
        return Or(tuple(parts))

    @v_args(inline=True)
    def filter(self, condition: Condition) -> Condition:
        return condition

    def lookthrough(self, _: list[object]) -> bool:
        return True

    # ---- measures
    @staticmethod
    def _options(items: list[object]) -> tuple[bool, Condition | None]:
        look = any(item is True for item in items)
        conditions = [item for item in items if item is not True]
        return look, (conditions[0] if conditions else None)  # type: ignore[return-value]

    def weight_measure(self, items: list[object]) -> WeightOf:
        look, condition = self._options(items)
        return WeightOf(condition, look)

    @staticmethod
    def _groupable(field: object) -> str:
        if str(field) not in GROUPABLE:
            raise ValidationError(f"cannot group by {field}; group by one of {', '.join(GROUPABLE)}")
        return str(field)

    def group_measure(self, items: list[object]) -> MaxGroupWeight:
        look, condition = self._options(items[1:])
        return MaxGroupWeight(self._groupable(items[0]), condition, look)

    def concentration_measure(self, items: list[object]) -> ConcentrationSum:
        look, condition = self._options(items[2:])
        return ConcentrationSum(self._groupable(items[0]), items[1], condition, look)  # type: ignore[arg-type]

    def count_measure(self, items: list[object]) -> CountOf:
        look, condition = self._options(items)
        return CountOf(condition, look)

    def absence_measure(self, items: list[object]) -> NoHoldings:
        look, condition = self._options(items)
        assert condition is not None
        return NoHoldings(condition, look)

    @v_args(inline=True)
    def metric_measure(self, token: Token) -> Metric:
        return Metric(str(token))

    # ---- bounds
    @v_args(inline=True)
    def upper(self, operator: Token, value: Decimal) -> Bound:
        return Bound(upper=value, strict=str(operator) == "<")

    @v_args(inline=True)
    def lower(self, operator: Token, value: Decimal) -> Bound:
        return Bound(lower=value, strict=str(operator) == ">")

    @v_args(inline=True)
    def exact(self, _: Token, value: Decimal) -> Bound:
        return Bound(lower=value, upper=value, exact=True)

    @v_args(inline=True)
    def range(self, low: Decimal, high: Decimal) -> Bound:
        return Bound(lower=low, upper=high)

    @v_args(inline=True)
    def warning(self, value: Decimal) -> tuple[str, Decimal]:
        return ("warn", value)

    # ---- rules
    def rule(self, items: list[object]) -> Rule:
        identifier = str(items[0])
        position = 1
        title = None
        if isinstance(items[position], str) and not isinstance(items[position], Token):
            title = items[position]
            position += 1
        severity = str(items[position]).lower()
        measure = items[position + 1]
        rest = items[position + 2 :]
        bound = next((item for item in rest if isinstance(item, Bound)), None)
        warn = next((item[1] for item in rest if isinstance(item, tuple)), None)
        if isinstance(measure, NoHoldings):
            if bound is not None:
                raise ValidationError(f"{identifier}: 'no holdings' takes no bound")
            bound = Bound(upper=Decimal(0))
        if bound is None:
            raise ValidationError(f"{identifier}: a limit is required")
        return Rule(identifier, measure, bound, severity, title, warn)  # type: ignore[arg-type]

    @v_args(inline=True)
    def header(self, name: str, version: Token, effective: Token) -> tuple[str, int, date]:
        return name, int(version), date.fromisoformat(str(effective))

    def start(self, items: list[object]) -> Mandate:
        header = items[0]
        assert isinstance(header, tuple)
        name, version, effective = header
        rules = tuple(item for item in items[1:] if isinstance(item, Rule))
        return Mandate(str(name), int(version), effective, rules)


def parse_mandate(text: str) -> Mandate:
    """Parse a whole mandate; syntax errors carry their line and column."""
    try:
        tree = _parser().parse(text)
    except UnexpectedInput as error:
        expected = sorted(getattr(error, "expected", set()) or getattr(error, "allowed", set()))
        hint = f"; expected one of {', '.join(expected[:8])}" if expected else ""
        found = error.get_context(text, span=30).strip().splitlines()[0] if text else ""
        raise MandateSyntaxError(f"cannot read '{found}'{hint}", error.line, error.column) from None
    try:
        mandate: Mandate = _Builder().transform(tree)
    except VisitError as error:
        raise error.orig_exc from None
    return mandate


def parse_rule(text: str) -> Rule:
    """Parse one rule on its own (wrapped in a throwaway header)."""
    mandate = parse_mandate('mandate "rule" version 1 effective 2000-01-01\n' + text)
    if len(mandate.rules) != 1:
        raise ValidationError("expected exactly one rule")
    return mandate.rules[0]
