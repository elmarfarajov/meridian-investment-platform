"""The chart gallery: one definition, used by the docs, the CLI and the tests."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian.gallery import build_gallery, gallery_items, gallery_markdown, reference_bond, reference_curve

GROUPS = {"calendars", "rates", "cashflows", "money", "platform"}


def test_every_item_is_uniquely_named_and_grouped():
    items = gallery_items()
    assert len(items) >= 15
    filenames = [item.filename for item in items]
    assert len(set(filenames)) == len(filenames)
    assert all(item.filename.endswith(".png") for item in items)
    assert {item.group for item in items} <= GROUPS
    assert all(item.title and item.description for item in items)


def test_the_reference_curve_and_bond_are_the_ones_the_docs_describe():
    curve = reference_curve()
    assert len(curve.years) == 10
    assert curve.par_rate(10) == pytest.approx(0.0415, abs=1e-10)
    bond = reference_bond()
    assert bond.coupon_rate == 0.04
    assert bond.maturity.year == 2034


def test_building_one_group_writes_only_that_group(tmp_path):
    written = build_gallery(tmp_path, only="money", dpi=60)
    expected = {item.filename for item in gallery_items() if item.group == "money"}
    assert {path.name for path in written} == expected
    assert all(path.stat().st_size > 3_000 for path in written)
    plt.close("all")


def test_building_a_single_chart_by_filename(tmp_path):
    written = build_gallery(tmp_path, only="data-model.png", dpi=60)
    assert len(written) == 1
    assert written[0].name == "data-model.png"
    plt.close("all")


def test_the_markdown_block_references_every_chart():
    markdown = gallery_markdown("docs/images")
    for item in gallery_items():
        assert f"docs/images/{item.filename}" in markdown
        assert item.title in markdown


@pytest.mark.slow
def test_the_whole_gallery_builds(tmp_path):
    written = build_gallery(tmp_path, dpi=60)
    assert len(written) == len(gallery_items())
    assert all(path.exists() for path in written)
    plt.close("all")
