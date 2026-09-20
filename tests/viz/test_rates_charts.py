"""The rate, cash flow and schema charts build, and say what they claim to say."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import matplotlib.pyplot as plt
import pytest

from meridian.core.enums import Frequency
from meridian.core.money import Money
from meridian.core.schedules import StubConvention, generate_schedule
from meridian.gallery import reference_bond, reference_curve
from meridian.viz import (
    PALETTE,
    plot_accrual_path,
    plot_allocation,
    plot_cash_flows,
    plot_compounding,
    plot_curve_scenarios,
    plot_daycount_comparison,
    plot_divergence_matrix,
    plot_flow_composition,
    plot_interpolation_comparison,
    plot_key_rate_durations,
    plot_price_yield,
    plot_rounding_drift,
    plot_schedule,
    plot_schema,
    plot_settlement_ladder,
    save_figure,
)

SETTLEMENT = date(2026, 9, 21)


@pytest.fixture(scope="module")
def curve():
    return reference_curve()


@pytest.fixture(scope="module")
def bond():
    return reference_bond()


def _close(figure):
    plt.close(figure)


def test_the_yield_curve_chart_has_a_panel_for_rates_and_one_for_factors(curve):
    from meridian.viz import plot_yield_curve

    figure = plot_yield_curve(curve)
    try:
        titles = [axis.get_title(loc="left") for axis in figure.axes]
        assert "The curve, three ways" in titles
        assert "Discount factors" in titles
    finally:
        _close(figure)


def test_the_interpolation_chart_draws_three_methods_twice(curve):
    figure = plot_interpolation_comparison(curve)
    try:
        assert len(figure.axes) == 2
        assert len(figure.axes[1].lines) == 3  # one forward curve per method
    finally:
        _close(figure)


def test_the_price_yield_chart_shows_the_actual_and_both_estimates(bond):
    figure = plot_price_yield(bond, SETTLEMENT)
    try:
        labels = [line.get_label() for line in figure.axes[0].lines]
        assert {"Actual price", "Duration only", "Duration + convexity"} <= set(labels)
    finally:
        _close(figure)


def test_the_key_rate_chart_has_one_bar_per_pillar(bond, curve):
    figure = plot_key_rate_durations(bond, curve, SETTLEMENT)
    try:
        assert len(figure.axes[0].patches) == len(curve.years)
    finally:
        _close(figure)


def test_the_scenario_and_compounding_charts_build(curve):
    for figure in (plot_curve_scenarios(curve), plot_compounding()):
        try:
            assert len(figure.axes) == 2
        finally:
            _close(figure)


def test_the_schedule_chart_marks_the_stub():
    schedule = generate_schedule(
        date(2025, 2, 10), date(2028, 5, 15), Frequency.SEMI_ANNUAL, stub=StubConvention.SHORT_FRONT
    )
    figure = plot_schedule(schedule)
    try:
        # one bar per period, plus the patches used for the legend
        assert len(figure.axes[0].patches) >= len(schedule)
    finally:
        _close(figure)


def test_the_cash_flow_charts_build(bond, curve):
    for figure in (
        plot_cash_flows(bond, SETTLEMENT, curve),
        plot_cash_flows(bond, SETTLEMENT),
        plot_flow_composition(bond, SETTLEMENT, curve),
        plot_accrual_path(bond, date(2026, 1, 1), date(2028, 1, 1)),
    ):
        try:
            assert figure.axes
        finally:
            _close(figure)


def test_the_money_charts_build():
    for figure in (
        plot_allocation(Money(Decimal("1000.00"), "USD")),
        plot_daycount_comparison(date(2026, 1, 15), date(2026, 7, 15)),
        plot_rounding_drift(Money(Decimal("2500.00"), "USD"), periods=40),
    ):
        try:
            assert figure.axes
        finally:
            _close(figure)


def test_the_calendar_matrix_is_square_and_symmetric():
    from meridian.viz import divergence_matrix

    matrix = divergence_matrix(("XNYS", "XLON", "TARGET"), 2026)
    assert matrix.shape == (3, 3)
    assert (matrix == matrix.T).all()
    assert (matrix.diagonal() == 0).all()
    figure = plot_divergence_matrix(2026, ("XNYS", "XLON", "TARGET"))
    try:
        assert figure.axes
    finally:
        _close(figure)


def test_the_settlement_ladder_has_a_row_per_market_plus_the_joint_one():
    figure = plot_settlement_ladder(date(2026, 12, 23), ("XNYS", "XLON"))
    try:
        labels = [label.get_text() for label in figure.axes[0].get_yticklabels()]
        assert labels[:2] == ["XNYS", "XLON"]
        assert labels[-1] == "All (XNYS+XLON)"
    finally:
        _close(figure)


def test_the_schema_diagram_draws_every_table():
    from meridian.persistence.base import Base

    figure = plot_schema()
    try:
        texts = {text.get_text() for text in figure.axes[0].texts}
        for table in Base.metadata.sorted_tables:
            assert table.name in texts
    finally:
        _close(figure)


def test_charts_write_png_files(tmp_path, curve):
    from meridian.viz import plot_yield_curve

    path = save_figure(plot_yield_curve(curve), tmp_path / "curve.png", dpi=70)
    assert path.stat().st_size > 5_000


def test_the_accent_colour_is_used_for_annotation_only(bond):
    """The house rule, enforced: amber may highlight a number, never fill a series."""
    figure = plot_price_yield(bond, SETTLEMENT)
    try:
        for axis in figure.axes:
            for line in axis.lines:
                assert line.get_color() != PALETTE["accent"]
            for patch in axis.patches:
                assert patch.get_facecolor() != PALETTE["accent"]
    finally:
        _close(figure)
