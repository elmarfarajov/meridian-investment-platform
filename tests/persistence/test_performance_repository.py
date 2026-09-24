"""Returns and attribution in the database."""

from __future__ import annotations

import pytest

from meridian.core import ValidationError
from meridian.persistence import UnitOfWork
from meridian.services.demo_performance import build_demo_performance
from meridian.services.performance_run import check, report_periods, run_demo_performance

PORTFOLIO = "PF-GLOBAL-EQ"


@pytest.fixture(scope="module")
def perf():
    return build_demo_performance()


@pytest.fixture
def stored(unit_of_work: UnitOfWork, perf):
    result = run_demo_performance(perf, unit_of_work)
    unit_of_work.commit()
    return result


def test_the_run_stores_every_day_and_every_period(stored, perf):
    periods = report_periods(perf)
    assert periods[0] == (perf.portfolio_returns.start, perf.portfolio_returns.days[-1])
    assert [end.year for _, end in periods[1:]] == [2024, 2025, 2026]
    assert stored.days == len(perf.portfolio_days)
    assert len(stored.periods) == 2 * len(periods)
    assert any("active" in value for _, value in stored.summary_rows())


def test_linking_the_stored_days_gives_the_same_returns(stored, unit_of_work, perf):
    portfolio, benchmark = unit_of_work.performance.linked(PORTFOLIO)
    assert portfolio == pytest.approx(perf.portfolio_returns.total(), abs=1e-12)
    assert benchmark == pytest.approx(perf.benchmark_returns.total(), abs=1e-12)
    rows = unit_of_work.performance.returns(PORTFOLIO, perf.portfolio_returns.days[9], perf.portfolio_returns.days[19])
    assert len(rows) == 10


def test_stored_effects_explain_the_active_return(stored, unit_of_work, perf):
    everything = perf.by_sector
    rows = [
        row
        for row in unit_of_work.performance.effects(PORTFOLIO, "sector")
        if row.period_start == everything.start and row.period_end == everything.end
    ]
    assert {row.kind for row in rows} == {"segment", "currency", "costs"}
    explained = sum(row.allocation + row.selection + row.interaction + row.currency + row.costs for row in rows)
    assert explained == pytest.approx(everything.active, abs=1e-12)


def test_running_again_replaces_and_a_bad_attribution_is_refused(stored, unit_of_work, perf):
    again = run_demo_performance(perf, unit_of_work)
    assert again.effects == stored.effects
    assert len(unit_of_work.performance.returns(PORTFOLIO)) == stored.days

    class Broken:
        residual, start, end = 1e-3, perf.by_sector.start, perf.by_sector.end

    with pytest.raises(ValidationError, match="nothing written"):
        check(Broken())  # type: ignore[arg-type]


def test_the_dry_run_computes_without_a_database(perf):
    assert run_demo_performance(perf).effects == 0
