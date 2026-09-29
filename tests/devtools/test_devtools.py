"""The project measured: the layering holds, the growth counts are right, the working day runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from meridian.devtools.growth import OUTPUT, _count_tests, load, measure
from meridian.devtools.structure import import_graph, package_stats, tests_by_package, upward
from meridian.platform_gallery import LAYERS


def test_every_import_points_down_the_layers():
    edges = import_graph()
    assert upward(edges, LAYERS) == []
    assert not [edge for edge in edges if edge[0] == "core"]  # core imports nothing from the platform
    layered = {name for names in LAYERS for name in names}
    assert {name for edge in edges for name in edge} <= layered  # every package has a place


def test_package_stats_and_test_counts_are_parsed():
    stats = {item.name: item for item in package_stats()}
    assert stats["core"].modules > 5 and stats["api"].lines > 500
    tests = tests_by_package()
    assert tests["api"][0] >= 30 and tests["core"][1] >= 1  # property tests are found by their decorator


def test_a_release_is_measured_from_its_files():
    files = {
        "src/meridian/core/a.py": "x = 1\n\ny = 2\n",
        "tests/core/test_a.py": (
            "from hypothesis import given\n\n@given()\ndef test_p():\n    pass\n\ndef test_q():\n    pass\n"
        ),
        "docs/images/a.png": "",
        "docs/adr/0001-x.md": "# x",
        "alembic/versions/0001_x.py": "",
    }
    release = measure(files, "v9.9.9", "2026-09-30", 42)
    assert (release.source_lines, release.tests, release.property_tests) == (2, 2, 1)
    assert (release.figures, release.decisions, release.migrations, release.commits) == (1, 1, 1, 42)
    assert _count_tests("def broken(:") == (0, 0)


def test_the_recorded_growth_is_monotone_where_it_should_be():
    releases = load(OUTPUT)
    assert releases[0].tag == "v0.1.0" and releases[-1].tag == "v1.0.0"
    assert [item.source_lines for item in releases] == sorted(item.source_lines for item in releases)
    assert [item.decisions for item in releases] == sorted(item.decisions for item in releases)
    rows = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert rows[-1]["collected"] > rows[-1]["tests"]  # parametrised cases counted one by one


def test_a_short_working_day_exercises_every_control(tmp_path):
    sys.path.insert(0, str(Path(__file__).parents[1] / "api"))
    from conftest import FakeData  # type: ignore[import-not-found]
    from meridian.devtools.workload import route_of, run_workload

    result = run_workload(rounds=4, data=FakeData(), directory=tmp_path)
    statuses = result.statuses()
    assert statuses.get(200, 0) > 20 and result.chain_valid
    assert result.audit_records >= len(result.samples)
    assert route_of("/v1/orders/ORD-000012/decision") == "/v1/orders/{id}/decision"
    assert route_of("/v1/portfolios/PF-GLOBAL-EQ/risk") == "/v1/portfolios/{id}/risk"
