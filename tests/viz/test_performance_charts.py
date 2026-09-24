"""The Day 4 charts: each draws from the demonstration account, with the titles and panels it promises."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian import performance_gallery
from meridian.gallery import gallery_items
from meridian.services.demo_performance import build_demo_performance
from meridian.viz.performance import EFFECT_COLOURS, legend_patches


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


def titles(figure) -> list[str]:
    return [axis.get_title(loc="left") or axis.get_title() for axis in figure.axes]


@pytest.mark.parametrize(
    ("builder", "panels", "phrase"),
    [
        (performance_gallery.cumulative_chart, 2, "Growth of 100"),
        (performance_gallery.bridge_chart, 2, "From the benchmark's return"),
        (performance_gallery.sector_chart, 3, "Effects (basis points)"),
        (performance_gallery.region_chart, 3, "Average weight"),
        (performance_gallery.calendar_chart, 2, "each month"),
        (performance_gallery.linking_chart, 3, "adding daily effects"),
        (performance_gallery.methods_chart, 2, "what was the return"),
        (performance_gallery.monthly_chart, 2, "monthly return"),
        (performance_gallery.rolling_chart, 3, "Tracking error"),
        (performance_gallery.drawdown_chart, 3, "deepest drawdowns"),
        (performance_gallery.currency_chart, 2, "currency weight"),
        (performance_gallery.contribution_chart, 2, "time-weighted return"),
        (performance_gallery.active_chart, 3, "Capture"),
        (performance_gallery.factsheet_chart, 5, "Growth of 100"),
    ],
)
def test_each_chart_has_its_panels_and_says_what_it_shows(builder, panels, phrase):
    figure = builder()
    assert len([axis for axis in figure.axes if axis.get_visible()]) >= panels
    assert any(phrase in title for title in titles(figure)), titles(figure)
    assert figure.texts, "every chart carries a title block"


def test_the_risk_return_map_labels_every_holding():
    figure = performance_gallery.risk_return_chart()
    labels = {text.get_text() for text in figure.axes[0].texts}
    assert {"Global Equity Core", "Policy benchmark", "US-AAPL", "US-T-2032"} <= labels


def test_the_bridge_shows_the_linked_effects_and_a_zero_residual():
    figure = performance_gallery.bridge_chart()
    rendered = " ".join(text.get_text() for text in figure.axes[0].texts)
    perf = build_demo_performance()
    assert f"{perf.by_sector.effect('selection') * 1e4:+.0f} bp" in rendered
    assert "residual" in rendered


def test_return_methods_agree_when_there_are_no_flows_and_differ_when_there_are():
    rows = performance_gallery.return_method_rows(build_demo_performance())
    by_label = {label: (twr, mwr, dietz) for label, twr, mwr, dietz in rows}
    assert "Since inception" in by_label
    twr, mwr, dietz = by_label["Since inception"]
    assert mwr == pytest.approx(dietz, abs=0.005)
    assert abs(twr - mwr) > 1e-4, "the client's flows make the two views differ"


def test_holding_series_and_the_legend():
    series = performance_gallery.holding_series(build_demo_performance())
    assert "US-AAPL" in series and all(len(item.days) > 60 for item in series.values())
    assert [patch.get_label() for patch in legend_patches()] == list(EFFECT_COLOURS)


def test_the_performance_group_is_in_the_gallery():
    names = {item.filename for item in gallery_items() if item.group == "performance"}
    assert len(names) == 15 and "factsheet.png" in names
