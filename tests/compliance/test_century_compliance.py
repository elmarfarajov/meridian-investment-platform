"""A sector limit on a century of the US market: the engine and the register on real history."""

from __future__ import annotations

from datetime import date

import pytest

from meridian.services import century_compliance as century


def test_the_market_broke_a_forty_percent_industry_limit_only_in_2025():
    register = century.index_register()
    assert [breach.group for breach in register] == ["Business equipment", "Business equipment"]
    assert all(breach.kind == "passive" for breach in register)  # an index fund trades nothing
    first, second = register
    assert first.opened == date(2025, 8, 31) and first.resolution == "resolved by the market"
    assert second.opened == date(2026, 5, 31) and second.closed is None and second.peak_value > 0.45


def test_even_the_dot_com_peak_stayed_short_of_the_warning_level():
    reports = century.index_reports()
    warnings = [report.day for report in reports if report.result("sector_40").status == "warning"]
    assert warnings and min(warnings) >= date(2021, 12, 31)
    peak_2000 = max(report.result("sector_40").value for report in reports if report.day.year == 2000)
    assert 0.34 < peak_2000 < 0.35


def test_capping_redistributes_pro_rata_and_never_exceeds_the_cap():
    capped = century.cap_weights({"A": 0.5, "B": 0.3, "C": 0.2}, cap=0.4)
    assert capped == pytest.approx({"A": 0.4, "B": 0.36, "C": 0.24})  # B and C keep their 3:2 proportion
    twice = century.cap_weights({"A": 0.6, "B": 0.3, "C": 0.05, "D": 0.05}, cap=0.35)
    assert max(twice.values()) <= 0.35 + 1e-12 and sum(twice.values()) == pytest.approx(1.0)
    assert twice["A"] == pytest.approx(0.35) and twice["B"] == pytest.approx(0.35)
    with pytest.raises(ValueError, match="cannot hold"):
        century.cap_weights({"A": 0.5, "B": 0.5}, cap=0.3)


def test_a_capped_index_cost_almost_nothing_over_the_century():
    comparison = century.capped_comparison()
    assert comparison.months_binding == 40
    market, capped = comparison.annual(comparison.market), comparison.annual(comparison.capped)
    assert abs(market - capped) < 0.0002  # under two basis points a year
    assert comparison.tracking_error < 0.005
