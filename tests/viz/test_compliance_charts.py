"""The Day 6 charts: each draws from the mandate checked over the demonstration account."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian import compliance_gallery
from meridian.compliance.parser import parse_rule
from meridian.gallery import gallery_items
from meridian.services.demo_compliance import build_demo_compliance


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


def titles(figure) -> list[str]:
    return [axis.get_title(loc="left") or axis.get_title() for axis in figure.axes]


@pytest.mark.parametrize(
    ("builder", "panels", "phrase"),
    [
        (compliance_gallery.utilisation_chart, 1, "Utilisation"),
        (compliance_gallery.timeline_chart, 1, "Every breach"),
        (compliance_gallery.heatmap_chart, 1, "Highest utilisation"),
        (compliance_gallery.issuer_chart, 1, "Microsoft"),
        (compliance_gallery.look_through_chart, 2, "looked through"),
        (compliance_gallery.register_chart, 3, "How they ended"),
        (compliance_gallery.pretrade_chart, 1, "order requested"),
        (compliance_gallery.replay_chart, 2, "baskets"),
        (compliance_gallery.ucits_chart, 2, "Issuers above 5%"),
        (compliance_gallery.tree_chart, 1, ""),
        (compliance_gallery.allocation_chart, 3, "Cash"),
        (compliance_gallery.report_chart, 3, "Limit utilisation today"),
    ],
)
def test_each_chart_has_its_panels_and_says_what_it_shows(builder, panels, phrase):
    figure = builder()
    assert len([axis for axis in figure.axes if axis.get_visible()]) >= panels
    assert any(phrase in title for title in titles(figure)), titles(figure)
    assert figure.texts, "every chart carries a title block"


def test_chart_data_agrees_with_the_register():
    demo = build_demo_compliance()
    rows = compliance_gallery.utilisation_rows(demo.today.results)
    assert len(rows) == len(demo.mandate.rules) and rows[0][2] == "Concentration"
    by_rule, durations, resolutions = compliance_gallery.register_summary(demo)
    assert sum(row[1] + row[2] for row in by_rule) == len(demo.breaches)
    assert sum(len(values) for values in durations.values()) == len(demo.breaches)
    assert sum(resolutions.values()) == len(demo.breaches)
    top, exclusions = compliance_gallery.look_through_rows(demo)
    assert top[0][0] == "MICROSOFT" and top[0][2] > top[0][1]
    assert exclusions and exclusions[0][1] == "Tobacco"
    levels = compliance_gallery.warn_levels(demo)
    assert levels["issuer_limit"] == pytest.approx(0.105 / 0.12)
    labels, matrix = compliance_gallery.monthly_utilisation(demo)
    assert matrix.shape == (len(demo.mandate.rules), len(labels))


def test_the_rule_tree_follows_the_parse():
    label, children = compliance_gallery.rule_tree(parse_rule(compliance_gallery.TREE_RULE))
    assert label.startswith("rule defence_screen") and len(children) == 3
    measure, bound, warning = children
    assert "look through" in measure[1][0][0] and bound[0].endswith("10%") and warning[0].endswith("8.0%")


def test_the_pretrade_reason_is_the_rule_that_decided():
    reasons = {row[2]: (row[5], row[6]) for row in compliance_gallery.pretrade_rows(build_demo_compliance())}
    assert reasons["IE-IWDA"] == ("blocked", "cash")  # the hard cash floor, not the soft look-through rule
    assert reasons["GB-BAE"][0] == "override required" and "tracking error" in reasons["GB-BAE"][1]


def test_the_compliance_group_is_in_the_gallery():
    names = {item.filename for item in gallery_items() if item.group == "compliance"}
    assert len(names) == 12 and "compliance-report.png" in names
