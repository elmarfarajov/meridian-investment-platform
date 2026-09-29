"""The platform command group: users, the audit chain and the OpenAPI document."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from meridian.cli import app
from meridian.config import reset_settings_cache

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", f"sqlite:///{(tmp_path / 'platform.sqlite').as_posix()}")
    monkeypatch.setenv("MERIDIAN_PASSWORD_ITERATIONS", "1000")
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_users_are_added_and_listed():
    assert runner.invoke(app, ["platform", "users"]).exit_code == 1  # nobody yet
    added = runner.invoke(
        app,
        [
            "platform",
            "add-user",
            "leyla",
            "--roles",
            "client",
            "--portfolios",
            "PF-GLOBAL-EQ",
            "--password",
            "a-long-password",
        ],
    )
    assert added.exit_code == 0, added.stdout
    listed = runner.invoke(app, ["platform", "users"])
    assert "leyla" in listed.stdout and "PF-GLOBAL-EQ" in listed.stdout
    wrong = runner.invoke(app, ["platform", "add-user", "x", "--roles", "wizard", "--password", "a-long-password"])
    assert wrong.exit_code == 1


def test_an_empty_audit_chain_verifies():
    result = runner.invoke(app, ["platform", "verify-audit"])
    assert result.exit_code == 0 and "chain intact" in result.stdout


def test_the_openapi_document_is_written(tmp_path):
    target = tmp_path / "openapi.json"
    result = runner.invoke(app, ["platform", "openapi", "--out", str(target)])
    assert result.exit_code == 0
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["info"]["title"] == "Meridian Investment Platform API" and len(document["paths"]) >= 18
