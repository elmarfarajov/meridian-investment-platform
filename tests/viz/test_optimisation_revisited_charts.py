"""The Day 7 revisit charts draw, and the comparison with Day 7's ledger shows what changed."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian import optimisation_revisited_gallery as gallery


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def test_day7_carried_publication_550s_losses_in_the_wrong_order():
    assert gallery.day7_carryover(-2_000.0, -5_000.0)[:2] == pytest.approx((2_000.0, 2_000.0))
    assert gallery.revisited_carryover(-2_000.0, -5_000.0)[:2] == pytest.approx((0.0, 4_000.0))
    assert gallery.day7_carryover(1_000.0, -9_000.0)[:2] == pytest.approx((5_000.0, 0.0))  # long-term called short
    assert gallery.revisited_carryover(1_000.0, -9_000.0)[:2] == pytest.approx((0.0, 5_000.0))


@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
@pytest.mark.parametrize("item", gallery.optimisation_revisited_items(), ids=lambda item: item.filename)
def test_every_chart_draws(item):
    assert item.builder().axes
