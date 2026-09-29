"""The web application: FastAPI over the platform's modules, with the controls a regulated firm needs.

Every request passes through the same layers, in this order:

1. **Request id** - taken from ``X-Request-ID`` or generated, returned on the
   response and written everywhere the request leaves a trace.
2. **Authentication** - a signed, unexpired bearer token (``/auth/token``
   issues them against a salted password hash).
3. **Authorisation** - the endpoint's permission, and for portfolio data the
   caller's entitlement to that portfolio.
4. **Rate limit** - a token bucket per user; over it, ``429`` with
   ``Retry-After``.
5. **Idempotency** - a write carrying ``Idempotency-Key`` is done once; a retry
   gets the stored response, a different body under the same key a ``409``.
6. **The handler** - which asks the data facade, never computes.
7. **Audit and metrics** - every request, allowed or refused, is appended to the
   hash-chained audit log and counted in Prometheus metrics.

Errors are RFC 9457 problem details (``application/problem+json``) with the
request id, never a stack trace.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, Counter, Histogram
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..config import Settings, get_settings
from ..core.audit_chain import AuditRecord
from ..core.exceptions import ValidationError
from ..persistence import Database, UnitOfWork
from ..persistence.platform_repositories import CHAIN_LOCK
from .data import DemoPlatformData, NotAvailable, PlatformData
from .security import DEVELOPMENT_SECRET, hash_password

LOGGER = logging.getLogger("meridian.api")
UNAUDITED = ("/metrics",)  # scraped every few seconds by Prometheus; counted, not audited

#: the demonstration users: (username, full name, roles, portfolios, password)
DEMO_USERS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...] | None, str], ...] = (
    ("aliyeva", "Leyla Aliyeva (client)", ("client",), ("PF-GLOBAL-EQ",), "client-demo-2026"),
    ("analyst", "Research Analyst", ("analyst",), None, "analyst-demo-2026"),
    ("pm", "Portfolio Manager", ("portfolio_manager",), None, "pm-demo-2026"),
    ("trader", "Execution Trader", ("trader",), None, "trader-demo-2026"),
    ("compliance", "Compliance Officer", ("compliance_officer",), None, "compliance-demo-2026"),
    ("admin", "Platform Administrator", ("administrator",), None, "admin-demo-2026"),
)


class RateLimiter:
    """A token bucket per user: ``rate`` requests a minute, bursting to the same number."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.refill = per_minute / 60.0
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def take(self, key: str, now: float | None = None) -> float:
        """Zero if allowed; otherwise the seconds until a token is available."""
        now = time.monotonic() if now is None else now
        with self.lock:
            tokens, last = self.buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            if tokens >= 1.0:
                self.buckets[key] = (tokens - 1.0, now)
                return 0.0
            self.buckets[key] = (tokens, now)
            return (1.0 - tokens) / self.refill


