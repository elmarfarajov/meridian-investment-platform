"""Four linking methods: each exact, each distributing the compounded active return its own way."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.core.exceptions import ValidationError
from meridian.performance.linking import METHODS, carino_factor, compound, link_lines, multipliers

rate = st.floats(min_value=-0.2, max_value=0.25, allow_nan=False)


@settings(max_examples=200, deadline=None)
@given(
    periods=st.lists(st.tuples(rate, rate, st.floats(min_value=0.0, max_value=1.0)), min_size=1, max_size=40),
    method=st.sampled_from(METHODS),
)
def test_every_method_links_exactly_to_the_compounded_active_return(periods, method):
    portfolio = [p for p, _, _ in periods]
    benchmark = [b for _, b, _ in periods]
    # two effect lines per period that sum to its active return, split by the third draw
    lines = {
        "allocation": [(p - b) * share for p, b, share in periods],
        "selection": [(p - b) * (1 - share) for p, b, share in periods],
    }
    linked = link_lines(lines, portfolio, benchmark, method)
    assert sum(linked.values()) == pytest.approx(compound(portfolio) - compound(benchmark), abs=1e-12)


def test_one_period_needs_no_linking():
    for method in METHODS:
        linked = link_lines({"a": [0.03], "b": [0.01]}, [0.05], [0.01], method)
        assert linked["a"] == pytest.approx(0.03) and linked["b"] == pytest.approx(0.01)


def test_the_methods_agree_on_the_total_and_differ_on_the_split():
    portfolio, benchmark = [0.10, -0.05, 0.08], [0.02, 0.03, 0.01]
    # allocation earns all of the first period's active return, selection all of the others'
    lines = {"allocation": [0.08, 0.0, 0.0], "selection": [0.0, -0.08, 0.07]}
    results = {method: link_lines(lines, portfolio, benchmark, method) for method in METHODS}
    target = compound(portfolio) - compound(benchmark)
    assert all(sum(found.values()) == pytest.approx(target) for found in results.values())
    allocations = sorted(found["allocation"] for found in results.values())
    assert allocations[-1] - allocations[0] > 5e-4  # the split is a choice: here the choices span 7 bp


def test_grap_carries_an_early_effect_with_the_portfolio_and_a_late_one_with_nothing():
    portfolio, benchmark = [0.10, 0.20], [0.0, 0.0]
    factors = multipliers(portfolio, benchmark, "grap")
    assert factors == pytest.approx([1.0, 1.10])  # period 2's effect is carried by period 1's growth


def test_frongello_unrolls_to_grap_effect_by_effect():
    portfolio, benchmark = [0.10, 0.05, -0.03], [0.04, 0.06, 0.01]
    lines = {"x": [0.06, 0.0, -0.01], "y": [0.0, -0.01, -0.03]}
    grap = link_lines(lines, portfolio, benchmark, "grap")
    frongello = link_lines(lines, portfolio, benchmark, "frongello")
    assert grap == pytest.approx(frongello)
    # x's first-period effect is carried by the benchmark's growth after it
    assert grap["x"] == pytest.approx(0.06 * 1.06 * 1.01 - 0.01 * 1.10 * 1.05)


def test_menchero_is_one_constant_when_active_returns_are_equal():
    portfolio, benchmark = [0.05, 0.05, 0.05], [0.02, 0.02, 0.02]
    factors = multipliers(portfolio, benchmark, "menchero")
    assert max(factors) - min(factors) < 1e-12
    assert sum(f * 0.03 for f in factors) == pytest.approx(compound(portfolio) - compound(benchmark))


def test_carino_factor_and_its_limit():
    assert carino_factor(0.1, 0.1) == pytest.approx(1 / 1.1)
    assert carino_factor(0.1, 0.05) == pytest.approx((math.log(1.1) - math.log(1.05)) / 0.05)


def test_bad_inputs_are_refused():
    with pytest.raises(ValidationError, match="unknown linking method"):
        link_lines({"a": [0.1]}, [0.1], [0.0], "linear")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="one portfolio and one benchmark"):
        link_lines({"a": [0.1]}, [0.1], [], "carino")
    with pytest.raises(ValidationError, match="has 2 values for 1"):
        link_lines({"a": [0.1, 0.2]}, [0.1], [0.0], "carino")
    with pytest.raises(ValidationError, match="does not link by a factor"):
        multipliers([0.1], [0.0], "frongello")
