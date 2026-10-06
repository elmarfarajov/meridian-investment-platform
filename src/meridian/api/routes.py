"""The endpoints: thin functions that check who is asking, ask the data facade, and shape the answer."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Path, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from prometheus_client import generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..core.audit_chain import verify
from ..persistence import UnitOfWork
from ..persistence.models import OrderRequestRow
from . import schemas
from .app import Platform, jsonable, platform_of, retry_after
from .security import (
    PERMISSIONS,
    Principal,
    hash_password,
    issue_token,
    portfolios_from,
    read_token,
    roles_from,
    verify_password,
)

bearer = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)
PortfolioId = Annotated[str, Path(pattern=r"^[A-Z0-9-]{2,64}$", examples=["PF-GLOBAL-EQ"])]
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        description="Repeat a write safely: same key, same result",
    ),
]
UNAUTHORISED = {"WWW-Authenticate": "Bearer"}
ORDER_ATTEMPTS = 20


# ---------------------------------------------------------------------------- who is asking
def principal(request: Request, token: Annotated[str | None, Depends(bearer)]) -> Principal:
    platform = platform_of(request)
    if token is None:
        raise HTTPException(401, "a bearer token is required", headers=UNAUTHORISED)
    try:
        caller = read_token(token, platform.settings.jwt_secret)
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(401, "the token has expired", headers=UNAUTHORISED) from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(401, "the token is not valid", headers=UNAUTHORISED) from error
    # the token says who; the user record says what they may do now. A token outlives a change to the
    # account - a leaver deactivated, a manager moved off the desk - and must not carry the old rights.
    with platform.database.session() as session:
        user = UnitOfWork(session).platform.user(caller.username)
        if user is None or not user.active:
            raise HTTPException(401, "the account is not active", headers=UNAUTHORISED)
        caller = Principal(user.username, roles_from(user.roles), portfolios_from(user.portfolios), caller.token_id)
    request.state.principal = caller
    wait = platform.limiter.take(caller.username)
    if wait > 0:
        raise HTTPException(
            429,
            f"over {platform.settings.api_rate_limit} requests a minute",
            headers={"Retry-After": retry_after(wait)},
        )
    return caller


Caller = Annotated[Principal, Depends(principal)]


def needs(permission: str) -> dict[str, Any]:
    """The permission an endpoint requires, recorded in the OpenAPI document as ``x-permission``.

    ``authenticated`` means any signed-in caller; endpoints without it are public (health, metrics, sign-in).
    """
    return {"openapi_extra": {"x-permission": permission}}


def require(permission: str) -> Callable[[Principal], Principal]:
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown permission {permission}")

    def check(caller: Caller) -> Principal:
        if not caller.can(permission):
            raise HTTPException(403, f"this needs the {permission} permission")
        return caller

    return check


def entitled(caller: Principal, portfolio_id: str) -> None:
    if not caller.sees(portfolio_id):
        # the same answer as a portfolio that does not exist: a client cannot learn which others do
        raise HTTPException(404, f"no portfolio {portfolio_id}")


def _data_call(platform: Platform, method: str, *args: Any) -> Any:
    try:
        return getattr(platform.data, method)(*args)
    except KeyError as error:
        raise HTTPException(404, f"no portfolio {error.args[0]}") from error


async def ask(request: Request, method: str, *args: Any) -> Any:
    return await run_in_threadpool(_data_call, platform_of(request), method, *args)


# ---------------------------------------------------------------------------- idempotency
def fingerprint(body: Any) -> str:
    return hashlib.sha256(json.dumps(jsonable(body), sort_keys=True).encode("utf-8")).hexdigest()


def replay(request: Request, caller: Principal, key: str | None, body: Any) -> JSONResponse | None:
    if key is None:
        return None
    with platform_of(request).database.session() as session:
        stored = UnitOfWork(session).platform.idempotent(key, caller.username)
        if stored is None:
            return None
        if stored.request_hash != fingerprint(body) or stored.path != request.url.path:
            raise HTTPException(409, "this Idempotency-Key was used for a different request")
        request.state.audit_detail = "idempotent replay"
        return JSONResponse(
            json.loads(stored.response_body), status_code=stored.status, headers={"Idempotent-Replayed": "true"}
        )


def remember(
    request: Request, caller: Principal, key: str | None, body: Any, status: int, response: Any
) -> JSONResponse | None:
    """Store a write's response under its key; if a request with the same key got there first, its response."""
    if key is None:
        return None
    try:
        with platform_of(request).database.session() as session:
            unit = UnitOfWork(session)
            _remember(unit, request, caller, key, body, status, response)
            unit.commit()
    except IntegrityError:
        return replay(request, caller, key, body)  # the same request, at the same moment: one answer for both
    return None


