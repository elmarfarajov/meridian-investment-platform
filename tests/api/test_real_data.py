"""The API over the real modules: a number served over HTTP is the number the modules compute."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meridian.api.app import create_app
from meridian.api.data import DemoPlatformData


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import make_settings  # type: ignore[import-not-found]

    with TestClient(create_app(make_settings(tmp_path_factory.mktemp("real")), DemoPlatformData())) as client:
        token = client.post("/auth/token", data={"username": "compliance", "password": "compliance-demo-2026"}).json()
        pm = client.post("/auth/token", data={"username": "pm", "password": "pm-demo-2026"}).json()
        yield (
            client,
            {"Authorization": f"Bearer {token['access_token']}"},
            {"Authorization": f"Bearer {pm['access_token']}"},
        )


def test_the_valuation_is_the_books(real):
    from meridian.services.demo_optimisation import build_demo_optimisation

    client, headers, _ = real
    valuation = client.get("/v1/portfolios/PF-GLOBAL-EQ/valuation", headers=headers).json()
    assert valuation["nav"] == pytest.approx(float(build_demo_optimisation().valuation.nav))
    assert sum(item["weight"] for item in valuation["positions"]) + valuation["cash"] / valuation[
        "nav"
    ] == pytest.approx(1.0)


def test_risk_compliance_and_performance_are_the_modules(real):
    client, headers, _ = real
    risk = client.get("/v1/portfolios/PF-GLOBAL-EQ/risk", headers=headers).json()
    assert risk["tracking_error"] == pytest.approx(0.058, abs=0.002)
    compliance = client.get("/v1/portfolios/PF-GLOBAL-EQ/compliance", headers=headers).json()
    assert len(compliance["rules"]) == 18
    performance = client.get("/v1/portfolios/PF-GLOBAL-EQ/performance", headers=headers).json()
    assert any(row["period"] == "Since inception" for row in performance["periods"])


def test_the_day6_pretrade_answer_comes_through_the_api(real):
    client, headers, _ = real
    decision = client.post(
        "/v1/portfolios/PF-GLOBAL-EQ/pretrade",
        headers=headers,
        json={"instrument_id": "US-MSFT", "side": "buy", "amount": 100_000},
    ).json()
    assert decision["decision"] == "blocked"
    assert decision["maximum"] == pytest.approx(85_976, abs=5)


def test_the_rebalance_is_the_day7_proposal(real):
    client, _, pm = real
    proposal = client.post("/v1/portfolios/PF-GLOBAL-EQ/rebalance-proposals", headers=pm).json()
    assert proposal["tracking_error_before"] == pytest.approx(0.058, abs=0.002)
    assert proposal["tax"] < 0 and len(proposal["orders"]) == 27
