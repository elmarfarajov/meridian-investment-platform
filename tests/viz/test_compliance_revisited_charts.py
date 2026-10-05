"""The Day 6 revisit charts draw, and draw the figures the tests check."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian import compliance_revisited_gallery as gallery


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def test_the_old_rule_let_unsafe_orders_through_and_the_new_one_none():
    counts = gallery.guarantee_counts()
    old, new = counts["any"]
    assert old > 200 and new == 0
    assert all(new == 0 for _, new in counts.values())
    assert counts["tobacco"][0] > 0 and counts["cash"][0] > 0  # the infinite-utilisation blind spots, both seen


@pytest.mark.parametrize("item", gallery.compliance_revisited_items(), ids=lambda item: item.filename)
def test_every_chart_draws(item):
    assert item.builder().axes
