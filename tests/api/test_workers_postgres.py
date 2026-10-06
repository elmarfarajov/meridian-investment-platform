"""The platform as it is deployed: several Uvicorn workers, one PostgreSQL, many requests at once.

The unit tests force each race with a barrier inside one process. Here nothing
is forced: four worker processes share one database, so a lock inside one
process protects nothing, and only what the database itself enforces holds.
Every request is sent at the same moment as many others, and the platform's
promises are checked afterwards:

- every order has its own number;
- one Idempotency-Key, sent twenty times at once, enters one order;
- of two approvers deciding one order at once, exactly one decides it;
- the audit chain is unbroken, one record per request.

The test makes its own database and drops it afterwards.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from meridian.config import Settings
from meridian.core.audit_chain import verify
from meridian.persistence import Database, UnitOfWork

pytestmark = pytest.mark.integration

WORKERS = 4
ORDER = {"portfolio_id": "PF-GLOBAL-EQ", "instrument_id": "US-MSFT", "side": "buy", "amount": 100_000}


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    base = os.environ.get("MERIDIAN_DATABASE_URL", "")
    if not base.startswith("postgresql"):
        pytest.skip("needs MERIDIAN_DATABASE_URL to point at PostgreSQL")
    url = make_url(base)
    name = f"meridian_workers_{uuid.uuid4().hex[:8]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    created = url.set(database=name).render_as_string(hide_password=False)
    Database(Settings(database_url=created)).create_all().dispose()  # the schema before the workers race to make it
    try:
        yield created
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="module")
def server(database_url: str, tmp_path_factory) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = {
        **os.environ,
        "MERIDIAN_DATABASE_URL": database_url,
        "MERIDIAN_PASSWORD_ITERATIONS": "1000",
        "MERIDIAN_API_RATE_LIMIT": "100000",
        "MERIDIAN_REPORTS_DIR": str(tmp_path_factory.mktemp("reports")),
    }
    command = [sys.executable, "-m", "uvicorn", "workers_app:app", "--app-dir", str(Path(__file__).parent)]
    command += ["--host", "127.0.0.1", "--port", str(port), "--workers", str(WORKERS), "--log-level", "warning"]
    process = subprocess.Popen(command, env=environment)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            pytest.fail("the workers did not start")
        time.sleep(2)  # every worker up, not only the first
        yield base
    finally:
        process.terminate()
        process.wait(timeout=30)


def token(base: str, username: str) -> dict[str, str]:
    response = httpx.post(f"{base}/auth/token", data={"username": username, "password": f"{username}-demo-2026"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def at_once(calls: list[Callable[[], httpx.Response]]) -> list[httpx.Response]:
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(lambda call: call(), calls))


def poster(base: str, path: str, headers: dict[str, str], body: Any) -> Callable[[], httpx.Response]:
    return lambda: httpx.post(f"{base}{path}", headers=headers, json=body, timeout=60)


def test_sixty_orders_at_once_get_sixty_numbers(server):
    pm, trader = token(server, "pm"), token(server, "trader")
    responses = at_once([poster(server, "/v1/orders", pm if n % 2 else trader, ORDER) for n in range(60)])
    assert [r.status_code for r in responses] == [201] * 60, [r.text for r in responses if r.status_code != 201]
    assert len({r.json()["order_id"] for r in responses}) == 60


def test_one_key_sent_twenty_times_at_once_enters_one_order(server):
    headers = {**token(server, "pm"), "Idempotency-Key": f"workers-{uuid.uuid4().hex}"}
    before = len(httpx.get(f"{server}/v1/orders?limit=500", headers=headers).json())
    responses = at_once([poster(server, "/v1/orders", headers, ORDER) for _ in range(20)])
    assert [r.status_code for r in responses] == [201] * 20, [r.text for r in responses if r.status_code != 201]
    assert len({r.json()["order_id"] for r in responses}) == 1
    after = len(httpx.get(f"{server}/v1/orders?limit=500", headers=headers).json())
    assert after == before + 1


def test_two_approvers_at_once_one_decision(server):
    pm = token(server, "pm")
    large = [poster(server, "/v1/orders", pm, {**ORDER, "amount": 600_000}) for _ in range(10)]
    pending = [r.json()["order_id"] for r in at_once(large)]
    # the demonstration has one compliance officer: two sessions of theirs, on two screens, deciding at once
    screen, other_screen = token(server, "compliance"), token(server, "compliance")
    for order_id in pending:
        path = f"/v1/orders/{order_id}/decision"
        results = at_once(
            [poster(server, path, screen, {"approve": True}), poster(server, path, other_screen, {"approve": False})]
        )
        assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]


def test_the_audit_chain_is_unbroken_after_it_all(server, database_url):
    ready = httpx.get(f"{server}/ready").json()
    assert ready["audit_chain"] == "intact"
    with Database(Settings(database_url=database_url)).session() as session:
        records = UnitOfWork(session).platform.records()
    check = verify(records)
    assert check.valid and check.records >= 118  # the requests these tests sent, every one recorded
    assert [record.sequence for record in records] == list(range(1, len(records) + 1))
