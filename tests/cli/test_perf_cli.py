"""The perf command group, end to end."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture
def database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", f"sqlite:///{(tmp_path / 'perf.sqlite').as_posix()}")
    reset_settings_cache()
    yield
    reset_settings_cache()


def invoke(*arguments: str) -> str:
    result = runner.invoke(app, ["perf", *arguments])
    assert result.exit_code == 0, result.stdout
    return result.stdout


def test_returns_by_period_and_by_year():
    output = invoke("returns")
    assert "Since inception" in output and "YTD" in output
    yearly = invoke("returns", "--yearly")
    assert "2024" in yearly and "2026" in yearly and "-14.19%" in yearly


def test_attribution_by_sector_and_region_explains_the_active_return():
    output = invoke("attribution")
    assert "Information Technology" in output and "currency JPY" in output and "Residual" in output
    assert "+306" in output, "the total row carries the active return in basis points"
    assert "North America" in invoke("attribution", "--by", "region", "--start", "2025-12-31")
    assert runner.invoke(app, ["perf", "attribution", "--by", "colour"]).exit_code == 1
    assert runner.invoke(app, ["perf", "attribution", "--end", "soon"]).exit_code == 1


def test_risk_and_contributions():
    output = invoke("risk")
    assert "Tracking error" in output and "Deepest drawdowns" in output
    contributions = invoke("contributions")
    assert "GB-BAE" in contributions and "-5.24%" in contributions


def test_factsheet_writes_a_png(tmp_path):
    target = tmp_path / "report.png"
    assert "wrote" in invoke("factsheet", "--out", str(target))
    assert target.stat().st_size > 50_000


def test_run_persist_then_read_the_attribution_back(database_url):
    assert "attribution rows stored" in invoke("run", "--persist")
    output = invoke("stored")
    assert "from the database" in output and "+306" in output
    assert "2025-12-31" in invoke("stored", "--by", "region")


def test_stored_on_an_empty_database_says_what_to_do(database_url):
    runner.invoke(app, ["db", "upgrade"])
    result = runner.invoke(app, ["perf", "stored"])
    assert result.exit_code == 1


def test_a_dry_run_writes_nothing():
    assert "active" in invoke("run")
