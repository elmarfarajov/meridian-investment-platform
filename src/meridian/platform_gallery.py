"""The Day 9 charts: the platform's architecture, controls, behaviour under use, and how the project grew.

Everything shown is measured or read from the code: the role matrix and the
OpenAPI document from the application, the package graph from the source, the
working day from driving the API over HTTP, the growth from the release tags
(recorded in ``docs/data/growth.json``).
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from matplotlib.figure import Figure

from .viz.platform import (
    DashboardData,
    plot_access,
    plot_api_surface,
    plot_architecture,
    plot_audit_chain,
    plot_dashboard,
    plot_deployment,
    plot_four_eyes,
    plot_growth,
    plot_journey,
    plot_latency,
    plot_module_graph,
    plot_pipeline,
    plot_rbac,
    plot_security,
    plot_tests,
)

if TYPE_CHECKING:
    from .devtools.workload import WorkloadResult
    from .gallery import GalleryItem

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / "docs" / "images"
MODULES = (
    ("core, domain, analytics", "Day 1", "money, calendars, curves, bonds"),
    ("marketdata, quality, refdata", "Day 2", "point in time, golden copy"),
    ("accounting", "Day 3", "ledger, lots, tax, bridge"),
    ("performance", "Day 4", "returns, attribution"),
    ("risk", "Day 5", "factor model, VaR, stress"),
    ("compliance", "Day 6", "mandate language, breaches"),
    ("optimisation", "Day 7", "tax-aware rebalancing"),
    ("execution", "Day 8", "orders, algorithms, TCA"),
    ("reporting", "Day 8", "the client report"),
    ("persistence, services", "Days 1-9", "repositories, runs, controls"),
)
LAYERS = (
    ("core", "config"),
    ("domain", "analytics"),
    ("marketdata", "quality", "refdata", "accounting", "seed"),
    ("performance", "risk", "compliance", "optimisation", "execution", "persistence"),
    ("services", "viz"),
    ("api", "cli", "reporting", "gallery", "devtools"),
)
OWASP = (
    (
        "API1 Broken object level authorisation",
        "entitlements checked on every portfolio; others answered as absent (404)",
        "test_a_client_sees_only_their_own_portfolios",
    ),
    (
        "API2 Broken authentication",
        "PBKDF2-SHA256 600k, HS256 tokens with expiry and issuer, one message for any failure",
        "test_missing_forged_and_expired_tokens_are_refused",
    ),
    (
        "API3 Broken object property level authorisation",
        "response models with extra='forbid'; only declared fields leave",
        "test_health_ready_and_the_openapi_contract",
    ),
    (
        "API4 Unrestricted resource consumption",
        "token-bucket rate limit per user, 429 with Retry-After; bounded pages",
        "test_the_rate_limit_answers_429_with_retry_after",
    ),
    (
        "API5 Broken function level authorisation",
        "a permission on every endpoint, recorded in OpenAPI as x-permission",
        "test_every_endpoint_checks_permission_and_entitlement",
    ),
    (
        "API6 Unrestricted access to sensitive business flows",
        "four eyes above the threshold; nobody approves their own order",
        "test_nobody_approves_their_own_order",
    ),
    ("API7 Server-side request forgery", "no endpoint fetches a URL it is given", "(no such flow)"),
    (
        "API8 Security misconfiguration",
        "refuses to start in production with the development key; no stack traces in errors",
        "test_production_refuses_the_development_key",
    ),
    (
        "API9 Improper inventory management",
        "one versioned API (/v1), its OpenAPI document generated from the code",
        "meridian platform openapi",
    ),
    (
        "API10 Unsafe consumption of APIs",
        "inputs validated by schema; domain errors returned as problem details",
        "test_bad_input_is_a_problem_not_a_crash",
    ),
)
JOURNEY = (
    ("Day 1", "Foundation", "Bootstrapped curves and bond analytics", "curve-interpolation.png"),
    ("Day 2", "Market data", "Golden copy by ranked consensus, faults planted and found", "quality-dashboard.png"),
    ("Day 3", "Portfolio accounting", "A ledger whose value bridge has no residual", "valuation-waterfall.png"),
    ("Day 4", "Performance", "Brinson-Fachler, linked by Carino", "attribution-bridge.png"),
    ("Day 5", "Risk", "A factor model validated against known truth", "bias-statistics.png"),
    ("Day 6", "Compliance", "A mandate language, checked every day", "limit-utilisation.png"),
    ("Day 7", "Optimisation", "The frontier of tracking error against tax", "tax-frontier.png"),
    ("Day 8", "Execution", "Implementation shortfall, decomposed exactly", "implementation-shortfall.png"),
    ("Day 9", "Platform", "One API, audited, over all of it", "platform-architecture.png"),
)


@lru_cache(maxsize=1)
def _workload() -> WorkloadResult:
    from .devtools.workload import demo_workload

    return demo_workload()


def _app():  # type: ignore[no-untyped-def]
    import tempfile

    from .api.app import create_app
    from .config import Settings

    directory = Path(tempfile.mkdtemp(prefix="meridian-openapi-"))
    return create_app(Settings(database_url=f"sqlite:///{(directory / 'x.sqlite').as_posix()}"))


# ---------------------------------------------------------------------------- the design
def architecture_chart() -> Figure:
    from .persistence.base import Base

    tables = len(Base.metadata.tables)
    return plot_architecture(
        MODULES,
        {"tables": f"{tables} tables", "summary": f"{tables} tables in one schema, nine migrations, one image."},
    )


def rbac_chart() -> Figure:
    from .api.app import DEMO_USERS
    from .api.security import PERMISSIONS, ROLES, permission_matrix

    users = {roles[0]: username for username, _, roles, _, _ in DEMO_USERS}
    matrix = permission_matrix()
    return plot_rbac(list(ROLES), list(PERMISSIONS), [row for _, row in matrix], users)


def api_surface_chart() -> Figure:
    spec = _app().openapi()
    rows = []
    order = ["system", "auth", "portfolios", "rebalancing", "orders", "trading", "reports", "audit"]
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            tag = (operation.get("tags") or ["system"])[0]
            rows.append(
                (tag, method.upper(), path, operation.get("x-permission", "public"), operation.get("summary", ""))
            )
    rows.sort(key=lambda row: (order.index(row[0]) if row[0] in order else 99, row[2], row[1]))
    return plot_api_surface(rows)


def deployment_chart() -> Figure:
    return plot_deployment()


def module_graph_chart() -> Figure:
    from .devtools.structure import import_graph, package_stats, upward

    sizes = {item.name: item.lines for item in package_stats()}
    edges = import_graph()
    return plot_module_graph(LAYERS, sizes, edges, upward(edges, LAYERS))


# ---------------------------------------------------------------------------- behaviour under use
def pipeline_chart() -> Figure:
    workload = _workload()
    samples = workload.samples
    total = len(samples)
    unauthenticated = sum(1 for s in samples if s.status == 401)
    forbidden = sum(1 for s in samples if s.status == 403)
    hidden = sum(1 for s in samples if s.status == 404)
    limited = sum(1 for s in samples if s.status == 429)
    invalid = sum(1 for s in samples if s.status == 422)
    conflicts = sum(1 for s in samples if s.status == 409)
    replays = _replays(workload)
    stages = [
        ("authentication", unauthenticated, "no valid token"),
        ("authorisation", forbidden, "not permitted"),
        ("entitlement", hidden, "not entitled"),
        ("rate limit", limited, "over the limit"),
        ("idempotency", replays + conflicts, "idempotent replays"),
        ("the mandate", invalid, "blocked or invalid"),
    ]
    return plot_pipeline(stages, total)


def _replays(workload: WorkloadResult) -> int:
    seen: set[str] = set()
    replays = 0
    for order in workload.orders:
        seen.add(order["order_id"])
    # retried orders show up as a second 201 on POST /v1/orders beyond the number of distinct orders entered
    posts = sum(1 for s in workload.samples if s.route == "/v1/orders" and s.method == "POST" and s.status == 201)
    replays = max(posts - len(seen), 0)
    return replays


def latency_chart() -> Figure:
    workload = _workload()
    groups = {name: values for name, values in workload.by_route().items() if len(values) >= 3}
    return plot_latency(groups, workload.login_milliseconds)


def dashboard_chart() -> Figure:
    workload = _workload()
    samples = workload.samples
    end = max(sample.started for sample in samples)
    edges = np.arange(0.0, end + 1.0, 1.0)
    times = edges[:-1] + 0.5
    users = sorted({sample.user for sample in samples}, key=lambda user: -sum(1 for s in samples if s.user == user))
    by_user = {}
    for user in users:
        counts, _ = np.histogram([s.started for s in samples if s.user == user], bins=edges)
        by_user[user] = counts.astype(float)
    p50, p95 = np.zeros(len(times)), np.zeros(len(times))
    for index in range(len(times)):
        window = [s.milliseconds for s in samples if edges[index] <= s.started < edges[index + 1]]
        if window:
            p50[index], p95[index] = np.percentile(window, [50, 95])
    p50[p50 == 0] = np.nan
    p95[p95 == 0] = np.nan
    statuses = Counter(str(sample.status) for sample in samples)
    all_ms = [sample.milliseconds for sample in samples]
    refused = sum(1 for sample in samples if sample.status in (401, 403))
    tiles = [
        ("Requests", f"{len(samples):,}", "info"),
        ("Median latency", f"{np.median(all_ms):,.0f} ms", "good"),
        ("p95 latency", f"{np.percentile(all_ms, 95):,.0f} ms", "warn"),
        ("Refused (401/403)", f"{refused:,}", "bad"),
        ("Audit records", f"{workload.audit_records:,}", "info"),
        ("Audit chain", "intact" if workload.chain_valid else "BROKEN", "good" if workload.chain_valid else "bad"),
    ]
    routes = Counter(f"{sample.method} {sample.route}" for sample in samples).most_common()
    return plot_dashboard(DashboardData(tiles, times, by_user, dict(sorted(statuses.items())), p50, p95, routes))


def access_chart() -> Figure:
    workload = _workload()
    counts: dict[str, Counter[int]] = defaultdict(Counter)
    for sample in workload.samples:
        counts[sample.user][sample.status] += 1
    order = ["aliyeva", "analyst", "pm", "trader", "compliance", "admin", "intruder", "monitor"]
    labels = {"aliyeva": "client (aliyeva)", "pm": "portfolio manager", "monitor": "health monitor"}
    return plot_access([(labels.get(user, user), counts[user]) for user in order if user in counts])


def four_eyes_chart() -> Figure:
    from .config import get_settings

    workload = _workload()
    orders = workload.orders
    blocked = sum(1 for s in workload.samples if s.route == "/v1/orders" and s.method == "POST" and s.status == 422)
    decided = [order for order in orders if order["decided_by"]]
    counts = {
        "entered": len(orders) + blocked,
        "blocked": blocked,
        "direct": sum(1 for order in orders if order["status"] == "approved" and not order["decided_by"]),
        "pending": len(decided) + sum(1 for order in orders if order["status"] == "pending approval"),
        "approved": sum(1 for order in decided if order["status"] == "approved"),
        "rejected": sum(1 for order in decided if order["status"] == "rejected"),
    }
    return plot_four_eyes(counts, get_settings().four_eyes_threshold)


def audit_chain_chart() -> Figure:
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone

    from .core.audit_chain import AuditRecord, chain, verify

    start = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)
    story = [
        ("pm", "POST /v1/orders", 201),
        ("compliance", "GET /v1/orders", 200),
        ("compliance", "POST …/decision", 200),
        ("trader", "GET /v1/trading/costs", 200),
        ("intruder", "GET /v1/audit", 401),
        ("aliyeva", "GET …/report.pdf", 200),
    ]
    entries = [
        AuditRecord(
            0,
            start + timedelta(seconds=index * 7),
            f"r{index}",
            who,
            what.split()[0],
            what.split()[1],
            status,
            18.0,
            None,
            None,
            "",
        )
        for index, (who, what, status) in enumerate(story)
    ]
    sealed = chain(entries)
    tampered = list(sealed)
    tampered[3] = replace(sealed[3], status=403)
    check = verify(tampered)
    blocks = []
    for record in tampered:
        valid = check.first_broken is None or record.sequence < check.first_broken
        who = record.username or "anonymous"
        blocks.append(
            (record.sequence, who, f"{record.method} {record.path}", record.record_hash[:10], record.status, valid)
        )
    timing = []
    base = entries[0]
    for count in (1_000, 5_000, 10_000, 25_000, 50_000):
        records = chain([replace(base, request_id=f"r{i}") for i in range(count)])
        started = time.perf_counter()
        verify(records)
        timing.append((count, time.perf_counter() - started))
    return plot_audit_chain(blocks, timing)


# ---------------------------------------------------------------------------- the project
def growth_chart() -> Figure:
    import json

    rows = json.loads((ROOT / "docs" / "data" / "growth.json").read_text(encoding="utf-8"))
    return plot_growth(rows)


def tests_chart() -> Figure:
    from .devtools.structure import tests_by_package

    counts = tests_by_package()
    rows = [(name, total, properties) for name, (total, properties) in counts.items()]
    controls = [
        ("ruff lint and format", "pyflakes, pycodestyle, bugbear, pyupgrade, simplify, isort"),
        ("mypy", "every function typed, across 190 source files"),
        ("pytest on Python 3.10, 3.11, 3.12", "the whole suite, the gallery included"),
        ("PostgreSQL 16 integration", "every repository against a real server"),
        ("Alembic check", "the models and the migrations cannot drift apart"),
        ("Docker image build", "the release image builds from a clean checkout"),
        ("Coverage", "measured on every run, reported with the missing lines"),
    ]
    collected = _collected_tests()
    return plot_tests(rows, collected, controls)


def _collected_tests() -> int:
    import json

    rows = json.loads((ROOT / "docs" / "data" / "growth.json").read_text(encoding="utf-8"))
    return int(rows[-1].get("collected", rows[-1]["tests"]))


def security_chart() -> Figure:
    return plot_security(OWASP)


def journey_chart() -> Figure:
    import matplotlib.image as mpimg

    panels: list[tuple[str, str, str, Any]] = []
    for day, module, headline, filename in JOURNEY:
        path = IMAGES / filename
        image = mpimg.imread(path) if path.exists() else None
        panels.append((day, module, headline, image))
    return plot_journey(panels)


def platform_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    def item(filename: str, title: str, description: str, builder) -> GalleryItem:  # type: ignore[no-untyped-def]
        return GalleryItem(filename, title, description, builder, "web platform")

    return (
        item(
            "platform-architecture.png",
            "The architecture",
            "Users, the API and its seven controls, the nine modules, storage and operations.",
            architecture_chart,
        ),
        item(
            "request-pipeline.png",
            "Seven layers between a request and the data",
            "A working day's requests, and what each layer stopped.",
            pipeline_chart,
        ),
        item(
            "rbac-matrix.png",
            "Role-based access control",
            "Permissions by role, with separation of duties.",
            rbac_chart,
        ),
        item(
            "api-surface.png",
            "The API surface",
            "Every endpoint and the permission it requires, read from the OpenAPI document.",
            api_surface_chart,
        ),
        item(
            "api-latency.png",
            "Latency, endpoint by endpoint",
            "Every request of the working day, with its median and 95th percentile.",
            latency_chart,
        ),
        item(
            "operations-dashboard.png",
            "The operations dashboard",
            "Request rate by user, statuses, latency and the busiest routes.",
            dashboard_chart,
        ),
        item(
            "audit-chain.png",
            "A tamper-evident audit trail",
            "The hash chain, an edited record caught, and the cost of verifying.",
            audit_chain_chart,
        ),
        item(
            "access-outcomes.png",
            "Who was refused, and why",
            "Each person's requests by the platform's answer.",
            access_chart,
        ),
        item(
            "four-eyes.png",
            "Orders under four eyes",
            "Pre-trade checks, the approval threshold and the second person.",
            four_eyes_chart,
        ),
        item(
            "deployment-topology.png",
            "Deployment",
            "The Docker Compose topology: database, migrations, API, Prometheus, Grafana.",
            deployment_chart,
        ),
        item(
            "package-graph.png",
            "The package graph",
            "Which package imports which, parsed from the source.",
            module_graph_chart,
        ),
        item(
            "test-landscape.png",
            "The tests",
            "Test functions by area, property-based among them, and what CI runs.",
            tests_chart,
        ),
        item(
            "security-controls.png",
            "Security controls",
            "The OWASP API Security Top 10 mapped to controls and the tests that prove them.",
            security_chart,
        ),
        item(
            "codebase-growth.png",
            "Nine days, ten releases",
            "Code, tests, figures and decisions at every release tag.",
            growth_chart,
        ),
        item("nine-days.png", "Nine days, one platform", "Each day's module and its headline chart.", journey_chart),
    )
