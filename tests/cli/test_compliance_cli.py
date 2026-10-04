"""The compliance command group, end to end."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture
def database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", f"sqlite:///{(tmp_path / 'compliance.sqlite').as_posix()}")
    reset_settings_cache()
    yield
    reset_settings_cache()


def invoke(*arguments: str) -> str:
    result = runner.invoke(app, ["compliance", *arguments])
    assert result.exit_code == 0, result.stdout
    return result.stdout


def test_rules_and_parse():
    assert "Global Equity Core" in invoke("rules")
    assert "hard rule" in invoke("parse", 'rule cap hard weight where sector = "Energy" <= 5%')
    failed = runner.invoke(app, ["compliance", "parse", "rule cap hard max weight by colour <= 5%"])
    assert failed.exit_code == 1


def test_check_today_and_a_past_day():
    assert "14 pass" in invoke("check")
    assert "breach" in invoke("check", "--as-of", "2025-03-14")
    assert runner.invoke(app, ["compliance", "check", "--as-of", "2023-01-02"]).exit_code == 1
    assert runner.invoke(app, ["compliance", "check", "--as-of", "soon"]).exit_code == 1


def test_pretrade_blocks_and_allows():
    blocked = invoke("pretrade", "US-MSFT", "100000")
    assert "blocked" in blocked and "85,976" in blocked
    assert "allowed" in invoke("pretrade", "US-MSFT", "50000", "--side", "sell")
    assert runner.invoke(app, ["compliance", "pretrade", "US-MSFT", "9000000", "--side", "sell"]).exit_code == 1


def test_register_replay_and_ucits():
    assert "37 breaches" in invoke("breaches")
    assert "no breaches" in invoke("breaches", "--open")
    assert "historical orders" in invoke("replay")
    assert "breach" in invoke("ucits")


def test_report_writes_a_png(tmp_path):
    target = tmp_path / "report.png"
    assert "wrote" in invoke("report", "--out", str(target))
    assert target.stat().st_size > 50_000


def test_run_persist_then_recount(database_url):
    assert "breaches in the register" in invoke("run", "--persist")
    output = invoke("stored")
    assert "results: pass" in output and "days in breach" in output


def test_stored_on_an_empty_database_says_what_to_do(database_url):
    runner.invoke(app, ["db", "upgrade"])
    assert runner.invoke(app, ["compliance", "stored"]).exit_code == 1
