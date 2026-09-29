"""A working day on the platform: seven people, the real modules, every control exercised.

The web layer is only as good as what it does under use, so the demonstration
drives it the way a firm would - through HTTP, against the real modules, with
the real controls in the way:

* the **client** reads her valuation, performance and report, and tries once to
  look at the risk model she is not entitled to;
* the **analyst** reads everything analytical;
* the **portfolio manager** checks orders before sending them, proposes the
  rebalance (and, once, retries the request after a "timeout"), and enters
  orders - some small, some over the four-eyes threshold, one the mandate
  blocks;
* the **trader** enters orders and reads trading costs;
* the **compliance officer** approves or rejects what is waiting, reads the
  audit log and verifies its chain;
* the **administrator** verifies the chain;
* an **intruder** guesses passwords and presents a forged token.

Every request is timed. The platform's own Prometheus metrics and audit log
are read back at the end, so the charts show what the platform recorded about
itself, not what the script believes happened.
"""

from __future__ import annotations

import random
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache, partial
from pathlib import Path
from typing import Any

from ..api.security import Principal, issue_token

WORKLOAD_SEED = 9
ROUNDS = 40
PASSWORDS = {
    "aliyeva": "client-demo-2026",
    "analyst": "analyst-demo-2026",
    "pm": "pm-demo-2026",
    "trader": "trader-demo-2026",
    "compliance": "compliance-demo-2026",
    "admin": "admin-demo-2026",
}
ROUTE_PATTERNS = (
    (re.compile(r"/v1/orders/ORD-\d+/decision"), "/v1/orders/{id}/decision"),
    (re.compile(r"/v1/portfolios/PF-[A-Z0-9-]+"), "/v1/portfolios/{id}"),
)


def route_of(path: str) -> str:
    for pattern, template in ROUTE_PATTERNS:
        path = pattern.sub(template, path)
    return path


@dataclass(frozen=True)
class Sample:
    user: str
    method: str
    route: str
    status: int
    milliseconds: float
    started: float  # seconds after the day began


@dataclass
class WorkloadResult:
    samples: list[Sample]
    metrics_text: str
    audit_records: int
    chain_valid: bool
    verify_milliseconds: float
    orders: list[dict[str, Any]] = field(default_factory=list)
    login_milliseconds: float = 0.0

    def by_route(self) -> dict[str, list[float]]:
        output: dict[str, list[float]] = {}
        for sample in self.samples:
            output.setdefault(f"{sample.method} {sample.route}", []).append(sample.milliseconds)
        return output

    def statuses(self) -> dict[int, int]:
        output: dict[int, int] = {}
        for sample in self.samples:
            output[sample.status] = output.get(sample.status, 0) + 1
        return output


