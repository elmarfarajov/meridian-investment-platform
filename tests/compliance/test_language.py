"""The mandate language: parsing, printing, and errors a compliance officer can act on."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.compliance.language import (
    GROUPABLE,
    And,
    Bound,
    Comparison,
    ConcentrationSum,
    CountOf,
    Mandate,
    MaxGroupWeight,
    Membership,
    Metric,
    NoHoldings,
    Or,
    Rule,
    WeightOf,
    mandate_text,
    to_text,
)
from meridian.compliance.parser import MandateSyntaxError, parse_mandate, parse_rule
from meridian.core import ValidationError
from meridian.services.demo_compliance import load_mandate, mandate_source


def test_a_rule_reads_as_it_is_written():
    rule = parse_rule(
        'rule issuer_limit "Single issuer" hard\n  max weight by issuer with look-through <= 10% warn at 9%'
    )
    assert rule == Rule(
        "issuer_limit",
        MaxGroupWeight("issuer", None, True),
        Bound(upper=Decimal("0.1")),
        "hard",
        "Single issuer",
        Decimal("0.09"),
    )
    assert parse_rule('RULE x SOFT WEIGHT WHERE sector = "Energy" <= 5%').severity == "soft"  # keywords ignore case


def test_every_measure_and_bound():
    cases = {
        'rule a hard weight where asset_class = "cash" between 1% and 10%': (
            WeightOf,
            Bound(Decimal("0.01"), Decimal("0.1")),
        ),
        "rule b hard sum weight by issuer above 5% <= 40%": (ConcentrationSum, Bound(upper=Decimal("0.4"))),
        'rule c hard count where asset_class = "equity" >= 20': (CountOf, Bound(lower=Decimal(20))),
        'rule d hard no holdings where rating < "BBB-"': (NoHoldings, Bound(upper=Decimal(0))),
        "rule e soft tracking_error < 6%": (Metric, Bound(upper=Decimal("0.06"), strict=True)),
        "rule f soft beta = 1": (Metric, Bound(Decimal(1), Decimal(1), exact=True)),
    }
    for text, (kind, bound) in cases.items():
        rule = parse_rule(text)
        assert isinstance(rule.measure, kind) and rule.bound == bound, text


def test_conditions_nest_with_and_binding_tighter_than_or():
    rule = parse_rule('rule x hard weight where sector = "A" or sector = "B" and country = "US" <= 5%')
    assert isinstance(rule.measure, WeightOf)
    condition = rule.measure.filter
    assert isinstance(condition, Or) and isinstance(condition.parts[1], And)
    rule = parse_rule('rule y hard weight where country not in ("US", "CA") <= 30%')
    assert rule.measure.filter == Membership("country", ("US", "CA"), negated=True)  # type: ignore[union-attr]


def test_errors_say_where_and_what():
    with pytest.raises(MandateSyntaxError, match="line 2") as caught:
        parse_rule("rule x hard max weight by colour <= 10%")
    assert caught.value.line == 2
    for text, message in (
        ("rule w hard weight <= 5% warn at 6%", "before the limit"),
        ("rule q hard weight between 5% and 1%", "empty"),
        ('rule m hard weight where sector = "x"', "limit is required"),
        ('rule z hard no holdings where sector = "x" <= 5%', "takes no bound"),
        ("rule g hard max weight by weight <= 5%", "cannot group by"),
        ("rule b soft beta between 0.8 and 1.2 warn at 1", "one-sided"),
    ):
        with pytest.raises(ValidationError, match=message):
            parse_rule(text)
    with pytest.raises(ValidationError, match="unique"):
        parse_mandate('mandate "m" version 1 effective 2024-01-01\nrule a hard weight <= 1%\nrule a hard weight <= 2%')


def test_the_demonstration_mandates_parse_and_print_back():
    mandate = load_mandate()
    assert mandate.name == "Global Equity Core" and mandate.version == 3 and len(mandate.rules) == 18
    assert mandate.effective == date(2024, 4, 4)
    assert parse_mandate(mandate_text(mandate)) == mandate
    assert "look-through" in mandate_source()
    ucits = load_mandate("ucits_screen.mandate")
    assert {rule.rule_id for rule in ucits.rules} == {"issuer_10", "five_ten_forty", "government_35", "fund_20"}


# ---------------------------------------------------------------------------- the round trip, generated
percent = st.integers(min_value=0, max_value=1000).map(lambda value: Decimal(value) / 1000)
names = st.sampled_from(["Energy", "US", "EUR", "Tobacco", "AA+", "equity", "fund"])
field = st.sampled_from(["sector", "industry", "country", "currency", "asset_class", "issuer"])


@st.composite
def conditions(draw, depth: int = 0):  # type: ignore[no-untyped-def]
    choice = draw(st.integers(0, 3 if depth < 2 else 1))
    if choice == 0:
        return Comparison(draw(field), draw(st.sampled_from(["=", "!="])), draw(names))
    if choice == 1:
        values = tuple(draw(st.lists(names, min_size=1, max_size=3)))
        return Membership(draw(field), values, draw(st.booleans()))
    parts = tuple(draw(st.lists(conditions(depth + 1), min_size=2, max_size=3)))
    parts = tuple(part for part in parts if not isinstance(part, And if choice == 2 else Or))
    if len(parts) < 2:
        return Comparison("sector", "=", "Energy")
    return And(parts) if choice == 2 else Or(parts)


@st.composite
def rules(draw):  # type: ignore[no-untyped-def]
    look = draw(st.booleans())
    condition = draw(st.none() | conditions())
    kind = draw(st.integers(0, 4))
    if kind == 0:
        measure = WeightOf(condition, look)
    elif kind == 1:
        measure = MaxGroupWeight(draw(st.sampled_from(GROUPABLE)), condition, look)
    elif kind == 2:
        measure = ConcentrationSum(draw(st.sampled_from(GROUPABLE)), draw(percent), condition, look)
    elif kind == 3:
        return Rule(
            "r", NoHoldings(draw(conditions()), look), Bound(upper=Decimal(0)), draw(st.sampled_from(["hard", "soft"]))
        )
    else:
        measure = Metric(draw(st.sampled_from(["tracking_error", "volatility", "active_share"])))
    low, high = sorted((draw(percent), draw(percent)))
    shape = draw(st.integers(0, 2))
    bound = Bound(upper=high) if shape == 0 else Bound(lower=low) if shape == 1 else Bound(low, high)
    title = draw(st.none() | st.sampled_from(["Single issuer", "Cash band"]))
    return Rule("r", measure, bound, draw(st.sampled_from(["hard", "soft"])), title)


@settings(max_examples=400, deadline=None)
@given(rules())
def test_printing_and_parsing_are_inverses(rule):
    assert parse_rule(to_text(rule)) == rule


def test_a_mandate_round_trips_with_every_rule():
    mandate = Mandate("m", 2, date(2025, 1, 1), (parse_rule("rule a soft weight <= 5% warn at 4.5%"),))
    assert parse_mandate(mandate_text(mandate)) == mandate
