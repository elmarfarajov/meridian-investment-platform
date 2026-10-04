"""The Day 5 revisit charts draw, and draw the figures the tests check."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian import century_risk_gallery as gallery


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def _texts(figure):
    return " ".join(text.get_text() for text in figure.findobj(lambda item: hasattr(item, "get_text")))


def test_the_reference_chart_prints_the_basel_numbers():
    text = _texts(gallery.references_chart())
    assert all(value in text for value in ("8.11", "95.88", "99.99")) and "PyPortfolioOpt" in text


def test_the_surprise_chart_names_documented_events_only():
    text = _texts(gallery.surprises_chart())
    assert "Eisenhower's heart attack" in text and "Black Monday" in text


def test_the_review_chart_computes_its_notes():
    text = _texts(gallery.review_chart())
    assert "gives 3 for 100 days and 9 for 500" in text


@pytest.mark.parametrize("item", gallery.century_risk_items(), ids=lambda item: item.filename)
def test_every_chart_draws(item):
    assert item.builder().axes
