"""The rebalance command group, end to end."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", f"sqlite:///{(tmp_path / 'rebalance.sqlite').as_posix()}")
    reset_settings_cache()
    yield
    reset_settings_cache()


def invoke(*arguments: str) -> str:
    result = runner.invoke(app, ["rebalance", *arguments])
    assert result.exit_code == 0, result.stdout
    return result.stdout


def test_propose_prints_the_orders():
    output = invoke("propose")
    assert "Orders" in output and "tracking error" in output
    assert "sell" in output and "buy" in output
    assert "Orders" in invoke("propose", "--risk-aversion", "3", "--no-harvest")
    assert runner.invoke(app, ["rebalance", "propose", "--risk-aversion", "-1"]).exit_code == 1


def test_lots_compare_and_frontier():
    assert "four ways" in invoke("lots")
    assert "tax-blind" in invoke("compare")
    assert "efficient frontier" in invoke("frontier")


def test_a_short_backtest():
    output = invoke("backtest", "--paths", "1", "--months", "3")
    assert "tax-blind" in output and "Tax alpha" in output


def test_run_stores_and_reads_back():
    assert runner.invoke(app, ["rebalance", "stored"]).exit_code == 1  # nothing stored yet
    assert "Rebalance run" in invoke("run")
    assert "stored" in invoke("run", "--persist")
    assert "Read back from the database" in invoke("stored")
