"""Risk against independent references, and on a century of daily US returns."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from meridian.devtools.risk_reference import reconciliation
from meridian.marketdata.french import french_daily
from meridian.risk.backtest import ewma_volatility, garch_var
from meridian.risk.garch import fit_garch, garch_filter
from meridian.risk.validation import qlike
from meridian.services import century_risk as century


def test_every_reference_agrees_or_differs_by_a_recorded_convention():
    checks = reconciliation()
    assert len(checks) >= 40
    breaks = [check for check in checks if not check.agrees and not check.convention]
    assert not breaks, [(check.reference, check.subject) for check in breaks]
    assert sum(1 for check in checks if check.convention) == 1  # PyPortfolioOpt's T - 1 sample, and only that


def test_the_daily_tables_are_packaged_and_aligned():
    data = french_daily()
    assert data.days[0] == date(1926, 7, 1) and len(data.days) >= 26_300
    assert data.returns.shape == (len(data.days), 12)
    crash = data.index_of(date(1987, 10, 19))
    assert data.days[crash] == date(1987, 10, 19) and data.market[crash] == pytest.approx(-0.1741, abs=5e-5)


def test_garch_var_filters_each_segment_with_garch_filter():
    returns = french_daily().market[-1400:]
    _, volatility, fits = garch_var(returns, window=1000, refit_every=10_000)
    assert len(fits) == 1
    fit = fit_garch(returns[:1000])
    warm = float(np.var(returns[:1000]))
    for day in range(1, 1000):
        warm = 0.94 * warm + 0.06 * returns[day - 1] ** 2
    expected = garch_filter(returns[1000:], fit, warm, returns[999] ** 2)
    assert np.allclose(volatility[1000:], expected, rtol=1e-12)


def test_qlike_prefers_the_right_forecast():
    rng = np.random.default_rng(2)
    sigma = np.exp(rng.normal(-4.5, 0.5, 20_000))
    returns = sigma * rng.standard_normal(len(sigma))
    assert qlike(returns, sigma) < qlike(returns, sigma * 1.3) and qlike(returns, sigma) < qlike(returns, sigma * 0.7)
    assert qlike(returns, sigma) < qlike(returns, np.full(len(sigma), sigma.mean()))


def test_a_century_of_var_backtests():
    results = {item.method: item for item in century.var_backtest()}
    assert set(results) == set(century.METHODS)
    normal, historical = results[century.METHODS[0]], results[century.METHODS[1]]
    filtered, garch = results[century.METHODS[2]], results[century.METHODS[3]]
    assert normal.rate > 0.02  # the normal tail is too thin: twice the exceptions it promises
    assert filtered.rate < garch.rate < historical.rate < normal.rate
    assert filtered.zone_counts()["red"] == 0 and historical.zone_counts()["red"] >= 8
    assert historical.christoffersen.p_value < 1e-10  # historical simulation reacts late, so misses cluster
    worst_day, _, ratio = normal.worst(1)[0]
    assert worst_day == date(1955, 9, 26) and ratio > 6  # Eisenhower's heart attack, not 1987, was the worst surprise
    assert date(1987, 10, 19) in {day for day, _, _ in historical.worst(3)}


def test_the_riskmetrics_forecast_runs_a_little_low_in_every_decade():
    rows = century.bias_by_decade()
    assert len(rows) == 13 * 11
    assert all(row.verdict == "under-forecasts" for row in rows)
    assert all(1.0 < row.bias < 1.15 for row in rows if row.series == "Market")


def test_garch_beats_ewma_and_both_beat_a_rolling_year():
    losses = century.forecast_losses()
    whole = {name: values[0] for name, values in losses.items()}
    assert whole["GARCH(1,1)-t"] < whole["RiskMetrics EWMA"] < whole["Rolling 252 days"]
    decades = [decade for decade in losses["GARCH(1,1)-t"] if decade]
    wins = sum(losses["GARCH(1,1)-t"][d] < losses["RiskMetrics EWMA"][d] for d in decades)
    assert wins >= 8


def test_with_twelve_assets_shrinkage_barely_matters():
    summary = century.covariance_summary()
    ratios = {name: ratio for name, (_, _, ratio) in summary.items()}
    assert all(0.95 < ratio < 1.08 for ratio in ratios.values())
    assert ratios["Ledoit-Wolf (identity)"] < 1.0  # the only one that promised more risk than it delivered


def test_ewma_volatility_uses_only_the_past():
    returns = np.array([0.01] * 60 + [0.10, 0.0, 0.0])
    volatility = ewma_volatility(returns)
    assert volatility[60] == pytest.approx(0.01)  # the 10% day is not in its own forecast
    assert volatility[61] > 0.02
