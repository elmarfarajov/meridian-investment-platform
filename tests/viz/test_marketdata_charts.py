"""Every Day 2 chart builds from the demonstration market and says what it claims to."""

from __future__ import annotations

from datetime import date

import matplotlib.pyplot as plt
import numpy as np
import pytest

from meridian.gallery import gallery_items, market_data_items
from meridian.marketdata.fx_history import FxHistory
from meridian.quality.robust import rolling_classical_z, rolling_robust_z
from meridian.services import build_demo_market, demo_quality_report
from meridian.viz import (
    demo_lots,
    plot_coverage_calendar,
    plot_fx_triangle,
    plot_lot_adjustments,
    plot_quality_dashboard,
    plot_robust_vs_classical,
    x_of,
)


@pytest.fixture(scope="module")
def market():
    return build_demo_market()


@pytest.fixture(scope="module")
def report(market):
    return demo_quality_report(market)


def texts(figure) -> str:
    return " ".join(text.get_text() for text in figure.findobj(lambda item: hasattr(item, "get_text")))


def test_the_dashboard_has_three_panels_and_names_the_worst_series(report):
    figure = plot_quality_dashboard(report)
    assert len(figure.axes) == 3
    assert "US-MSFT" in texts(figure)
    plt.close(figure)


def test_the_robust_chart_tells_the_story_it_claims():
    figure = plot_robust_vs_classical()
    titles = [axis.get_title(loc="left") for axis in figure.axes]
    assert any("catches 3 of 3" in title for title in titles)
    assert any("Classical" in title and "catches 3 of 3" not in title for title in titles)
    plt.close(figure)


def test_masking_happens_in_the_numbers_not_just_the_picture():
    """The chart's own data: after the first bad tick, the classical score of the next two falls below 6."""
    rng = np.random.default_rng(21)
    returns = rng.standard_t(5, 220) * 0.0095
    for index, value in {120: 0.11, 128: -0.095, 137: 0.12}.items():
        returns[index] = value
    classical = rolling_classical_z(returns.tolist(), 60)
    robust = rolling_robust_z(returns.tolist(), 60)
    assert all(abs(robust[index]) >= 6 for index in (120, 128, 137))  # type: ignore[arg-type]
    assert abs(classical[120]) >= 6  # type: ignore[arg-type]
    assert all(abs(classical[index]) < 6 for index in (128, 137))  # type: ignore[arg-type]


def test_lot_chart_totals_are_conserved():
    figure = plot_lot_adjustments(*demo_lots())
    assert texts(figure).count("57,774") >= 4  # before and after, in both capital-event panels
    plt.close(figure)


def test_fx_chart_marks_the_planted_break(market, report):
    figure = plot_fx_triangle(report.fx_residuals, FxHistory.from_dataset(market.clean), date(2026, 9, 18))
    assert "+40 bp" in texts(figure)
    plt.close(figure)


def test_coverage_calendar_counts_the_missing_days(market, report):
    figure = plot_coverage_calendar(market.damaged, report, market.calendars, date(2026, 1, 5), date(2026, 4, 30))
    assert "Expected, missing (5)" in texts(figure)
    plt.close(figure)


def test_gallery_includes_every_day_two_chart():
    names = {item.filename for item in gallery_items()}
    assert {item.filename for item in market_data_items()} <= names
    assert len(names) == len(gallery_items())  # no two charts share a file
    assert len(names) >= 30 + len(market_data_items()) - 13  # Day 1 and Day 2 are all still there


def test_x_of_is_monotonic():
    assert x_of(date(2026, 1, 2)) - x_of(date(2026, 1, 1)) == pytest.approx(1.0)


@pytest.mark.slow
def test_every_market_data_chart_renders(tmp_path):
    for item in market_data_items():
        figure = item.builder()
        figure.savefig(tmp_path / item.filename, dpi=50)
        assert (tmp_path / item.filename).stat().st_size > 5_000, item.filename
        plt.close(figure)