@dataclass
class Platform:
    """What the application holds for its lifetime."""

    settings: Settings
    database: Database
    data: PlatformData
    limiter: RateLimiter
    registry: CollectorRegistry = field(default_factory=CollectorRegistry)

    def __post_init__(self) -> None:
        self.requests = Counter(
            "meridian_http_requests", "HTTP requests handled", ["method", "route", "status"], registry=self.registry
        )
        self.latency = Histogram(
            "meridian_http_request_seconds",
            "Time to handle a request",
            ["route"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )
        self.audited = Counter("meridian_audit_records", "Records appended to the audit chain", registry=self.registry)
        self.audit_failures = Counter(
            "meridian_audit_failures", "Records that could not be appended to the audit chain", registry=self.registry
        )
        self.denied = Counter(
            "meridian_access_denied",
            "Requests refused by authentication or authorisation",
            ["status"],
            registry=self.registry,
        )


def problem(
    status: int, title: str, detail: str | None, request: Request, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


TITLES = {
    400: "Bad request",
    401: "Not authenticated",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    422: "Unprocessable request",
    429: "Too many requests",
    500: "Internal error",
}


def seed_users(platform: Platform) -> int:
    """Create the demonstration users if there are none. Several workers start at once; the first one wins."""
    from sqlalchemy.exc import IntegrityError

    try:
        with platform.database.session() as session:
            unit = UnitOfWork(session)
            if unit.platform.users():
                return 0
            for username, full_name, roles, portfolios, password in DEMO_USERS:
                hashed = hash_password(password, iterations=platform.settings.password_iterations)
                unit.platform.save_user(username, full_name, hashed, roles, portfolios)
            unit.commit()
    except IntegrityError:
        return 0  # another worker seeded them first
    return len(DEMO_USERS)


def create_app(settings: Settings | None = None, data: PlatformData | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.environment == "production" and settings.jwt_secret == DEVELOPMENT_SECRET:
        raise RuntimeError("refusing to start in production with the development signing key: set MERIDIAN_JWT_SECRET")
    if len(settings.jwt_secret) < 32:
        raise RuntimeError("the token signing key must be at least 32 characters")
    database = Database(settings)
    platform = Platform(settings, database, data or DemoPlatformData(), RateLimiter(settings.api_rate_limit))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database.create_all()
        if settings.demo_users:
            created = seed_users(platform)
            if created:
                LOGGER.info("created %s demonstration users", created)
        yield
        database.dispose()

    app = FastAPI(
        title="Meridian Investment Platform API",
        version=__version__,
        description=(
            "Portfolios, performance, risk, compliance, tax-aware rebalancing, orders and trading costs, over the "
            "same domain objects as the Meridian CLI. Bearer tokens from `/auth/token`; every request is "
            "authorised by permission and entitlement, rate-limited, and appended to a hash-chained audit log. "
            "Writes accept an `Idempotency-Key` header."
        ),
        lifespan=lifespan,
        contact={"name": "Meridian", "url": "https://github.com/elmarfarajov/meridian-investment-platform"},
        license_info={"name": "MIT"},
        openapi_tags=[
            {"name": "system", "description": "Health, readiness, version and metrics."},
            {"name": "auth", "description": "Access tokens and the caller's identity."},
            {
                "name": "portfolios",
                "description": "Valuation, performance, attribution, risk, compliance and tax lots.",
            },
            {"name": "rebalancing", "description": "Pre-trade checks and tax-aware rebalance proposals."},
            {"name": "orders", "description": "Orders with pre-trade checks and four-eyes approval."},
            {"name": "trading", "description": "Transaction cost analysis."},
            {"name": "reports", "description": "The client report."},
            {"name": "audit", "description": "The hash-chained audit log and its verification."},
        ],
    )
    app.state.platform = platform

    # ------------------------------------------------------------------ errors
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code in (401, 403):
            platform.denied.labels(str(error.status_code)).inc()
        headers = dict(error.headers or {})
        return problem(error.status_code, TITLES.get(error.status_code, "Error"), str(error.detail), request, headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        detail = "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors())
        return problem(422, TITLES[422], detail, request)

    @app.exception_handler(ValidationError)
    async def domain_invalid(request: Request, error: ValidationError) -> JSONResponse:
        return problem(422, TITLES[422], str(error), request)

    @app.exception_handler(NotAvailable)
    async def not_available(request: Request, error: NotAvailable) -> JSONResponse:
        return problem(404, TITLES[404], str(error), request)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        LOGGER.exception("unhandled error on %s", request.url.path, exc_info=error)
        return problem(500, TITLES[500], "the error has been logged with this request's id", request)

    # ------------------------------------------------------------------ every request
    @app.middleware("http")
    async def envelope(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.principal = None
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as error:  # the handler above turns it into a problem; the audit still records it
            LOGGER.exception("unhandled error", exc_info=error)
            response = problem(500, TITLES[500], "the error has been logged with this request's id", request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        platform.requests.labels(request.method, template, str(response.status_code)).inc()
        platform.latency.labels(template).observe(elapsed)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path not in UNAUDITED:
            principal = request.state.principal
            entry = AuditRecord(
                0,
                datetime.now(timezone.utc),
                request.state.request_id,
                None if principal is None else principal.username,
                request.method,
                request.url.path[:256],
                response.status_code,
                elapsed * 1000.0,
                request.headers.get("Idempotency-Key"),
                getattr(request.state, "audit_detail", None),
                "",
            )
            await run_in_threadpool(_append, platform, entry)
        return response

    from .routes import register

    register(app)
    return app


def _append(platform: Platform, entry: AuditRecord, attempts: int = 20) -> None:
    """Seal the entry onto the chain.

    Within a process a lock serialises writers. Across processes (several
    Uvicorn workers, several containers) two writers can read the same head;
    the second insert then collides on the sequence number, which is the
    primary key, and is retried against the new head - optimistic
    concurrency, so the chain never forks and no request waits on a lock
    held in another process.
    """
    from sqlalchemy.exc import IntegrityError

    for attempt in range(attempts):
        try:
            with CHAIN_LOCK, platform.database.session() as session:
                unit = UnitOfWork(session)
                unit.platform.append(entry)
                unit.commit()
            platform.audited.inc()
            return
        except IntegrityError:
            time.sleep(0.002 * (attempt + 1))
    platform.audit_failures.inc()
    LOGGER.error("could not append %s %s to the audit chain after %s attempts", entry.method, entry.path, attempts)


def retry_after(seconds: float) -> str:
    return str(max(1, math.ceil(seconds)))


def platform_of(request: Request) -> Platform:
    platform: Platform = request.app.state.platform
    return platform


def jsonable(value: Any) -> Any:
    """A response body as the idempotency store keeps it."""
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)
