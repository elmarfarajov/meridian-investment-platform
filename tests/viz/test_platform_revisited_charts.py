"""The Day 9 revisit charts draw, from the measurements kept with their method."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian import platform_revisited_gallery as gallery


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def test_the_measurements_show_each_promise_broken_before_and_kept_after():
    before, after = gallery.rates("day9"), gallery.rates("revisited")
    assert all(rate > 0.1 for rate in before) and all(rate == 0 for rate in after)
    times = gallery.measured()["sign_in_ms"]
    assert gallery.median(times["day9"]["real user, wrong password"]) > 10 * gallery.median(
        times["day9"]["no such user"]
    )
    revisited = [gallery.median(values) for values in times["revisited"].values()]
    assert max(revisited) < 1.3 * min(revisited)  # indistinguishable: within the noise of one hash
    assert "PostgreSQL" in gallery.measured()["how"]


@pytest.mark.parametrize("item", gallery.platform_revisited_items(), ids=lambda item: item.filename)
def test_every_chart_draws(item):
    assert item.builder().axes
