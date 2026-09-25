"""The Day 5 charts: each draws from the risk model applied to the demonstration account."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pytest

from meridian import risk_gallery
from meridian.gallery import gallery_items
from meridian.services.demo_risk import build_demo_risk


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


def titles(figure) -> list[str]:
    return [axis.get_title(loc="left") or axis.get_title() for axis in figure.axes]


@pytest.mark.parametrize(
    ("builder", "panels", "phrase"),
    [
        (risk_gallery.decomposition_chart, 2, "tracking error"),
        (risk_gallery.bias_chart, 2, "Bias statistic"),
        (risk_gallery.eigen_chart, 2, "sample correlation"),
        (risk_gallery.factor_returns_chart, 12, "Style factors"),
        (risk_gallery.volatility_chart, 2, "forecast one day ahead"),
        (risk_gallery.correlation_chart, 2, "Correlations of the factors"),
        (risk_gallery.exposures_chart, 3, "Styles"),
        (risk_gallery.contributions_chart, 2, "Contribution to volatility"),
        (risk_gallery.var_backtest_chart, 2, "Basel traffic light"),
        (risk_gallery.var_methods_chart, 2, "1% tail"),
        (risk_gallery.stress_chart, 2, "Portfolio less benchmark"),
        (risk_gallery.book_bias_chart, 2, "account's own forecasts"),
        (risk_gallery.specific_chart, 2, "size decile"),
        (risk_gallery.regression_chart, 2, "R-squared"),
        (risk_gallery.report_chart, 5, "Stress tests"),
    ],
)
def test_each_chart_has_its_panels_and_says_what_it_shows(builder, panels, phrase):
    figure = builder()
    assert len([axis for axis in figure.axes if axis.get_visible()]) >= panels
    assert any(phrase in title for title in titles(figure)), titles(figure)
    assert figure.texts, "every chart carries a title block"


def test_the_minimum_variance_chart_shows_every_estimator():
    figure = risk_gallery.minimum_variance_chart()
    labels = {text.get_text() for text in figure.axes[0].get_legend().get_texts()}
    assert {"Sample", "Factor model"} <= labels


def test_chart_data_agrees_with_the_model():
    risk = build_demo_risk()
    groups, totals = risk_gallery.group_table(risk)
    assert sum(groups["Active"].values()) == pytest.approx(totals["Active"])
    errors = risk_gallery.volatility_errors(risk)
    assert errors["GARCH(1,1)"] < errors["Equal-weighted 252 days"]
    labels, _, _, spread_shrunk, spread_raw = risk_gallery.specific_calibration(risk)
    assert len(labels) == 10 and np.mean(spread_raw) < np.mean(spread_shrunk)  # the shrinkage verdict
    headline = dict(risk_gallery.headline(risk))
    assert headline["Tracking error"].endswith("%") and "/" in headline["VaR exceptions"]
    rows = risk_gallery.contribution_rows(risk.portfolio, 5)
    assert len(rows) == 5 and abs(rows[0][3]) >= abs(rows[-1][3])


def test_the_risk_group_is_in_the_gallery():
    names = {item.filename for item in gallery_items() if item.group == "risk"}
    assert len(names) == 16 and "risk-report.png" in names
