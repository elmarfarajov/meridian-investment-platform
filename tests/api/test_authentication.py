"""What an attacker can learn from a failed login, and what an account keeps after it is changed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meridian.api import routes
from meridian.api.app import create_app
from meridian.persistence import Database, UnitOfWork

ORDER = {"portfolio_id": "PF-GLOBAL-EQ", "instrument_id": "US-MSFT", "side": "buy", "amount": 100_000}


@pytest.fixture
def counted(monkeypatch):
    """Count the password hashes the sign-in endpoint computes: the work, and so the time, a failure takes."""
    calls: list[str] = []
    original = routes.verify_password

    def verify(password: str, stored: str) -> bool:
        calls.append(stored)
        return original(password, stored)

    monkeypatch.setattr(routes, "verify_password", verify)
    return calls


def set_user(settings, username: str, **changes) -> None:
    with Database(settings).session() as session:
        row = UnitOfWork(session).platform.user(username)
        for name, value in changes.items():
            setattr(row, name, value)
        session.commit()


@pytest.mark.parametrize(
    ("username", "password"),
    [("pm", "pm-demo-2026"), ("pm", "wrong-password"), ("nobody-by-this-name", "pm-demo-2026"), ("inactive", "x")],
)
def test_every_sign_in_computes_one_password_hash_whether_or_not_the_account_exists(
    client, counted, settings_factory, username, password
):
    """Day 9 hashed only for an account that existed and was active: a failure for anyone else came back at once.

    At 600,000 PBKDF2 iterations that is the difference between a few hundred
    milliseconds and none, and it told an attacker which usernames were real.
    """
    if username == "inactive":
        set_user(settings_factory(), "analyst", active=False)
        username = "analyst"
    client.post("/auth/token", data={"username": username, "password": password})
    assert len(counted) == 1


def test_a_deactivated_account_is_refused_at_once_not_when_its_token_expires(client, login, settings_factory):
    headers = login(client, "analyst")
    assert client.get("/auth/me", headers=headers).status_code == 200
    set_user(settings_factory(), "analyst", active=False)
    refused = client.get("/auth/me", headers=headers)
    assert refused.status_code == 401 and "not active" in refused.json()["detail"]


def test_a_changed_role_takes_effect_on_the_next_request(client, login, settings_factory):
    headers = login(client, "pm")
    assert client.post("/v1/orders", headers=headers, json=ORDER).status_code == 201
    set_user(settings_factory(), "pm", roles="analyst")  # moved off the desk: may no longer enter orders
    assert client.post("/v1/orders", headers=headers, json=ORDER).status_code == 403
    assert client.get("/auth/me", headers=headers).json()["roles"] == ["analyst"]


def test_a_token_for_an_account_that_was_removed_is_refused(tmp_path, fake, settings_factory):
    with TestClient(create_app(settings_factory(), fake)) as client:
        token = client.post("/auth/token", data={"username": "trader", "password": "trader-demo-2026"}).json()
        with Database(settings_factory()).session() as session:
            session.delete(UnitOfWork(session).platform.user("trader"))
            session.commit()
        refused = client.get("/auth/me", headers={"Authorization": f"Bearer {token['access_token']}"})
        assert refused.status_code == 401
