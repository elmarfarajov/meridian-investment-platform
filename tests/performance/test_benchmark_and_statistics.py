"""The benchmark's construction and the risk-adjusted statistics."""

from __future__ import annotations

from datetime import date

import pytest

from meridian.accounting.sources import FixedFx
from meridian.core import ValidationError
from meridian.marketdata.providers.synthetic import InstrumentSpec, demo_market
from meridian.marketdata.series import TimeSeries
from meridian.performance.benchmark import Constituent, EquityIndex, PolicyBenchmark, index_level, region_of
from meridian.performance.returns import ReturnSeries
from meridian.performance.statistics import (
    calendar_table,
    drawdown_episodes,
    relative,
    risk_return,
    rolling,
    summary_rows,
)
from meridian.services.demo_market import DEMO_END, DEMO_START

D = date
DAYS = [D(2025, 1, 30), D(2025, 1, 31), D(2025, 2, 3), D(2025, 2, 4)]


def series(values: list[float]) -> TimeSeries:
    return TimeSeries([(day, value) for day, value in zip(DAYS, values, strict=True)])


def test_a_cap_weighted_index_drifts_with_returns_and_translates_currency():
    constituents = (
        Constituent("A", "A", "Tech", "North America", "USD", "XNYS", 300.0),
        Constituent("B", "B", "Banks", "Europe ex UK", "EUR", "TARGET", 100.0),
    )
    fx = FixedFx({"EUR": "1.10", ("EUR", D(2025, 2, 3)): "1.21"})
    index = EquityIndex("Test", constituents, {"A": series([100, 110, 110, 110]), "B": series([50, 50, 50, 55])}, fx)
    days = index.days(DAYS)
    first = dict((item.instrument_id, (weight, local, move)) for item, weight, local, move in days[0][1])
    assert first["A"] == (pytest.approx(0.75), pytest.approx(0.10), 0.0)
    second = {item.instrument_id: weight for item, weight, _, _ in days[1][1]}
    assert second["A"] == pytest.approx(330 / 430)
    euro = {item.instrument_id: (local, move) for item, _, local, move in days[1][1]}["B"]
    assert euro == (0.0, pytest.approx(0.10))
    with pytest.raises(ValidationError, match="no total return series"):
        EquityIndex("Broken", constituents, {"A": series([1, 1, 1, 1])}, fx)


def test_the_policy_benchmark_rebalances_monthly_and_blends_sleeves():
    constituents = (Constituent("A", "A", "Tech", "North America", "USD", "XNYS", 1.0),)
    index = EquityIndex("Test", constituents, {"A": series([100, 110, 110, 110])}, FixedFx({}))
    policy = PolicyBenchmark("P", index, {"equity": 0.8, "fixed income": 0.15, "cash": 0.05}, {D(2025, 1, 31): 0.02})
    built = policy.build(DAYS)
    assert built[0].rate == pytest.approx(0.8 * 0.10 + 0.15 * 0.02)
    # on 3 February (a new month) the drifted weights are reset to policy
    assert built[1].weights("sector")["Tech"] == pytest.approx(0.8)
    assert index_level(built)[0][1] == pytest.approx(100 * (1 + built[0].rate))
    with pytest.raises(ValidationError, match="sum to"):
        PolicyBenchmark("P", index, {"equity": 0.5, "fixed income": 0.1, "cash": 0.1})
    assert region_of("CH") == "Switzerland" and region_of(None) == "Other"


def test_companions_share_the_markets_factor_without_changing_it():
    market = demo_market(7)
    before = market.generate(DEMO_START, DEMO_END).log_returns["US-AAPL"]
    companion = market.companion([InstrumentSpec("BM-X", sector="Information Technology")], DEMO_START, DEMO_END)
    assert companion.market_factor == market.generate(DEMO_START, DEMO_END).market_factor
    assert demo_market(7).generate(DEMO_START, DEMO_END).log_returns["US-AAPL"] == before
    with pytest.raises(ValidationError, match="must be new"):
        market.companion([InstrumentSpec("US-AAPL")], DEMO_START, DEMO_END)
    with pytest.raises(ValidationError, match="end after start"):
        market.companion([InstrumentSpec("BM-Y")], DEMO_END, DEMO_START)


# ---------------------------------------------------------------------------- statistics
def returns(rates: list[float], start: date | None = None) -> ReturnSeries:
    start = start or D(2025, 1, 1)
    days = tuple(date.fromordinal(start.toordinal() + index + 1) for index in range(len(rates)))
    return ReturnSeries(days, tuple(rates))


def test_drawdown_episodes_find_peak_trough_and_recovery():
    s = returns([0.10, -0.20, 0.05, 0.25, -0.05])
    worst, other = drawdown_episodes(s, 2)
    assert worst.depth == pytest.approx(-0.20)
    assert worst.peak == D(2025, 1, 2) and worst.trough == D(2025, 1, 3) and worst.recovery == D(2025, 1, 5)
    assert other.recovery is None and other.depth == pytest.approx(-0.05)
    assert worst.length == 3


def test_risk_measures_on_a_known_series():
    s = returns([0.01, -0.01] * 130)
    measures = risk_return(s, risk_free=0.0)
    assert measures.volatility == pytest.approx(0.01 * (252**0.5), rel=0.01)
    assert measures.positive_days == pytest.approx(0.5)
    assert measures.best_day == 0.01 and measures.worst_day == -0.01
    assert measures.var_95 == pytest.approx(-0.01)
    assert abs(measures.skewness) < 1e-9
    with pytest.raises(ValidationError, match="at least two"):
        risk_return(returns([0.01]))


def test_a_series_against_itself():
    s = returns([0.01, -0.02, 0.015, 0.003, -0.004] * 20)
    rel = relative(s, s)
    assert rel.tracking_error == 0.0 and rel.beta == pytest.approx(1.0) and rel.correlation == pytest.approx(1.0)
    assert rel.up_capture == pytest.approx(1.0) and rel.down_capture == pytest.approx(1.0)
    assert rel.active_return == 0.0 and rel.information_ratio == 0.0
    leveraged = ReturnSeries(s.days, tuple(2 * value for value in s.rates))
    assert relative(leveraged, s).beta == pytest.approx(2.0)
    with pytest.raises(ValidationError, match="fewer than two"):
        relative(s, returns([0.01], start=D(2030, 1, 1)))


def test_rolling_and_calendar_and_summary():
    s = returns([0.001, -0.002, 0.003] * 40)
    b = returns([0.0005, -0.001, 0.002] * 40)
    points = rolling(s, b, window=20)
    assert len(points) == 101 and points[0].day == s.days[19]
    assert all(point.tracking_error > 0 for point in points)
    table = calendar_table(returns([0.001] * 70, start=D(2024, 12, 31)))
    assert set(table[2025]) >= {1, 2, 13}
    rows = dict((name, (mine, theirs)) for name, mine, theirs in summary_rows(s, b))
    assert "Information ratio" in rows and rows["Beta"][1] == "1.00"
