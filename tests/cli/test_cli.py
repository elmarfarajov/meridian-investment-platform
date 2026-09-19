"""The CLI is what an operations team touches, so its exit codes matter."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture
def database_url(tmp_path, monkeypatch) -> Iterator[str]:
    url = f"sqlite:///{(tmp_path / 'cli.sqlite').as_posix()}"
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", url)
    monkeypatch.setenv("MERIDIAN_REPORTS_DIR", str(tmp_path / "reports"))
    reset_settings_cache()
    yield url
    reset_settings_cache()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "meridian" in result.stdout


def test_info_shows_the_effective_configuration(database_url: str):
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "base currency" in result.stdout
    assert "sqlite" in result.stdout


def test_calendar_list_and_holidays():
    listed = runner.invoke(app, ["calendar", "list"])
    assert listed.exit_code == 0
    assert "XNYS" in listed.stdout and "TARGET" in listed.stdout

    holidays = runner.invoke(app, ["calendar", "holidays", "XNYS", "--year", "2026"])
    assert holidays.exit_code == 0
    assert "2026-07-03" in holidays.stdout  # Independence Day observed on the Friday
    assert "10 closures" in holidays.stdout


def test_an_unknown_calendar_fails_cleanly():
    result = runner.invoke(app, ["calendar", "holidays", "XNOPE"])
    assert result.exit_code == 1


def test_settlement_skips_the_christmas_closure():
    result = runner.invoke(app, ["calendar", "settle", "2026-12-24", "--calendar", "XNYS", "--days", "2"])
    assert result.exit_code == 0
    assert "2026-12-29" in result.stdout


def test_calendar_chart_writes_a_file(tmp_path):
    destination = tmp_path / "calendar.png"
    result = runner.invoke(app, ["calendar", "chart", "--year", "2026", "--out", str(destination)])
    assert result.exit_code == 0
    assert destination.exists()


def test_security_validation_reports_both_outcomes():
    result = runner.invoke(app, ["security", "validate", "US0378331005", "US0378331006"])
    assert result.exit_code == 0
    assert "valid" in result.stdout
    assert "invalid" in result.stdout


def test_cusip_to_isin():
    result = runner.invoke(app, ["security", "to-isin", "037833100"])
    assert result.exit_code == 0
    assert "US0378331005" in result.stdout


def test_init_seed_and_status_round_trip(database_url: str):
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    seeded = runner.invoke(app, ["db", "seed"])
    assert seeded.exit_code == 0
    assert "instruments" in seeded.stdout

    status = runner.invoke(app, ["db", "status"])
    assert status.exit_code == 0
    assert "transactions" in status.stdout
    assert "12" in status.stdout  # the twelve seeded instruments


def test_seeding_twice_does_not_duplicate(database_url: str):
    runner.invoke(app, ["db", "init", "--create-all"])
    runner.invoke(app, ["db", "seed"])
    runner.invoke(app, ["db", "seed"])
    status = runner.invoke(app, ["db", "status"])
    assert status.exit_code == 0
    assert " 24 " not in status.stdout  # instruments were upserted, not doubled
