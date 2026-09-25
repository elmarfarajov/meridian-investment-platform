"""Risk in the database: factor returns, forecasts with outcomes, and report exposures."""

from __future__ import annotations

import numpy as np
import pytest

from meridian.core import ValidationError
from meridian.persistence import UnitOfWork
from meridian.services.demo_risk import build_demo_risk
from meridian.services.risk_run import MODEL_ID, check, run_demo_risk

PORTFOLIO = "PF-GLOBAL-EQ"


@pytest.fixture(scope="module")
def risk():
    return build_demo_risk()


@pytest.fixture
def stored(unit_of_work: UnitOfWork, risk):
    result = run_demo_risk(risk, unit_of_work)
    unit_of_work.commit()
    return result


def test_the_run_stores_the_history_the_forecasts_and_the_exposures(stored, risk):
    assert stored.stored["factor return"] == len(risk.estimated.days) * len(risk.factors)
    assert stored.stored["forecast"] == len(risk.book_forecasts)
    assert stored.stored["exposure"] == len(risk.factors)
    assert stored.zone in {"green", "yellow"} and any("Basel" in label for label, _ in stored.summary_rows())


def test_factor_volatility_computed_in_sql_matches_python(stored, unit_of_work, risk):
    in_sql = unit_of_work.risk.realised_volatility(MODEL_ID, "World")
    in_python = float(np.std(risk.estimated.factor("World"), ddof=1)) * 252**0.5
    assert in_sql == pytest.approx(in_python, rel=1e-9)
    series = unit_of_work.risk.factor_returns(MODEL_ID, "Momentum")
    assert len(series) == len(risk.estimated.days) and series[0][0] == risk.estimated.days[0]


def test_the_backtest_can_be_recounted_from_the_database(stored, unit_of_work, risk):
    hits, days = unit_of_work.risk.exception_count(PORTFOLIO)
    assert (hits, days) == (stored.exceptions, stored.scored_days)
    rows = unit_of_work.risk.forecasts(PORTFOLIO)
    assert rows[0].forecast_date == risk.book_forecasts[0].day
    assert rows[-1].var_99 == pytest.approx(risk.book_forecasts[-1].var)
    exposures = {row.factor: row for row in unit_of_work.risk.exposures(PORTFOLIO, risk.model.as_of)}
    assert exposures["World"].portfolio == pytest.approx(risk.portfolio.exposure("World"))
    total = sum(row.active_contribution for row in exposures.values())
    assert total == pytest.approx(risk.active.volatility - risk.active.by_group()["Specific"], rel=1e-9)


def test_running_again_replaces_and_a_broken_forecast_is_refused(stored, unit_of_work, risk, monkeypatch):
    again = run_demo_risk(risk, unit_of_work)
    assert again.stored == stored.stored
    assert unit_of_work.risk.exception_count(PORTFOLIO)[1] == stored.scored_days
    broken = list(risk.book_forecasts)
    broken[3] = type(broken[3])(broken[3].day, 1, float("nan"), 0.01, 0.5, 0.0, 0.0)
    monkeypatch.setattr(type(risk), "book_forecasts", property(lambda self: broken))
    with pytest.raises(ValidationError, match="nothing written"):
        check(risk)
