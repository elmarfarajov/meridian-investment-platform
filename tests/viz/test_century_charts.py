"""The Day 4 revisit charts draw, and draw the figures the tests check."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian import century_gallery as gallery


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def _texts(figure):
    return " ".join(text.get_text() for text in figure.findobj(lambda item: hasattr(item, "get_text")))


def test_the_rebuilt_market_chart_states_the_fit():
    text = _texts(gallery.rebuilt_chart())
    assert "correlation 0.9997" in text and "March 2000" in text


def test_the_drawdown_chart_names_the_depression():
    text = _texts(gallery.drawdown_chart())
    assert "-83.7%" in text and "Aug 1929 to Jun 1932" in text


def test_the_linking_chart_names_every_method():
    text = _texts(gallery.linking_chart())
    assert all(name in text for name in ("Cariño", "Menchero", "GRAP", "Frongello"))


def test_the_old_xirr_basis_overstated_microsoft_s_example():
    assert gallery._xirr_at(365.25) > gallery._xirr_at(365.0)
    assert gallery._xirr_at(365.0) == pytest.approx(0.373362535, abs=2e-9)


@pytest.mark.parametrize("item", gallery.century_items(), ids=lambda item: item.filename)
def test_every_chart_draws(item):
    assert item.builder().axes
