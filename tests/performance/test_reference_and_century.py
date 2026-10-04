"""Performance against empyrical and scipy, and on a century of real US returns."""

from __future__ import annotations

from datetime import date

import pytest

from meridian.core.exceptions import ValidationError
from meridian.devtools import fetch_french
from meridian.devtools.performance_reference import CONVENTIONS, compare, reconciliation
from meridian.marketdata.french import INDUSTRY_NAMES, french_history, month_end
from meridian.performance.linking import METHODS
from meridian.performance.statistics import drawdown_episodes, risk_return
from meridian.services import century_review as century


# ---------------------------------------------------------------------------- the packaged data
def test_a_century_of_industry_returns_is_packaged():
    history = french_history()
    assert history.months[0] == date(1926, 7, 31) and len(history.months) >= 1202
    assert set(history.industries) == set(INDUSTRY_NAMES)
    assert all(abs(sum(history.weights(month).values()) - 1.0) < 1e-12 for month in history.months[::97])
    first = history.data[date(1926, 7, 31)]["NoDur"]
    assert first.value_weighted == pytest.approx(0.0144) and first.firms > 0  # as printed: 1.44%
    assert month_end("200002") == date(2000, 2, 29)


def test_the_parser_reads_the_library_s_sections():
    text = "title line\n\n  Average Firm Size\n,A,B\n192607, 1.0, 2.0\n  1927, 9.9, 9.9\n"
    parsed = fetch_french.sections(text)
    header, rows = parsed["Average Firm Size"]
    assert header == ["A", "B"] and fetch_french.monthly_rows(parsed["Average Firm Size"]) == [
        ("192607", ["1.0", "2.0"])
    ]
    assert len(rows) == 2  # the annual row is read, and dropped by monthly_rows


def test_a_slice_of_history_keeps_its_months():
    history = french_history().between(date(1999, 12, 31), date(2009, 12, 31))
    assert history.months[0] == date(2000, 1, 31) and history.months[-1] == date(2009, 12, 31)
    with pytest.raises(ValidationError, match="no months"):
        french_history().between(date(1900, 1, 1), date(1901, 1, 1))


# ---------------------------------------------------------------------------- the benchmark rebuilt
def test_the_market_rebuilt_from_its_industries_tracks_the_published_market():
    check = century.benchmark_check()
    assert check.correlation > 0.9995
    assert check.rms_gap < 0.0012  # 11 bp a month
    month, gap = check.largest_gap
    assert month == date(2000, 3, 31) and gap > 0.015  # the top of the technology bubble
    rebuilt, published = check.growth()
    assert rebuilt / published == pytest.approx(1.113, abs=0.01)  # a century of 11 bp compounds to 11%


# ---------------------------------------------------------------------------- attribution
def test_a_century_of_attribution_is_exact_under_every_linking_method():
    results = century.linking_comparison()
    actives = {method: result.active for method, result in results.items()}
    assert set(results) == set(METHODS)
    assert all(abs(result.residual) < 1e-6 * abs(result.active) for result in results.values())
    assert max(actives.values()) - min(actives.values()) < 1e-6
    allocation = {method: result.effect("allocation") / result.active for method, result in results.items()}
    assert results["grap"].effect("allocation") == pytest.approx(results["frongello"].effect("allocation"))
    assert max(allocation.values()) - min(allocation.values()) > 0.04  # Cariño 7%, Menchero 12% of the answer


def test_the_equal_weighted_market_beat_the_cap_weighted_over_the_century_but_not_the_last_decade():
    whole = century.equal_weight_attribution()
    assert whole.portfolio > whole.benchmark
    decades = dict(century.decade_attribution())
    assert decades["2000s"].portfolio > 1.0 and decades["2000s"].benchmark < 0.0
    assert decades["2010s"].effect("selection") < 0  # the decade of the largest companies
    for result in decades.values():
        assert abs(result.residual) < 1e-9


def test_real_risk_statistics():
    market = century.market_series()
    worst = drawdown_episodes(market, 1)[0]
    assert worst.peak == date(1929, 8, 31) and worst.trough == date(1932, 6, 30)
    assert worst.depth == pytest.approx(-0.837, abs=0.005) and worst.recovery == date(1945, 1, 31)
    excess = risk_return(century.excess_series(), risk_free=0.0)
    assert 0.3 < excess.sharpe < 0.45


# ---------------------------------------------------------------------------- the reference library
def test_every_measure_agrees_with_empyrical_or_differs_by_a_reconciled_convention():
    comparisons = compare(century.equal_weight_series(), century.market_series(), 0.0, "century")
    assert all(item.reconciled for item in comparisons), [item.measure for item in comparisons if not item.reconciled]
    differing = {item.measure for item in comparisons if not item.agrees}
    assert differing <= set(CONVENTIONS)
    assert {"volatility", "beta", "maximum drawdown", "up capture", "down capture"}.isdisjoint(differing)


@pytest.mark.slow
def test_the_demonstration_account_reconciles_too():
    comparisons = reconciliation()
    assert len(comparisons) == 30 and all(item.reconciled for item in comparisons)
