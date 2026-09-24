"""The book command group, end to end."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture
def database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", f"sqlite:///{(tmp_path / 'book.sqlite').as_posix()}")
    reset_settings_cache()
    yield
    reset_settings_cache()


def invoke(*arguments: str):
    result = runner.invoke(app, ["book", *arguments])
    assert result.exit_code == 0, result.stdout
    return result.stdout


def test_run_dry_passes_its_controls():
    output = invoke("run")
    assert "journal entries" in output and "passed" in output and "FAILED" not in output


def test_run_persist_then_the_trial_balance_from_sql(database_url):
    assert "passed" in invoke("run", "--persist")
    output = invoke("trial-balance", "--from-db")
    assert "from the database" in output and "Contributed capital" in output
    assert "Investments at cost" in invoke("trial-balance", "--as-of", "2025-06-30")


def test_trial_balance_from_an_empty_database_explains_what_to_do(database_url):
    result = runner.invoke(app, ["book", "trial-balance", "--from-db"])
    assert result.exit_code == 1


def test_positions_lots_and_cash():
    assert "NAV" in invoke("positions", "--as-of", "2026-06-30")
    assert "Tax basis" in invoke("lots", "DE-BAYN")
    assert "Settled" in invoke("cash", "--as-of", "2024-04-02")
    assert runner.invoke(app, ["book", "lots", "NOPE"]).exit_code == 1
    assert runner.invoke(app, ["book", "positions", "--as-of", "yesterday"]).exit_code == 1


def test_gains_under_both_codes_and_form_8949():
    assert "Schedule D" in invoke("gains")
    assert "section 104" in invoke("gains", "--regime", "uk")
    assert "Form 8949" in invoke("gains", "--year", "2025", "--form-8949")
    assert runner.invoke(app, ["book", "gains", "--regime", "fr"]).exit_code == 1


def test_lot_choice_nav_journal_and_wash_sales():
    assert "Minimum tax" in invoke("lot-choice", "US-MSFT", "100")
    assert "NAV" in invoke("nav", "--every", "60")
    assert "Debit" in invoke("journal", "-n", "2")
    assert "Wash sales" in invoke("wash-sales")
    assert runner.invoke(app, ["book", "journal", "--source", "NOPE"]).exit_code == 1


def test_bridge_writes_the_waterfall(tmp_path):
    chart = tmp_path / "waterfall.png"
    output = invoke("bridge", "--chart", str(chart))
    assert "Residual" in output and "Closing NAV" in output
    assert chart.stat().st_size > 20_000


def test_reconcile_on_a_day_and_with_the_dashboard(tmp_path):
    chart = tmp_path / "rec.png"
    output = invoke("reconcile", "--chart", str(chart))
    assert "recall" in output and "100%" in output and "failed settlement" in output
    assert chart.stat().st_size > 20_000
    assert "Breaks on 2026-04-08" in invoke("reconcile", "--as-of", "2026-04-08")
    assert runner.invoke(app, ["book", "reconcile", "--as-of", "2020-01-02"]).exit_code == 1