def _remember(
    unit: UnitOfWork, request: Request, caller: Principal, key: str, body: Any, status: int, response: Any
) -> None:
    unit.platform.remember(
        key,
        caller.username,
        request.method,
        request.url.path,
        fingerprint(body),
        status,
        json.dumps(jsonable(response)),
    )


# ---------------------------------------------------------------------------- system
system = APIRouter(tags=["system"])


@system.get("/health", response_model=schemas.Health, summary="Liveness")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


@system.get(
    "/ready", response_model=schemas.Health, summary="Readiness: the database answers and the audit chain is intact"
)
def ready(request: Request, response: Response) -> dict[str, Any]:
    platform = platform_of(request)
    try:
        with platform.database.session() as session:
            check = verify(UnitOfWork(session).platform.records())
    except Exception:
        response.status_code = 503
        return {"status": "degraded", "version": __version__, "database": "unavailable"}
    if not check.valid:
        response.status_code = 503
    return {
        "status": "ok" if check.valid else "degraded",
        "version": __version__,
        "database": "ok",
        "audit_chain": "intact" if check.valid else "broken",
    }


@system.get("/metrics", summary="Prometheus metrics", response_class=PlainTextResponse)
def metrics(request: Request) -> Response:
    return Response(generate_latest(platform_of(request).registry), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------- auth
auth = APIRouter(prefix="/auth", tags=["auth"])


@lru_cache(maxsize=4)
def decoy_hash(iterations: int) -> str:
    """A hash no password matches, checked when there is no such account: every sign-in costs the same."""
    return hash_password(secrets.token_urlsafe(32), iterations=iterations)


@auth.post("/token", response_model=schemas.Token, summary="Exchange a username and password for a bearer token")
def token(request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> dict[str, Any]:
    platform = platform_of(request)
    with platform.database.session() as session:
        user = UnitOfWork(session).platform.user(form.username)
        # always one hash, whether or not the account exists or is active: the time a failure takes must
        # not tell an attacker which usernames are real
        stored = user.password_hash if user is not None else decoy_hash(platform.settings.password_iterations)
        matches = verify_password(form.password, stored)
        valid = user is not None and user.active and matches
        if not valid or user is None:
            # one message for an unknown user and a wrong password: the response does not reveal which
            request.state.audit_detail = f"failed login for {form.username[:64]}"
            platform.denied.labels("401").inc()
            raise HTTPException(401, "incorrect username or password", headers=UNAUTHORISED)
        caller = Principal(user.username, roles_from(user.roles), portfolios_from(user.portfolios))
    request.state.principal = caller
    access, seconds = issue_token(caller, platform.settings.jwt_secret, platform.settings.jwt_ttl_minutes)
    return {"access_token": access, "token_type": "bearer", "expires_in": seconds, "roles": sorted(caller.roles)}


@auth.get(
    "/me", response_model=schemas.Me, summary="The caller: roles, permissions and portfolios", **needs("authenticated")
)
def me(caller: Caller) -> dict[str, Any]:
    return {
        "username": caller.username,
        "roles": sorted(caller.roles),
        "permissions": sorted(caller.permissions),
        "portfolios": None if caller.portfolios is None else sorted(caller.portfolios),
    }


# ---------------------------------------------------------------------------- portfolios
portfolios = APIRouter(prefix="/v1/portfolios", tags=["portfolios"])


@portfolios.get(
    "", response_model=list[schemas.Portfolio], summary="The portfolios the caller may see", **needs("portfolio:read")
)
async def list_portfolios(
    request: Request, caller: Annotated[Principal, Depends(require("portfolio:read"))]
) -> list[dict[str, Any]]:
    everything = await ask(request, "portfolios")
    return [item for item in everything if caller.sees(item["portfolio_id"])]


def _portfolio_endpoint(method: str, permission: str, model: type, summary: str) -> Callable[..., Any]:
    guard = Depends(require(permission))

    async def endpoint(request: Request, portfolio_id: PortfolioId, caller: Principal = guard) -> Any:
        entitled(caller, portfolio_id)
        return await ask(request, method, portfolio_id)

    endpoint.__name__ = f"get_{method}"
    endpoint.__doc__ = summary
    return endpoint


for _path, _method, _permission, _model, _summary in (
    (
        "/{portfolio_id}/valuation",
        "valuation",
        "portfolio:read",
        schemas.Valuation,
        "Holdings valued at the last close",
    ),
    (
        "/{portfolio_id}/performance",
        "performance",
        "portfolio:read",
        schemas.Performance,
        "Time-weighted returns against the benchmark",
    ),
    (
        "/{portfolio_id}/attribution",
        "attribution",
        "risk:read",
        schemas.Attribution,
        "Brinson-Fachler attribution by sector, linked",
    ),
    ("/{portfolio_id}/risk", "risk", "risk:read", schemas.Risk, "Factor-model risk, value at risk and stress tests"),
    (
        "/{portfolio_id}/compliance",
        "compliance",
        "compliance:read",
        schemas.Compliance,
        "Every rule of the mandate today",
    ),
    (
        "/{portfolio_id}/tax-lots",
        "tax_lots",
        "tax:read",
        schemas.TaxLots,
        "Open tax lots with basis and holding period",
    ),
):
    portfolios.add_api_route(
        _path,
        _portfolio_endpoint(_method, _permission, _model, _summary),
        methods=["GET"],
        response_model=_model,
        summary=_summary,
        **needs(_permission),
    )


# ---------------------------------------------------------------------------- rebalancing
rebalancing = APIRouter(prefix="/v1/portfolios", tags=["rebalancing"])


@rebalancing.post(
    "/{portfolio_id}/pretrade",
    response_model=schemas.PreTrade,
    summary="Check an order against the mandate before it is sent",
    **needs("compliance:read"),
)
async def pretrade(
    request: Request,
    portfolio_id: PortfolioId,
    body: schemas.PreTradeIn,
    caller: Annotated[Principal, Depends(require("compliance:read"))],
) -> Any:
    entitled(caller, portfolio_id)
    return await ask(request, "pretrade", portfolio_id, body.instrument_id, body.side, body.amount)


@rebalancing.post(
    "/{portfolio_id}/rebalance-proposals",
    response_model=schemas.Rebalance,
    status_code=201,
    summary="Propose a tax-aware rebalance (idempotent)",
    **needs("rebalance:propose"),
)
async def propose(
    request: Request,
    portfolio_id: PortfolioId,
    caller: Annotated[Principal, Depends(require("rebalance:propose"))],
    key: IdempotencyKey = None,
) -> Any:
    entitled(caller, portfolio_id)
    body = {"portfolio_id": portfolio_id}
    stored = await run_in_threadpool(replay, request, caller, key, body)
    if stored is not None:
        return stored
    result = await ask(request, "rebalance", portfolio_id)
    first = await run_in_threadpool(remember, request, caller, key, body, 201, result)
    return result if first is None else first


# ---------------------------------------------------------------------------- orders
orders = APIRouter(prefix="/v1/orders", tags=["orders"])


def _order_out(row: OrderRequestRow) -> dict[str, Any]:
    return {
        "order_id": row.order_id,
        "portfolio_id": row.portfolio_id,
        "instrument_id": row.instrument_id,
        "side": row.side,
        "amount": row.amount,
        "status": row.status,
        "pretrade_decision": row.pretrade_decision,
        "pretrade_reasons": [item for item in row.pretrade_reasons.split("; ") if item],
        "created_by": row.created_by,
        "decided_by": row.decided_by,
        "decision_note": row.decision_note,
    }


@orders.post(
    "",
    response_model=schemas.OrderOut,
    status_code=201,
    summary="Enter an order: checked pre-trade, four eyes above the threshold (idempotent)",
    **needs("orders:create"),
)
async def create_order(
    request: Request,
    body: schemas.OrderIn,
    caller: Annotated[Principal, Depends(require("orders:create"))],
    key: IdempotencyKey = None,
) -> Any:
    entitled(caller, body.portfolio_id)
    stored = await run_in_threadpool(replay, request, caller, key, body)
    if stored is not None:
        return stored
    check = await ask(request, "pretrade", body.portfolio_id, body.instrument_id, body.side, body.amount)
    if check["decision"] == "blocked":
        reasons = ", ".join(f"{item['rule_id']} ({item['effect']})" for item in check["reasons"])
        raise HTTPException(
            422, f"blocked by the mandate: {reasons}; the largest order allowed is {check['maximum']:,.0f}"
        )
    platform = platform_of(request)
    needs_second = body.amount > platform.settings.four_eyes_threshold or check["decision"] == "override required"

    def store() -> dict[str, Any] | JSONResponse:
        """The order and its idempotency record in one transaction, so a retry can never enter it twice.

        Two requests can take the same order number, or the same key, at the same
        moment; the database refuses the second insert. A taken key means the
        same request got there first, and its answer is returned; a taken number
        is tried again with the next one.
        """
        for attempt in range(ORDER_ATTEMPTS):
            try:
                with platform.database.session() as session:
                    unit = UnitOfWork(session)
                    row = OrderRequestRow(
                        order_id=unit.platform.next_order_id(),
                        portfolio_id=body.portfolio_id,
                        instrument_id=body.instrument_id,
                        side=body.side,
                        amount=body.amount,
                        status="pending approval" if needs_second else "approved",
                        pretrade_decision=check["decision"],
                        pretrade_reasons="; ".join(f"{item['rule_id']}: {item['effect']}" for item in check["reasons"]),
                        created_by=caller.username,
                    )
                    unit.platform.add_order(row)
                    result = _order_out(row)
                    if key is not None:
                        _remember(unit, request, caller, key, body, 201, result)
                    unit.commit()
                    return result
            except IntegrityError:
                first = replay(request, caller, key, body)
                if first is not None:
                    return first
                time.sleep(0.002 * (attempt + 1))
        raise HTTPException(503, "the order could not be numbered; try again with the same Idempotency-Key")

    result = await run_in_threadpool(store)
    if isinstance(result, JSONResponse):
        return result
    request.state.audit_detail = f"order {result['order_id']} {result['status']}"
    return result


@orders.get(
    "",
    response_model=list[schemas.OrderOut],
    summary="Orders for the portfolios the caller may see",
    **needs("orders:read"),
)
def list_orders(
    request: Request,
    caller: Annotated[Principal, Depends(require("orders:read"))],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    with platform_of(request).database.session() as session:
        rows = UnitOfWork(session).platform.orders(
            None if caller.portfolios is None else sorted(caller.portfolios), limit=limit
        )
        return [_order_out(row) for row in rows]


@orders.post(
    "/{order_id}/decision",
    response_model=schemas.OrderOut,
    summary="Approve or reject an order: never your own",
    **needs("orders:approve"),
)
def decide(
    request: Request,
    order_id: str,
    body: schemas.Decision,
    caller: Annotated[Principal, Depends(require("orders:approve"))],
) -> dict[str, Any]:
    with platform_of(request).database.session() as session:
        unit = UnitOfWork(session)
        row = unit.platform.order(order_id)
        if row is None or not caller.sees(row.portfolio_id):
            raise HTTPException(404, f"no order {order_id}")
        if row.created_by == caller.username:
            raise HTTPException(403, "four eyes: the person who entered an order cannot decide it")
        if row.status != "pending approval":
            raise HTTPException(409, f"{order_id} is already {row.status}")
        status = "approved" if body.approve else "rejected"
        if not unit.platform.decide_order(order_id, status, caller.username, body.note):
            # another approver decided it between this request's read and its write
            raise HTTPException(409, f"{order_id} was decided by someone else a moment ago")
        unit.commit()
        session.refresh(row)
        request.state.audit_detail = f"order {order_id} {row.status}"
        return _order_out(row)


# ---------------------------------------------------------------------------- trading and reports
trading = APIRouter(prefix="/v1/trading", tags=["trading"])


@trading.get(
    "/costs",
    response_model=schemas.TradingCosts,
    summary="Implementation shortfall of the latest trading day",
    **needs("trading:read"),
)
async def trading_costs(request: Request, caller: Annotated[Principal, Depends(require("trading:read"))]) -> Any:
    return await ask(request, "trading_costs")


reports = APIRouter(prefix="/v1/portfolios", tags=["reports"])


@reports.get(
    "/{portfolio_id}/report.pdf",
    summary="The client report, as a PDF",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}},
    **needs("report:read"),
)
async def client_report(
    request: Request, portfolio_id: PortfolioId, caller: Annotated[Principal, Depends(require("report:read"))]
) -> FileResponse:
    entitled(caller, portfolio_id)
    directory = platform_of(request).settings.reports_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = await ask(request, "client_report", portfolio_id, directory)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


# ---------------------------------------------------------------------------- audit
audit = APIRouter(prefix="/v1/audit", tags=["audit"])


@audit.get(
    "", response_model=schemas.AuditPage, summary="The audit log, oldest first, by cursor", **needs("audit:read")
)
def audit_log(
    request: Request,
    caller: Annotated[Principal, Depends(require("audit:read"))],
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    username: str | None = None,
) -> dict[str, Any]:
    with platform_of(request).database.session() as session:
        records = UnitOfWork(session).platform.records(after=after, limit=limit + 1, username=username)
    page = records[:limit]
    return {
        "records": [
            {
                **{
                    name: getattr(record, name)
                    for name in (
                        "sequence",
                        "request_id",
                        "username",
                        "method",
                        "path",
                        "status",
                        "latency_ms",
                        "idempotency_key",
                        "previous_hash",
                        "record_hash",
                    )
                },
                "recorded_at": record.recorded_at.isoformat(),
            }
            for record in page
        ],
        "next_after": page[-1].sequence if len(records) > limit else None,
    }


@audit.get(
    "/verify",
    response_model=schemas.ChainStatus,
    summary="Walk the hash chain and report the first broken record",
    **needs("audit:read"),
)
def audit_verify(request: Request, caller: Annotated[Principal, Depends(require("audit:read"))]) -> dict[str, Any]:
    with platform_of(request).database.session() as session:
        check = verify(UnitOfWork(session).platform.records())
    return {"records": check.records, "valid": check.valid, "first_broken": check.first_broken, "reason": check.reason}


def register(app: FastAPI) -> None:
    for router in (system, auth, portfolios, rebalancing, orders, trading, reports, audit):
        app.include_router(router)
