from __future__ import annotations

import matplotlib.pyplot as plt

from meridian.viz import PALETTE, SERIES, apply_house_style, new_figure, save_figure, series_colours


def test_the_accent_is_never_a_default_series_colour():
    """The house rule: amber highlights one thing, it does not fill a series."""
    assert PALETTE["accent"] not in SERIES


def test_series_colours_are_distinct_until_they_have_to_repeat():
    assert len(set(series_colours(len(SERIES)))) == len(SERIES)
    assert series_colours(len(SERIES) + 1)[-1] == SERIES[0]


def test_house_style_is_applied_to_the_global_rcparams():
    apply_house_style()
    assert plt.rcParams["axes.titlelocation"] == "left"
    assert plt.rcParams["legend.frameon"] is False
    assert plt.rcParams["axes.spines.top"] is False


def test_save_figure_creates_the_directory_and_writes_a_png(tmp_path):
    figure = new_figure(4, 3)
    figure.add_subplot().plot([1, 2, 3], [2, 1, 3])
    destination = save_figure(figure, tmp_path / "nested" / "chart.png", dpi=72)
    assert destination.exists()
    assert destination.stat().st_size > 1_000
    assert destination.read_bytes()[:4] == b"\x89PNG"
