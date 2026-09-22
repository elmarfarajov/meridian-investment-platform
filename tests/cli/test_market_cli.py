"""The market command group, end to end against a temporary database."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture
def database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", f"sqlite:///{(tmp_path / 'market.sqlite').as_posix()}")
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_rules_lists_the_catalogue():
    result = runner.invoke(app, ["market", "rules"])
    assert result.exit_code == 0
    assert "robust_outlier" in result.stdout and "completeness" in result.stdout


def test_quality_reports_scores_findings_and_writes_the_dashboard(tmp_path):
    chart = tmp_path / "dashboard.png"
    result = runner.invoke(app, ["market", "quality", "-n", "5", "--chart", str(chart)])
    assert result.exit_code == 0
    assert "US-MSFT" in result.stdout
    assert "critical" in result.stdout
    assert chart.stat().st_size > 10_000


def test_price_persist_then_read_history_as_known_at_a_past_date(database_url):
    priced = runner.invoke(app, ["market", "price", "--persist"])
    assert priced.exit_code == 0
    assert "golden prices" in priced.stdout
    then = runner.invoke(app, ["market", "history", "US-AAPL", "--known-at", "2026-09-10", "--tail", "2"])
    assert then.exit_code == 0
    assert "2026-09-10" in then.stdout and "2026-09-11" not in then.stdout
    before = runner.invoke(app, ["market", "history", "US-AAPL", "--known-at", "2020-01-01"])
    assert before.exit_code == 1


def test_history_without_a_load_explains_what_to_do(database_url):
    result = runner.invoke(app, ["market", "history", "US-AAPL"])
    assert result.exit_code == 1


def test_actions_and_adjust():
    actions = runner.invoke(app, ["market", "actions", "--instrument", "DEMO-SPLIT"])
    assert actions.exit_code == 0
    assert "0.250000" in actions.stdout  # the 4-for-1 split factor
    adjusted = runner.invoke(app, ["market", "adjust", "DEMO-SPLIT"])
    assert adjusted.exit_code == 0
    assert "2025-06-10" in adjusted.stdout
    missing = runner.invoke(app, ["market", "adjust", "NOPE"])
    assert missing.exit_code == 1


def test_xref_resolves_by_date():
    renamed = runner.invoke(app, ["market", "xref", "FB", "--on", "2021-06-01"])
    assert "US-META" in renamed.stdout
    reused = runner.invoke(app, ["market", "xref", "MRDN", "--on", "2018-01-02"])
    assert "DEMO-OLDCO" in reused.stdout
    nothing = runner.invoke(app, ["market", "xref", "MRDN", "--on", "2022-01-03"])
    assert "identified nothing" in nothing.stdout
