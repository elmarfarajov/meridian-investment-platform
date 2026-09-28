"""The trade and report command groups, end to end."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", f"sqlite:///{(tmp_path / 'trade.sqlite').as_posix()}")
    reset_settings_cache()
    yield
    reset_settings_cache()


def invoke(*arguments: str) -> str:
    result = runner.invoke(app, list(arguments))
    assert result.exit_code == 0, result.stdout
    return result.stdout


def test_the_desk_views():
    assert "Blotter" in invoke("trade", "blotter")
    assert "child orders" in invoke("trade", "order", "DE-BAYN")
    assert runner.invoke(app, ["trade", "order", "NOPE"]).exit_code == 1
    assert "shortfall" in invoke("trade", "costs")
    assert "Algorithms compared" in invoke("trade", "algos")
    assert "Impact calibration" in invoke("trade", "calibrate")
    assert "Allocations to PF-BALANCED" in invoke("trade", "allocations", "--portfolio", "PF-BALANCED")
    assert runner.invoke(app, ["trade", "allocations", "--portfolio", "PF-NONE"]).exit_code == 1


def test_run_stores_and_reads_back():
    assert runner.invoke(app, ["trade", "stored"]).exit_code == 1
    assert "Trading-day run" in invoke("trade", "run")
    assert "stored" in invoke("trade", "run", "--persist")
    assert "Read back from the database" in invoke("trade", "stored")


def test_the_client_report_is_written(tmp_path):
    target = tmp_path / "pack.pdf"
    assert "client report written" in invoke("report", "client", "--out", str(target))
    assert target.read_bytes().startswith(b"%PDF")
    assert runner.invoke(app, ["report", "client", "--out", str(tmp_path / "pack.txt")]).exit_code == 1
