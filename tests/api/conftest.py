"""A platform to test the web layer against: a temporary database and a small, exact stand-in for the modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from meridian.api.app import create_app
from meridian.api.data import NotAvailable
from meridian.config import Settings
from meridian.core import ValidationError

PORTFOLIOS = ("PF-GLOBAL-EQ", "PF-BALANCED")


class FakeData:
    """Answers in the facade's shapes, with numbers chosen so the tests can assert them exactly."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _check(self, portfolio_id: str) -> None:
        if portfolio_id not in PORTFOLIOS:
            raise KeyError(portfolio_id)
        if portfolio_id != "PF-GLOBAL-EQ":
            raise NotAvailable(f"{portfolio_id} is on the books, but its analytics have not been run")

    def portfolios(self) -> list[dict[str, Any]]:
        return [
            {
                "portfolio_id": key,
                "name": key.title(),
                "base_currency": "USD",
                "benchmark_id": "MSCI-WORLD",
                "account_id": "AC-0001",
                "strategy": "global-equity",
                "inception": "2024-04-01",
                "analysed": key == "PF-GLOBAL-EQ",
            }
            for key in PORTFOLIOS
        ]

    def valuation(self, portfolio_id: str) -> dict[str, Any]:
        self._check(portfolio_id)
        self.calls.append("valuation")
        position = {
            "instrument_id": "US-MSFT",
            "quantity": 100.0,
            "price": 400.0,
            "currency": "USD",
            "market_value_base": 40_000.0,
            "weight": 0.8,
            "unrealised_long_term": 5_000.0,
            "unrealised_short_term": 0.0,
        }
        return {
            "portfolio_id": portfolio_id,
            "as_of": "2026-09-18",
            "nav": 50_000.0,
            "cash": 10_000.0,
            "positions": [position],
        }

    def performance(self, portfolio_id: str) -> dict[str, Any]:
        self._check(portfolio_id)
        return {
            "portfolio_id": portfolio_id,
            "periods": [{"period": "YTD", "portfolio": 0.1, "benchmark": 0.08, "annualised": False}],
            "calendar_years": [{"year": 2026, "portfolio": 0.1, "benchmark": 0.08}],
            "statistics": [{"measure": "Total return", "portfolio": "10.00%", "benchmark": "8.00%"}],
        }

    def attribution(self, portfolio_id: str) -> dict[str, Any]:
        self._check(portfolio_id)
        return {
            "portfolio_id": portfolio_id,
            "start": "2024-04-01",
            "end": "2026-09-18",
            "portfolio": 0.1,
            "benchmark": 0.08,
            "active": 0.02,
            "effects": {"allocation": 0.01, "selection": 0.01},
            "segments": [],
        }

    def risk(self, portfolio_id: str) -> dict[str, Any]:
        self._check(portfolio_id)
        return {
            "portfolio_id": portfolio_id,
            "as_of": "2026-09-18",
            "volatility": 0.12,
            "tracking_error": 0.05,
            "by_group": {"world": 0.1},
            "active_by_group": {"specific": 0.04},
            "value_at_risk": [],
            "stress": [],
        }

    def compliance(self, portfolio_id: str) -> dict[str, Any]:
        self._check(portfolio_id)
        return {
            "portfolio_id": portfolio_id,
            "as_of": "2026-09-18",
            "mandate": "Test, version 1",
            "rules": [],
            "open_breaches": 0,
        }

    def tax_lots(self, portfolio_id: str) -> dict[str, Any]:
        self._check(portfolio_id)
        return {"portfolio_id": portfolio_id, "as_of": "2026-09-18", "lots": []}

    def pretrade(self, portfolio_id: str, instrument_id: str, side: str, amount: float) -> dict[str, Any]:
        self._check(portfolio_id)
        if instrument_id == "UNKNOWN":
            raise ValidationError("UNKNOWN is not an instrument the platform knows")
        if amount > 1_000_000:
            return {
                "decision": "blocked",
                "maximum": 1_000_000.0,
                "reasons": [{"rule_id": "issuer_limit", "effect": "new breach", "before": 0.1, "after": 0.2}],
            }
        return {"decision": "allowed", "maximum": 1_000_000.0, "reasons": []}

    def rebalance(self, portfolio_id: str) -> dict[str, Any]:
        self._check(portfolio_id)
        self.calls.append("rebalance")
        return {
            "portfolio_id": portfolio_id,
            "as_of": "2026-09-18",
            "tracking_error_before": 0.058,
            "tracking_error_after": 0.026,
            "active_share_after": 0.30,
            "tax": -96_900.0,
            "cost": 4_800.0,
            "turnover": 1.13,
            "compliance": "warning",
            "orders": [],
        }

    def trading_costs(self) -> dict[str, Any]:
        return {
            "trade_date": "2026-09-21",
            "paper_value": 1.0,
            "shortfall_bps": -7.9,
            "components_bps": {"spread": 2.5},
            "blocks": [],
        }

    def client_report(self, portfolio_id: str, directory: Path) -> Path:
        self._check(portfolio_id)
        path = directory / f"client-report-{portfolio_id}.pdf"
        path.write_bytes(b"%PDF-1.4 test")
        return path


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values = {
        "database_url": f"sqlite:///{(tmp_path / 'platform.sqlite').as_posix()}",
        "reports_dir": tmp_path / "reports",
        "password_iterations": 1_000,
        "api_rate_limit": 1_000,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def fake() -> FakeData:
    return FakeData()


@pytest.fixture
def client(tmp_path, fake) -> TestClient:
    with TestClient(create_app(make_settings(tmp_path), fake)) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def login():
    cache: dict[tuple[int, str], dict[str, str]] = {}

    def headers(client: TestClient, username: str) -> dict[str, str]:
        key = (id(client), username)
        if key not in cache:
            response = client.post(
                "/auth/token",
                data={"username": username, "password": f"{'client' if username == 'aliyeva' else username}-demo-2026"},
            )
            assert response.status_code == 200, response.text
            cache[key] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        return cache[key]

    return headers


@pytest.fixture
def settings_factory(tmp_path):
    return lambda **overrides: make_settings(tmp_path, **overrides)
