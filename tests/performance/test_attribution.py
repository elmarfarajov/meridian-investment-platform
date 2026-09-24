"""Brinson-Fachler, currency, costs and Cariño linking."""

from __future__ import annotations

import math
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.core import Ticker, ValidationError
from meridian.domain.instruments import Bond, Equity, Fund, SecurityIdentifiers
from meridian.performance.attribution import (
    AttributionDay,
    SegmentDay,
    attribute,
    attribute_day,
    benchmark_look_through,
    carino_factor,
    classify,
    link_attribution,
    monthly,
)
from meridian.performance.benchmark import CASH, FIXED_INCOME, BenchmarkDay, BenchmarkPiece
from meridian.performance.contributions import Exposure, PortfolioDay

D = date


def equity(key: str, sector: str, country: str = "US", currency: str = "USD") -> Equity:
    return Equity(
        instrument_id=key,
        name=key,
        currency=currency,
        identifiers=SecurityIdentifiers(ticker=Ticker(key[:5])),
        country=country,
        sector=sector,
    )


INSTRUMENTS = {
    "TECH": equity("TECH", "Tech"),
    "BANK": equity("BANK", "Banks"),
    "EURO": equity("EURO", "Banks", "DE", "EUR"),
    "FUND": Fund(
        instrument_id="FUND", name="World fund", currency="USD", identifiers=SecurityIdentifiers(ticker=Ticker("FUND"))
    ),
}
LOOK = benchmark_look_through({"FUND": None})


def piece(key: str, sector: str, weight: float, local: float, fx: float = 0.0, currency: str = "USD") -> BenchmarkPiece:
    return BenchmarkPiece(key, sector, "North America", currency, weight, local, fx)


def test_the_textbook_two_sector_example():
    """Portfolio 60/40 tech/banks returning 5% and 1%; benchmark 50/50 returning 4% and 2%."""
    day = D(2025, 3, 3)
    portfolio = PortfolioDay(
        day, 1000.0, 34.0, 0.0, (Exposure("TECH", "USD", 600, 30, 0), Exposure("BANK", "USD", 400, 4, 0))
    )
    benchmark = BenchmarkDay(day, (piece("B1", "Tech", 0.5, 0.04), piece("B2", "Banks", 0.5, 0.02)))
    result = attribute_day(portfolio, benchmark, INSTRUMENTS, look_through=LOOK)
    tech, banks = result.segments["Tech"], result.segments["Banks"]
    assert result.portfolio == pytest.approx(0.034) and result.benchmark == pytest.approx(0.03)
    assert tech.allocation == pytest.approx(0.1 * (0.04 - 0.03))
    assert tech.selection == pytest.approx(0.5 * (0.05 - 0.04))
    assert tech.interaction == pytest.approx(0.1 * (0.05 - 0.04))
    assert banks.allocation == pytest.approx(-0.1 * (0.02 - 0.03))
    assert banks.selection == pytest.approx(0.5 * (0.01 - 0.02))
    assert banks.interaction == pytest.approx(-0.1 * (0.01 - 0.02))
    assert result.residual == pytest.approx(0.0, abs=1e-15)
    assert result.effect("allocation") == pytest.approx(0.002)


def test_a_segment_the_portfolio_does_not_hold_and_one_the_benchmark_does_not():
    day = D(2025, 3, 3)
    portfolio = PortfolioDay(day, 1000.0, 20.0, 0.0, (Exposure("TECH", "USD", 1000, 20, 0),))
    benchmark = BenchmarkDay(day, (piece("B1", "Banks", 1.0, 0.01),))
    result = attribute_day(portfolio, benchmark, INSTRUMENTS, look_through=LOOK)
    assert result.segments["Banks"].rp is None and result.segments["Banks"].selection == 0
    assert result.segments["Tech"].rb is None
    assert result.residual == pytest.approx(0.0, abs=1e-15)


def test_currency_is_separated_and_costs_are_the_portfolios_own():
    day = D(2025, 3, 3)
    portfolio = PortfolioDay(
        day,
        1000.0,
        20.0 + 10.0 - 2.0,
        -2.0,
        (Exposure("EURO", "EUR", 500, 20, 10), Exposure("CASH:USD", "USD", 500, 0, 0)),
    )
    benchmark = BenchmarkDay(
        day, (piece("B1", "Banks", 0.5, 0.03, 0.01, "EUR"), BenchmarkPiece("C", CASH, CASH, "USD", 0.5, 0.0, 0.0))
    )
    result = attribute_day(portfolio, benchmark, INSTRUMENTS, look_through=LOOK)
    assert result.currency["EUR"] == pytest.approx(10 / 1000 - 0.5 * 0.01)
    assert result.costs == pytest.approx(-0.002)
    assert result.residual == pytest.approx(0.0, abs=1e-15)
    assert result.currency_weights["EUR"] == (0.5, 0.5)


