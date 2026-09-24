"""The demonstration account's performance and attribution, checked against the book."""

from __future__ import annotations

import pytest

from meridian.performance.contributions import holding_contributions
from meridian.performance.returns import flows_of, modified_dietz, money_weighted_return
from meridian.services.demo_performance import (
    COMPANIONS,
    DemoPerformance,
    build_demo_performance,
    constituents,
)


@pytest.fixture(scope="module")
def perf() -> DemoPerformance:
    return build_demo_performance()


def test_every_day_decomposes_exactly_into_holdings_cash_and_costs(perf: DemoPerformance):
    days = perf.portfolio_days
    assert len(days) == len(perf.accounting.daily_bridges)
    assert max(abs(day.residual) for day in days) < 1e-6
    # the portfolio's weights sum to one on every day, transfers in kind included
    assert all(abs(sum(e.value for e in day.exposures) / day.capital - 1) < 1e-9 for day in days if day.capital)


def test_the_time_weighted_return_matches_the_decomposition(perf: DemoPerformance):
    rates = [day.rate for day in perf.portfolio_days]
    assert rates == pytest.approx(list(perf.portfolio_returns.rates))
    contributions = holding_contributions(perf.portfolio_days)
    assert sum(contributions.values()) == pytest.approx(perf.portfolio_returns.total(), abs=1e-10)
    assert contributions["Costs"] < 0


def test_money_weighted_and_dietz_against_time_weighted(perf: DemoPerformance):
    bridges = perf.accounting.daily_bridges
    first, last = bridges[0], bridges[-1]
    mwr = money_weighted_return(float(first.opening), float(last.closing), flows_of(bridges), first.start, last.end)
    dietz = modified_dietz(float(first.opening), float(last.closing), flows_of(bridges), first.start, last.end)
    twr = perf.portfolio_returns.total()
    assert abs(dietz - mwr.period) < 0.01  # Dietz approximates the IRR, not the TWR
    assert abs(twr - dietz) > 1e-4  # and it is not the TWR when money moves


def test_the_benchmark_is_a_world_index_with_a_policy_blend(perf: DemoPerformance):
    assert len(constituents()) == 36 and len(COMPANIONS) == 30
    first = perf.benchmark_days[0]
    assert sum(first.weights("sector").values()) == pytest.approx(1.0)
    regions = first.weights("region")
    assert regions["North America"] / 0.8 == pytest.approx(0.757, abs=0.02)
    assert regions["Fixed income"] == pytest.approx(0.15) and regions["Cash"] == pytest.approx(0.05)
    assert perf.benchmark_returns.days == perf.portfolio_returns.days


@pytest.mark.parametrize("dimension", ["sector", "region"])
def test_attribution_explains_the_active_return_exactly(perf: DemoPerformance, dimension: str):
    result = perf.attribution(dimension)
    assert result.portfolio == pytest.approx(perf.portfolio_returns.total(), abs=1e-10)
    assert result.benchmark == pytest.approx(perf.benchmark_returns.total(), abs=1e-10)
    assert abs(result.residual) < 1e-12
    assert max(abs(day.residual) for day in result.days) < 1e-12
    assert abs(result.linking_gap) > 1e-4  # the unlinked sum would be wrong by more than a basis point
    names = {item.segment for item in result.segments}
    assert {"Fixed income", "Cash"} <= names


def test_by_sector_and_by_region_agree_on_everything_but_the_split(perf: DemoPerformance):
    sector, region = perf.by_sector, perf.by_region
    assert sector.active == pytest.approx(region.active)
    assert sector.effect("currency") == pytest.approx(region.effect("currency"))
    assert sector.effect("costs") == pytest.approx(region.effect("costs"))
    assert sector.segment("Industrials").selection > 0  # BAE Systems beat its sector
    months = perf.monthly_by_sector
    assert len(months) >= 29 and all(abs(item.residual) < 1e-12 for item in months)
