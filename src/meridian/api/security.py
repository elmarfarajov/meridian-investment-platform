"""Who may do what: passwords, access tokens, roles, permissions and entitlements.

**Passwords** are never stored. What is stored is a salted PBKDF2-HMAC-SHA256
hash at 600,000 iterations (the OWASP 2023 recommendation), in the
``pbkdf2_sha256$iterations$salt$hash`` format, compared in constant time.

**Access tokens** are JSON Web Tokens signed with HMAC-SHA256, valid for
thirty minutes, carrying the user, their roles and a unique id. The signature
key comes from the environment; the service refuses to start in production
with the development default.

**Roles** are bundles of **permissions**, the unit every endpoint checks:

=====================  ======================================================
role                   what it is for
=====================  ======================================================
client                 reads its own portfolios' reports, nothing else
analyst                reads every portfolio: valuation, performance, risk
portfolio manager      also proposes rebalances and enters orders
trader                 enters orders and reads trading costs
compliance officer     reads everything, approves orders, reads the audit log
administrator          manages users; reads the audit log
=====================  ======================================================

**Entitlements** narrow a permission to data: a client holds
``portfolio:read`` like an analyst, but only for the portfolios on their own
record. Separation of duties is built into the matrix - the administrator
cannot trade, and the person who enters an order cannot approve it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jwt

from ..core.exceptions import ValidationError

ITERATIONS = 600_000
ALGORITHM = "HS256"
ISSUER = "meridian"
DEVELOPMENT_SECRET = "meridian-development-secret-change-me-0123456789"

PERMISSIONS: tuple[str, ...] = (
    "portfolio:read",
    "risk:read",
    "compliance:read",
    "tax:read",
    "report:read",
    "rebalance:propose",
    "orders:read",
    "orders:create",
    "orders:approve",
    "trading:read",
    "audit:read",
    "users:manage",
)

ROLES: dict[str, frozenset[str]] = {
    "client": frozenset({"portfolio:read", "report:read"}),
    "analyst": frozenset({"portfolio:read", "risk:read", "compliance:read", "tax:read", "report:read", "trading:read"}),
    "portfolio_manager": frozenset(
        {
            "portfolio:read",
            "risk:read",
            "compliance:read",
            "tax:read",
            "report:read",
            "rebalance:propose",
            "orders:read",
            "orders:create",
            "trading:read",
        }
    ),
    "trader": frozenset({"portfolio:read", "orders:read", "orders:create", "trading:read"}),
    "compliance_officer": frozenset(
        {
            "portfolio:read",
            "risk:read",
            "compliance:read",
            "tax:read",
            "report:read",
            "orders:read",
            "orders:approve",
            "trading:read",
            "audit:read",
        }
    ),
    "administrator": frozenset({"users:manage", "audit:read"}),
}


# ---------------------------------------------------------------------------- passwords
def hash_password(password: str, *, iterations: int = ITERATIONS, salt: bytes | None = None) -> str:
    if len(password) < 8:
        raise ValidationError("a password needs at least eight characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    encode = base64.b64encode
    return f"pbkdf2_sha256${iterations}${encode(salt).decode()}${encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
    return hmac.compare_digest(candidate, base64.b64decode(digest))


# ---------------------------------------------------------------------------- principals
@dataclass(frozen=True)
class Principal:
    """The authenticated caller of a request."""

    username: str
    roles: frozenset[str]
    portfolios: frozenset[str] | None = None  # None: every portfolio (staff)
    token_id: str = field(default="", compare=False)

    @property
    def permissions(self) -> frozenset[str]:
        granted: set[str] = set()
        for role in self.roles:
            granted |= ROLES.get(role, frozenset())
        return frozenset(granted)

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def sees(self, portfolio_id: str) -> bool:
        return self.portfolios is None or portfolio_id in self.portfolios


def roles_from(text: str) -> frozenset[str]:
    roles = frozenset(item.strip() for item in text.split(",") if item.strip())
    unknown = roles - ROLES.keys()
    if unknown:
        raise ValidationError(f"unknown roles: {', '.join(sorted(unknown))}")
    return roles


def portfolios_from(text: str | None) -> frozenset[str] | None:
    if text is None or not text.strip():
        return None
    return frozenset(item.strip() for item in text.split(",") if item.strip())


# ---------------------------------------------------------------------------- tokens
def issue_token(principal: Principal, secret: str, ttl_minutes: int, now: datetime | None = None) -> tuple[str, int]:
    now = now or datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ttl_minutes)
    claims = {
        "iss": ISSUER,
        "sub": principal.username,
        "roles": sorted(principal.roles),
        "portfolios": None if principal.portfolios is None else sorted(principal.portfolios),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM), ttl_minutes * 60


def read_token(token: str, secret: str) -> Principal:
    """The principal a token names; raises ``jwt.InvalidTokenError`` if it is forged, expired or malformed."""
    claims = jwt.decode(
        token, secret, algorithms=[ALGORITHM], issuer=ISSUER, options={"require": ["exp", "sub", "iss"]}
    )
    portfolios = claims.get("portfolios")
    return Principal(
        claims["sub"],
        frozenset(claims.get("roles", ())),
        None if portfolios is None else frozenset(portfolios),
        claims.get("jti", ""),
    )


def permission_matrix(roles: Iterable[str] = ROLES) -> list[tuple[str, list[bool]]]:
    """Role by permission, for documentation and the chart."""
    return [(role, [permission in ROLES[role] for permission in PERMISSIONS]) for role in roles]