def test_a_fund_is_looked_through_to_the_benchmark():
    day = D(2025, 3, 3)
    portfolio = PortfolioDay(day, 1000.0, 20.0, 0.0, (Exposure("FUND", "USD", 1000, 20, 0),))
    benchmark = BenchmarkDay(day, (piece("B1", "Tech", 0.75, 0.03), piece("B2", "Banks", 0.25, 0.01)))
    result = attribute_day(portfolio, benchmark, INSTRUMENTS, look_through=LOOK)
    assert result.segments["Tech"].wp == pytest.approx(0.75)
    assert result.segments["Banks"].wp == pytest.approx(0.25)
    assert result.effect("allocation") == pytest.approx(0.0, abs=1e-15)
    scoped = benchmark_look_through({"FUND": "Japan"})
    assert scoped("FUND", benchmark, "sector") == {"Other": 1.0}


def test_classification():
    bond = Bond(instrument_id="B", name="B", currency="USD", identifiers=SecurityIdentifiers(ticker=Ticker("B")))
    assert classify(bond, "sector") == FIXED_INCOME
    assert classify(INSTRUMENTS["EURO"], "region") == "Europe ex UK"
    assert classify(INSTRUMENTS["FUND"], "sector") is None


def test_carino_factor_and_its_limit():
    assert carino_factor(0.1, 0.1) == pytest.approx(1 / 1.1)
    assert carino_factor(0.1, 0.05) == pytest.approx((math.log(1.1) - math.log(1.05)) / 0.05)


def synthetic_day(
    day: date, rp: dict[str, float], rb: dict[str, float], wp: dict[str, float], wb: dict[str, float]
) -> AttributionDay:
    segments = {}
    bench_total = sum(wb[key] * rb[key] for key in wb)
    for key in wp:
        allocation = (wp[key] - wb[key]) * (rb[key] - bench_total)
        selection = wb[key] * (rp[key] - rb[key])
        interaction = (wp[key] - wb[key]) * (rp[key] - rb[key])
        segments[key] = SegmentDay(key, wp[key], wb[key], rp[key], rb[key], allocation, selection, interaction)
    portfolio = sum(wp[key] * rp[key] for key in wp)
    return AttributionDay(day, portfolio, bench_total, segments, {}, 0.0)


returns = st.floats(min_value=-0.04, max_value=0.04)


@settings(max_examples=80, deadline=None)
@given(
    st.lists(
        st.tuples(returns, returns, returns, returns, st.floats(0.1, 0.9), st.floats(0.1, 0.9)), min_size=2, max_size=40
    )
)
def test_linked_effects_always_sum_to_the_compounded_active_return(rows):
    days = [
        synthetic_day(
            date.fromordinal(D(2025, 1, 1).toordinal() + index),
            {"A": a, "B": b},
            {"A": c, "B": d},
            {"A": w, "B": 1 - w},
            {"A": v, "B": 1 - v},
        )
        for index, (a, b, c, d, w, v) in enumerate(rows)
    ]
    result = link_attribution(days, "sector")
    assert result.residual == pytest.approx(0.0, abs=1e-12)
    assert result.active == pytest.approx(
        math.prod(1 + x.portfolio for x in days) - math.prod(1 + x.benchmark for x in days)
    )


def test_attribute_checks_its_inputs_and_links_by_month():
    day1, day2 = D(2025, 1, 31), D(2025, 2, 3)
    portfolio = [PortfolioDay(day, 1000.0, 10.0, 0.0, (Exposure("TECH", "USD", 1000, 10, 0),)) for day in (day1, day2)]
    benchmark = [BenchmarkDay(day, (piece("B1", "Tech", 1.0, 0.005),)) for day in (day1, day2)]
    result = attribute(portfolio, benchmark, INSTRUMENTS, look_through=LOOK)
    assert result.residual == pytest.approx(0.0, abs=1e-15)
    assert [item.end for item in monthly(result)] == [day1, day2]
    assert result.segment("Tech").selection == pytest.approx(result.active)
    with pytest.raises(ValidationError, match="by sector or by region"):
        attribute(portfolio, benchmark, INSTRUMENTS, dimension="country", look_through=LOOK)
    with pytest.raises(ValidationError, match="no benchmark return"):
        attribute(portfolio, benchmark[:1], INSTRUMENTS, look_through=LOOK)
    with pytest.raises(ValidationError, match="at least one day"):
        link_attribution([], "sector")
