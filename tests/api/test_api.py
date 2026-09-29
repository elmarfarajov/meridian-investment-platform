"""The web platform end to end: authentication, permissions, entitlements, idempotency, four eyes, audit, metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient

from meridian.api.app import DEMO_USERS, RateLimiter, create_app
from meridian.api.security import DEVELOPMENT_SECRET, ROLES, Principal, issue_token
from meridian.persistence import Database, UnitOfWork
from meridian.persistence.models import AuditLogRow

ORDER = {"portfolio_id": "PF-GLOBAL-EQ", "instrument_id": "US-MSFT", "side": "buy", "amount": 100_000}


# ---------------------------------------------------------------------- system
def test_health_ready_and_the_openapi_contract(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready").json()
    assert ready == {"status": "ok", "version": ready["version"], "database": "ok", "audit_chain": "intact"}
    spec = client.get("/openapi.json").json()
    assert len(spec["paths"]) >= 18
    assert "/v1/orders" in spec["paths"] and "/v1/audit/verify" in spec["paths"]
    response = client.get("/health", headers={"X-Request-ID": "trace-me"})
    assert response.headers["X-Request-ID"] == "trace-me"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_metrics_count_requests_by_route_and_status(client, login):
    client.get("/v1/portfolios", headers=login(client, "analyst"))
    text = client.get("/metrics").text
    assert 'meridian_http_requests_total{method="GET",route="/v1/portfolios",status="200"}' in text
    assert "meridian_http_request_seconds_bucket" in text and "meridian_audit_records_total" in text


# ---------------------------------------------------------------------- authentication
def test_a_token_is_issued_for_the_right_password_only(client):
    good = client.post("/auth/token", data={"username": "analyst", "password": "analyst-demo-2026"})
    assert good.status_code == 200 and good.json()["roles"] == ["analyst"]
    wrong = client.post("/auth/token", data={"username": "analyst", "password": "wrong-password"})
    unknown = client.post("/auth/token", data={"username": "nobody", "password": "wrong-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]  # the answer does not reveal which was wrong
    assert wrong.headers["content-type"] == "application/problem+json"


def test_missing_forged_and_expired_tokens_are_refused(client):
    assert client.get("/v1/portfolios").status_code == 401
    forged, _ = issue_token(
        Principal("analyst", frozenset({"analyst"})), "another-secret-of-at-least-32-characters", 30
    )
    assert client.get("/v1/portfolios", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    expired, _ = issue_token(Principal("analyst", frozenset({"analyst"})), DEVELOPMENT_SECRET, 30, now=old)
    response = client.get("/v1/portfolios", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401 and "expired" in response.json()["detail"]


def test_me_reports_roles_and_permissions(client, login):
    me = client.get("/auth/me", headers=login(client, "aliyeva")).json()
    assert me["roles"] == ["client"] and me["portfolios"] == ["PF-GLOBAL-EQ"]
    assert set(me["permissions"]) == ROLES["client"]


# ---------------------------------------------------------------------- authorisation and entitlements
@pytest.mark.parametrize(
    ("username", "path", "status"),
    [
        ("analyst", "/v1/portfolios/PF-GLOBAL-EQ/risk", 200),
        ("aliyeva", "/v1/portfolios/PF-GLOBAL-EQ/valuation", 200),
        ("aliyeva", "/v1/portfolios/PF-GLOBAL-EQ/risk", 403),  # a client sees reports, not the risk model
        ("trader", "/v1/portfolios/PF-GLOBAL-EQ/compliance", 403),
        ("admin", "/v1/portfolios/PF-GLOBAL-EQ/valuation", 403),  # the administrator cannot read client data
        ("admin", "/v1/audit/verify", 200),
        ("analyst", "/v1/audit", 403),
        ("analyst", "/v1/portfolios/PF-UNKNOWN/valuation", 404),
        ("analyst", "/v1/portfolios/PF-BALANCED/valuation", 404),  # on the books, not analysed
    ],
)
def test_every_endpoint_checks_permission_and_entitlement(client, login, username, path, status):
    assert client.get(path, headers=login(client, username)).status_code == status


def test_a_client_sees_only_their_own_portfolios(client, login):
    headers = login(client, "aliyeva")
    listed = client.get("/v1/portfolios", headers=headers).json()
    assert [item["portfolio_id"] for item in listed] == ["PF-GLOBAL-EQ"]
    other = client.get("/v1/portfolios/PF-BALANCED/valuation", headers=headers)
    missing = client.get("/v1/portfolios/PF-NONE/valuation", headers=headers)
    assert other.status_code == missing.status_code == 404  # another client's portfolio looks like no portfolio


def test_bad_input_is_a_problem_not_a_crash(client, login):
    headers = login(client, "pm")
    assert client.get("/v1/portfolios/bad id!/valuation", headers=headers).status_code in (404, 422)
    negative = client.post("/v1/orders", headers=headers, json={**ORDER, "amount": -5})
    assert negative.status_code == 422 and "amount" in negative.json()["detail"]
    unknown = client.post(
        "/v1/portfolios/PF-GLOBAL-EQ/pretrade",
        headers=headers,
        json={"instrument_id": "UNKNOWN", "side": "buy", "amount": 10},
    )
    assert unknown.status_code == 422


# ---------------------------------------------------------------------- idempotency
def test_a_retried_write_is_done_once(client, login, fake):
    headers = {**login(client, "pm"), "Idempotency-Key": "rebalance-2026-09-18"}
    first = client.post("/v1/portfolios/PF-GLOBAL-EQ/rebalance-proposals", headers=headers)
    second = client.post("/v1/portfolios/PF-GLOBAL-EQ/rebalance-proposals", headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json() and second.headers["Idempotent-Replayed"] == "true"
    assert fake.calls.count("rebalance") == 1


def test_an_order_retried_after_a_timeout_is_entered_once(client, login):
    headers = {**login(client, "pm"), "Idempotency-Key": "order-7f3a9c21"}
    first = client.post("/v1/orders", headers=headers, json=ORDER)
    second = client.post("/v1/orders", headers=headers, json=ORDER)
    assert first.json()["order_id"] == second.json()["order_id"]
    assert len(client.get("/v1/orders", headers=login(client, "pm")).json()) == 1
    conflict = client.post("/v1/orders", headers=headers, json={**ORDER, "amount": 200_000})
    assert conflict.status_code == 409  # the same key for a different order


# ---------------------------------------------------------------------- orders and four eyes
def test_small_orders_are_approved_and_large_ones_wait_for_a_second_person(client, login):
    small = client.post("/v1/orders", headers=login(client, "trader"), json=ORDER).json()
    assert small["status"] == "approved" and small["pretrade_decision"] == "allowed"
    large = client.post("/v1/orders", headers=login(client, "pm"), json={**ORDER, "amount": 600_000}).json()
    assert large["status"] == "pending approval"
    decide = f"/v1/orders/{large['order_id']}/decision"
    assert client.post(decide, headers=login(client, "trader"), json={"approve": True}).status_code == 403
    approved = client.post(decide, headers=login(client, "compliance"), json={"approve": True, "note": "within limits"})
    assert approved.status_code == 200 and approved.json()["decided_by"] == "compliance"
    again = client.post(decide, headers=login(client, "compliance"), json={"approve": False})
    assert again.status_code == 409


def test_nobody_approves_their_own_order(tmp_path, fake, settings_factory):
    with TestClient(create_app(settings_factory(), fake)) as client:
        with Database(settings_factory()).session() as session:
            unit = UnitOfWork(session)
            from meridian.api.security import hash_password

            unit.platform.save_user(
                "both",
                "Both Hats",
                hash_password("both-demo-2026", iterations=1000),
                ["portfolio_manager", "compliance_officer"],
                None,
            )
            unit.commit()
        token = client.post("/auth/token", data={"username": "both", "password": "both-demo-2026"}).json()[
            "access_token"
        ]
        headers = {"Authorization": f"Bearer {token}"}
        order = client.post("/v1/orders", headers=headers, json={**ORDER, "amount": 900_000}).json()
        refused = client.post(f"/v1/orders/{order['order_id']}/decision", headers=headers, json={"approve": True})
        assert refused.status_code == 403 and "four eyes" in refused.json()["detail"]


def test_an_order_the_mandate_blocks_is_refused_with_the_largest_allowed(client, login):
    blocked = client.post("/v1/orders", headers=login(client, "pm"), json={**ORDER, "amount": 5_000_000})
    assert blocked.status_code == 422
    assert "issuer_limit" in blocked.json()["detail"] and "1,000,000" in blocked.json()["detail"]


# ---------------------------------------------------------------------- reports and trading
def test_the_client_downloads_their_report(client, login):
    response = client.get("/v1/portfolios/PF-GLOBAL-EQ/report.pdf", headers=login(client, "aliyeva"))
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert client.get("/v1/trading/costs", headers=login(client, "aliyeva")).status_code == 403
    assert client.get("/v1/trading/costs", headers=login(client, "trader")).json()["shortfall_bps"] == -7.9


# ---------------------------------------------------------------------- audit
def test_every_request_is_audited_and_the_chain_verifies(client, login):
    client.get("/v1/portfolios", headers=login(client, "analyst"))
    client.get("/v1/audit", headers=login(client, "analyst"))  # refused, and still audited
    page = client.get("/v1/audit?limit=500", headers=login(client, "compliance")).json()
    records = page["records"]
    assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))
    assert any(record["status"] == 403 and record["username"] == "analyst" for record in records)
    assert any(record["path"] == "/auth/token" and record["username"] is None for record in records) is False
    for earlier, later in pairwise(records):
        assert later["previous_hash"] == earlier["record_hash"]
    assert client.get("/v1/audit/verify", headers=login(client, "compliance")).json()["valid"] is True


def test_editing_the_audit_log_is_detected(client, login, settings_factory):
    client.get("/v1/portfolios", headers=login(client, "analyst"))
    with Database(settings_factory()).session() as session:
        row = session.get(AuditLogRow, 2)
        row.status = 200 if row.status != 200 else 204  # someone covers their tracks
        session.commit()
    check = client.get("/v1/audit/verify", headers=login(client, "compliance")).json()
    assert check["valid"] is False and check["first_broken"] == 2
    assert client.get("/ready").status_code == 503


def test_the_audit_log_pages_by_cursor(client, login):
    headers = login(client, "compliance")
    for _ in range(5):
        client.get("/health")
    first = client.get("/v1/audit?limit=3", headers=headers).json()
    assert len(first["records"]) == 3 and first["next_after"] == 3
    second = client.get(f"/v1/audit?limit=3&after={first['next_after']}", headers=headers).json()
    assert second["records"][0]["sequence"] == 4


# ---------------------------------------------------------------------- limits and configuration
def test_the_rate_limit_answers_429_with_retry_after(tmp_path, fake, settings_factory):
    with TestClient(create_app(settings_factory(api_rate_limit=3), fake)) as client:
        token = client.post("/auth/token", data={"username": "analyst", "password": "analyst-demo-2026"}).json()[
            "access_token"
        ]
        headers = {"Authorization": f"Bearer {token}"}
        statuses = [client.get("/v1/portfolios", headers=headers).status_code for _ in range(5)]
        assert statuses[:3] == [200, 200, 200] and statuses[3] == 429
        limited = client.get("/v1/portfolios", headers=headers)
        assert int(limited.headers["Retry-After"]) >= 1


def test_the_token_bucket_refills():
    limiter = RateLimiter(60)
    assert all(limiter.take("u", now=0.0) == 0.0 for _ in range(60))
    assert limiter.take("u", now=0.0) > 0
    assert limiter.take("u", now=2.0) == 0.0  # one a second comes back


def test_production_refuses_the_development_key(settings_factory, fake):
    with pytest.raises(RuntimeError, match="development signing key"):
        create_app(settings_factory(environment="production"), fake)
    with pytest.raises(RuntimeError, match="32 characters"):
        create_app(settings_factory(jwt_secret="short"), fake)
    assert len(DEMO_USERS) == len(ROLES)