def run_workload(
    rounds: int = ROUNDS, seed: int = WORKLOAD_SEED, data: Any = None, directory: Path | None = None
) -> WorkloadResult:
    import logging

    from fastapi.testclient import TestClient

    from ..api.app import create_app
    from ..api.data import DemoPlatformData
    from ..config import Settings

    logging.getLogger("httpx").setLevel(logging.WARNING)
    directory = directory or Path(tempfile.mkdtemp(prefix="meridian-workload-"))
    settings = Settings(
        database_url=f"sqlite:///{(directory / 'platform.sqlite').as_posix()}",
        reports_dir=directory / "reports",
        api_rate_limit=10_000,
    )
    rng = random.Random(seed)
    samples: list[Sample] = []
    orders: list[dict[str, Any]] = []
    with TestClient(create_app(settings, data or DemoPlatformData())) as client:
        began = time.perf_counter()

        def call(user: str, method: str, path: str, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
            started = time.perf_counter()
            response = client.request(method, path, headers=headers, **kwargs)
            elapsed = (time.perf_counter() - started) * 1000.0
            samples.append(Sample(user, method, route_of(path), response.status_code, elapsed, started - began))
            return response

        tokens: dict[str, dict[str, str]] = {}
        login_started = time.perf_counter()
        for user, password in PASSWORDS.items():
            response = call(user, "POST", "/auth/token", data={"username": user, "password": password})
            tokens[user] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        login_ms = (time.perf_counter() - login_started) * 1000.0 / len(PASSWORDS)
        # warm the modules once, outside the measured day's statistics
        for path in ("valuation", "performance", "attribution", "risk", "compliance", "tax-lots"):
            client.get(f"/v1/portfolios/PF-GLOBAL-EQ/{path}", headers=tokens["analyst"])
        client.post("/v1/portfolios/PF-GLOBAL-EQ/rebalance-proposals", headers=tokens["pm"])
        client.get("/v1/trading/costs", headers=tokens["trader"])
        client.get("/v1/portfolios/PF-GLOBAL-EQ/report.pdf", headers=tokens["aliyeva"])
        samples.clear()
        began = time.perf_counter()

        instruments = ("US-MSFT", "US-AAPL", "US-JNJ", "DE-BAYN", "GB-BAE", "CH-ROG", "IE-IWDA", "US-IVV")
        forged, _ = issue_token(
            Principal("admin", frozenset({"administrator", "compliance_officer"})), "not-the-key-" * 4, 30
        )

        def client_day() -> None:
            h = tokens["aliyeva"]
            for path in ("valuation", "performance"):
                call("aliyeva", "GET", f"/v1/portfolios/PF-GLOBAL-EQ/{path}", h)
            if rng.random() < 0.25:
                call("aliyeva", "GET", "/v1/portfolios/PF-GLOBAL-EQ/report.pdf", h)
            if rng.random() < 0.1:
                call("aliyeva", "GET", "/v1/portfolios/PF-GLOBAL-EQ/risk", h)  # not entitled: 403
            if rng.random() < 0.05:
                call("aliyeva", "GET", "/v1/portfolios/PF-BALANCED/valuation", h)  # someone else's: 404

        def analyst_day() -> None:
            h = tokens["analyst"]
            for path in rng.sample(["valuation", "performance", "attribution", "risk", "compliance", "tax-lots"], 3):
                call("analyst", "GET", f"/v1/portfolios/PF-GLOBAL-EQ/{path}", h)
            call("analyst", "GET", "/v1/portfolios", h)

        def pm_day(number: int) -> None:
            h = tokens["pm"]
            instrument = rng.choice(instruments)
            amount = float(rng.choice([25_000, 60_000, 150_000, 400_000, 900_000, 2_500_000]))
            call(
                "pm",
                "POST",
                "/v1/portfolios/PF-GLOBAL-EQ/pretrade",
                h,
                json={"instrument_id": instrument, "side": "buy", "amount": amount},
            )
            order = {"portfolio_id": "PF-GLOBAL-EQ", "instrument_id": instrument, "side": "buy", "amount": amount}
            key = {**h, "Idempotency-Key": f"pm-order-{number:04d}"}
            response = call("pm", "POST", "/v1/orders", key, json=order)
            if response.status_code == 201:
                orders.append(response.json())
            if rng.random() < 0.15:  # a timeout, and the same order sent again
                call("pm", "POST", "/v1/orders", key, json=order)
            if number % 10 == 0:
                call(
                    "pm",
                    "POST",
                    "/v1/portfolios/PF-GLOBAL-EQ/rebalance-proposals",
                    {**h, "Idempotency-Key": f"rebalance-{number:04d}"},
                )

        def trader_day(number: int) -> None:
            h = tokens["trader"]
            call("trader", "GET", "/v1/trading/costs", h)
            if rng.random() < 0.5:
                amount = float(rng.choice([20_000, 80_000, 300_000]))
                response = call(
                    "trader",
                    "POST",
                    "/v1/orders",
                    {**h, "Idempotency-Key": f"trader-order-{number:04d}"},
                    json={
                        "portfolio_id": "PF-GLOBAL-EQ",
                        "instrument_id": rng.choice(instruments[1:]),
                        "side": "buy",
                        "amount": amount,
                    },
                )
                if response.status_code == 201:
                    orders.append(response.json())

        def compliance_day() -> None:
            h = tokens["compliance"]
            pending = [
                item
                for item in call("compliance", "GET", "/v1/orders", h).json()
                if item["status"] == "pending approval"
            ]
            for item in pending[:3]:
                approve = rng.random() < 0.8
                call(
                    "compliance",
                    "POST",
                    f"/v1/orders/{item['order_id']}/decision",
                    h,
                    json={"approve": approve, "note": "within limits" if approve else "too concentrated"},
                )
            if rng.random() < 0.3:
                call("compliance", "GET", "/v1/audit?limit=100", h)
            call("compliance", "GET", "/v1/portfolios/PF-GLOBAL-EQ/compliance", h)

        def admin_day() -> None:
            if rng.random() < 0.2:
                call("admin", "GET", "/v1/audit/verify", tokens["admin"])
            if rng.random() < 0.1:
                call("admin", "GET", "/v1/portfolios/PF-GLOBAL-EQ/valuation", tokens["admin"])  # 403: no client data

        def intruder_day() -> None:
            if rng.random() < 0.3:
                call(
                    "intruder",
                    "POST",
                    "/auth/token",
                    data={"username": "compliance", "password": rng.choice(["password", "letmein1", "compliance"])},
                )
            if rng.random() < 0.15:
                call("intruder", "GET", "/v1/audit", {"Authorization": f"Bearer {forged}"})

        for number in range(1, rounds + 1):
            actions: list[tuple[str, Callable[[], Any]]] = [
                ("client", client_day),
                ("analyst", analyst_day),
                ("pm", partial(pm_day, number)),
                ("trader", partial(trader_day, number)),
                ("compliance", compliance_day),
                ("admin", admin_day),
                ("intruder", intruder_day),
            ]
            rng.shuffle(actions)
            for _, action in actions:
                action()
            call("monitor", "GET", "/health")
        metrics_text = client.get("/metrics").text
        started = time.perf_counter()
        check = client.get("/v1/audit/verify", headers=tokens["compliance"]).json()
        verify_ms = (time.perf_counter() - started) * 1000.0
        final_orders = client.get("/v1/orders?limit=500", headers=tokens["compliance"]).json()
    return WorkloadResult(samples, metrics_text, check["records"], check["valid"], verify_ms, final_orders, login_ms)


@lru_cache(maxsize=1)
def demo_workload() -> WorkloadResult:
    return run_workload()
