"""``meridian platform`` - run and operate the web platform.

``serve`` starts the API under Uvicorn; ``users`` lists who may use it and
``add-user`` creates or updates an account; ``verify-audit`` walks the audit
chain; ``openapi`` writes the API's contract to a file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from ..config import get_settings
from ..core.exceptions import ValidationError
from ..persistence import Database, UnitOfWork
from ._common import console, fail, render_rows, success, table

app = typer.Typer(help="The web platform: serve the API, manage users, verify the audit trail.", no_args_is_help=True)


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    workers: Annotated[int, typer.Option("--workers", min=1)] = 1,
) -> None:
    """Start the API (OpenAPI documentation at /docs)."""
    import uvicorn

    console.print(f"serving on http://{host}:{port} - documentation at http://{host}:{port}/docs")
    uvicorn.run("meridian.api.main:app", host=host, port=port, workers=workers, proxy_headers=True, log_level="info")


@app.command("users")
def users() -> None:
    """Everyone who may sign in, with their roles and portfolios."""
    database = Database(get_settings()).create_all()
    try:
        with database.session() as session:
            rows = [
                (row.username, row.full_name, row.roles, row.portfolios or "all", "yes" if row.active else "no")
                for row in UnitOfWork(session).platform.users()
            ]
    finally:
        database.dispose()
    if not rows:
        fail("no users yet - start the platform once, or add one with `meridian platform add-user`")
    console.print(render_rows(table("Platform users", ["User", "Name", "Roles", "Portfolios", "Active"]), rows))


@app.command("add-user")
def add_user(
    username: Annotated[str, typer.Argument()],
    roles: Annotated[str, typer.Option("--roles", help="Comma-separated, e.g. analyst,trader")],
    name: Annotated[str, typer.Option("--name")] = "",
    portfolios: Annotated[str, typer.Option("--portfolios", help="For a client: the portfolios they may see")] = "",
    password: Annotated[str, typer.Option("--password", prompt=True, hide_input=True, confirmation_prompt=True)] = "",
) -> None:
    """Create a user, or reset an existing one's password and roles."""
    from ..api.security import hash_password, portfolios_from, roles_from

    settings = get_settings()
    try:
        role_set = roles_from(roles)
        hashed = hash_password(password, iterations=settings.password_iterations)
    except ValidationError as error:
        fail(str(error))
    allowed = portfolios_from(portfolios)
    database = Database(settings).create_all()
    try:
        with database.session() as session:
            unit = UnitOfWork(session)
            unit.platform.save_user(
                username, name or username, hashed, sorted(role_set), None if allowed is None else sorted(allowed)
            )
            unit.commit()
    finally:
        database.dispose()
    success(f"{username}: {', '.join(sorted(role_set))}")


@app.command("verify-audit")
def verify_audit() -> None:
    """Walk the audit log's hash chain and report the first record that fails."""
    from ..core.audit_chain import verify

    database = Database(get_settings()).create_all()
    try:
        with database.session() as session:
            check = verify(UnitOfWork(session).platform.records())
    finally:
        database.dispose()
    if not check.valid:
        fail(f"the audit chain is broken at record {check.first_broken} of {check.records}: {check.reason}", code=2)
    success(f"{check.records:,} records, chain intact")


@app.command("openapi")
def openapi(out: Annotated[Path, typer.Option("--out")] = Path("openapi.json")) -> None:
    """Write the API's OpenAPI document."""
    from ..api.app import create_app

    document = create_app().openapi()
    out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    success(f"{len(document['paths'])} paths written to {out}")
