"""The Day 8 revisit charts draw, and the POV comparison shows what changed."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pytest

from meridian import execution_revisited_gallery as gallery


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def test_day8s_pov_took_a_tenth_of_the_rest_and_the_revisited_one_a_tenth_of_all():
    assert float(np.nanmean(gallery.pov_participation(True))) == pytest.approx(0.1 / 1.1, abs=0.001)
    assert float(np.nanmean(gallery.pov_participation(False))) == pytest.approx(0.10, abs=0.001)


@pytest.mark.parametrize("item", gallery.execution_revisited_items(), ids=lambda item: item.filename)
def test_every_chart_draws(item):
    assert item.builder().axes
