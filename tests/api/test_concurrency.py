"""Requests that arrive together: each race is forced, so the test fails every time the code is wrong.

A race needs two requests to read before either writes. Left to the scheduler
that happens rarely and a test of it is flaky; here a barrier holds each
request at the read until the other has read too, which is the interleaving
that breaks a check-then-act.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from meridian.api.app import create_app
from meridian.api.security import hash_password
from meridian.persistence import Database, UnitOfWork
from meridian.persistence.platform_repositories import PlatformRepository

ORDER = {"portfolio_id": "PF-GLOBAL-EQ", "instrument_id": "US-MSFT", "side": "buy", "amount": 100_000}


def hold_at(monkeypatch: pytest.MonkeyPatch, name: str, parties: int = 2) -> None:
    """Make every caller of ``PlatformRepository.<name>`` wait there until ``parties`` callers have arrived."""
    barrier = threading.Barrier(parties, timeout=3)
    original = getattr(PlatformRepository, name)

    def held(self: PlatformRepository, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        # if the code serialised the callers before they got here, the barrier breaks: a pass, not a hang
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        return result

    monkeypatch.setattr(PlatformRepository, name, held)


def together(*calls: Callable[[], Any]) -> list[Any]:
    results: list[Any] = [None] * len(calls)

    def run(index: int) -> None:
        results[index] = calls[index]()

    threads = [threading.Thread(target=run, args=(index,)) for index in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


@pytest.fixture
def app(tmp_path, fake, settings_factory):
    application = create_app(settings_factory(), fake)
    with TestClient(application):  # starts the app: tables and demonstration users
        pass
    with Database(settings_factory()).session() as session:
        unit = UnitOfWork(session)
        unit.platform.save_user(
            "compliance2",
            "Second Officer",
            hash_password("compliance2-demo-2026", iterations=1_000),
            ["compliance_officer"],
            None,
        )
        unit.commit()
    return application


def bearer(application, username: str, password: str | None = None) -> dict[str, str]:
    with TestClient(application) as client:
        response = client.post(
            "/auth/token", data={"username": username, "password": password or f"{username}-demo-2026"}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


def post(application, path: str, headers: dict[str, str], json: Any) -> Callable[[], Any]:
    def call() -> Any:
        with TestClient(application) as client:
            return client.post(path, headers=headers, json=json)

    return call


def orders(application, headers: dict[str, str]) -> list[dict[str, Any]]:
    with TestClient(application) as client:
        return list(client.get("/v1/orders", headers=headers).json())


def test_two_orders_entered_at_once_get_two_numbers(app, monkeypatch):
    pm, trader = bearer(app, "pm"), bearer(app, "trader")
    hold_at(monkeypatch, "next_order_id")
    first, second = together(post(app, "/v1/orders", pm, ORDER), post(app, "/v1/orders", trader, ORDER))
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    assert first.json()["order_id"] != second.json()["order_id"]
    assert len(orders(app, pm)) == 2


def test_the_same_order_sent_twice_at_once_is_entered_once(app, monkeypatch):
    headers = {**bearer(app, "pm"), "Idempotency-Key": "order-race-0001"}
    hold_at(monkeypatch, "idempotent")
    first, second = together(post(app, "/v1/orders", headers, ORDER), post(app, "/v1/orders", headers, ORDER))
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    assert first.json()["order_id"] == second.json()["order_id"]
    assert len(orders(app, bearer(app, "pm"))) == 1


def test_two_approvers_at_once_cannot_both_decide(app, monkeypatch):
    pm = bearer(app, "pm")
    with TestClient(app) as client:
        large = client.post("/v1/orders", headers=pm, json={**ORDER, "amount": 600_000}).json()
    path = f"/v1/orders/{large['order_id']}/decision"
    hold_at(monkeypatch, "order")
    approve, reject = together(
        post(app, path, bearer(app, "compliance"), {"approve": True}),
        post(app, path, bearer(app, "compliance2"), {"approve": False}),
    )
    statuses = sorted([approve.status_code, reject.status_code])
    assert statuses == [200, 409], (approve.text, reject.text)  # one decides; the other is told it was decided
    winner = approve if approve.status_code == 200 else reject
    final = next(item for item in orders(app, pm) if item["order_id"] == large["order_id"])
    assert final["status"] == winner.json()["status"] and final["decided_by"] == winner.json()["decided_by"]
