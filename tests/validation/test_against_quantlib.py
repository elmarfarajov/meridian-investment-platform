"""The rates engine reconciled against QuantLib: every check passes, every break is explained."""

from datetime import date

import pytest

pytest.importorskip("QuantLib")

from meridian.devtools.reference import (
    KNOWN_DIFFERENCES,
    compare_calendars,
    explain,
    monotone_convex_variant,
    reconciliation,
)


@pytest.fixture(scope="module")
def checks():
    return reconciliation()


def test_every_check_passes(checks):
    failed = [(check.area, check.name, check.max_error, check.unexplained[:3]) for check in checks if not check.passed]
    assert not failed
    assert len(checks) >= 27


def test_the_checks_cover_every_area(checks):
    assert {check.area for check in checks} == {"calendars", "day counts", "bonds", "gilts", "curves"}
    assert sum(check.cases for check in checks if check.area == "calendars") > 100_000


@pytest.mark.parametrize(
    ("calendar", "only_meridian", "only_quantlib"),
    [("XNYS", 0, 0), ("SIFMA", 0, 0), ("XLON", 0, 0), ("TARGET", 0, 0), ("XETR", 45, 0), ("XTKS", 11, 16)],
)
def test_the_calendar_breaks_are_exactly_the_documented_ones(calendar, only_meridian, only_quantlib):
    comparison = next(item for item in compare_calendars() if item.calendar == calendar)
    assert len(comparison.closed_only_by_meridian) == only_meridian
    assert len(comparison.closed_only_by_quantlib) == only_quantlib
    assert comparison.unexplained() == ()


def test_each_known_difference_carries_its_reason_and_evidence():
    for difference in KNOWN_DIFFERENCES:
        assert difference.reason and difference.evidence
    assert explain("calendars", "XETR", date(2026, 12, 31)) is not None
    assert explain("calendars", "XETR", date(2026, 12, 30)) is None
    assert explain("calendars", "XTKS", date(1990, 3, 21)) is not None
    assert explain("calendars", "XTKS", date(2010, 3, 22)) is None


def test_quantlib_s_convex_monotone_is_a_blend_close_to_pure_hagan_west():
    variant = monotone_convex_variant()
    assert variant["mean_forward_gap_bp"] < 2
    assert variant["max_forward_gap_bp"] < 10
    assert variant["passes"] > 1
