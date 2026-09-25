"""The risk command group, end to end."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture
def database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", f"sqlite:///{(tmp_path / 'risk.sqlite').as_posix()}")
    reset_settings_cache()
    yield
    reset_settings_cache()


def invoke(*arguments: str) -> str:
    result = runner.invoke(app, ["risk", *arguments])
    assert result.exit_code == 0, result.stdout
    return result.stdout


def test_the_model_and_the_portfolio():
    output = invoke("model")
    assert "World" in output and "FX JPY" in output and "R-squared" in output
    portfolio = invoke("portfolio")
    assert "Specific" in portfolio and "Total" in portfolio and "active bets" in portfolio


def test_contributions_var_and_stress():
    assert "MSFT" in invoke("contributions")
    assert "basis" in invoke("contributions", "--active")
    output = invoke("var", "--horizon", "10")
    assert "Monte Carlo" in output and "10-day" in output
    assert "Equities -20%" in invoke("stress")


def test_backtest_and_validation():
    output = invoke("backtest")
    assert "Bias statistics" in output and "green" in output
    assert "passed" in output or "rejected" in output
    validation = invoke("validate")
    assert "EWMA" in validation and "riskless" in validation


def test_report_writes_a_png(tmp_path):
    target = tmp_path / "report.png"
    assert "wrote" in invoke("report", "--out", str(target))
    assert target.stat().st_size > 50_000


def test_run_persist_then_recount_from_the_database(database_url):
    assert "Basel" in invoke("run", "--persist")
    output = invoke("stored")
    assert "VaR exceptions" in output and "World volatility" in output


def test_stored_on_an_empty_database_says_what_to_do(database_url):
    runner.invoke(app, ["db", "upgrade"])
    assert runner.invoke(app, ["risk", "stored"]).exit_code == 1
