# The web platform

Eight days built the modules a portfolio management firm runs on:
- market data;
- the book of record;
- performance;
- risk;
- compliance;
- tax-aware rebalancing;
- execution and the client report.

The ninth puts one service in front of them. A firm can then give its clients, its
analysts, its portfolio managers, its traders and its compliance officers access to
exactly what each of them should see, and prove afterwards who saw and did what.

**Implementation:** [`api/app.py`](../../src/meridian/api/app.py),
[`api/routes.py`](../../src/meridian/api/routes.py),
[`api/security.py`](../../src/meridian/api/security.py),
[`api/data.py`](../../src/meridian/api/data.py),
[`core/audit_chain.py`](../../src/meridian/core/audit_chain.py),
[`persistence/platform_repositories.py`](../../src/meridian/persistence/platform_repositories.py),
[`Dockerfile`](../../Dockerfile), [`docker-compose.yml`](../../docker-compose.yml) ·
**Decisions:** [ADR 0041](../adr/0041-the-api-serves-the-modules-it-does-not-compute.md) to
[ADR 0045](../adr/0045-one-command-deployment-with-its-own-observability.md)

---

## 1. One service over the same objects

The API computes nothing. Every endpoint:
1. checks who is asking;
2. asks a data facade;
3. shapes the answer with a response model.

The facade asks the module that owns the answer. So a number served over HTTP is the
number the command line prints and the client report shows. The API's tests check this
directly: the valuation served equals the Day 3 book's NAV, and a pre-trade check of a
$100,000 Microsoft purchase comes back blocked with a largest allowed order of $85,976,
the Day 6 answer.

The facade is a `Protocol`. The web layer is therefore tested twice:
- against a small in-memory stand-in, which is fast and exact about every status code;
- against the real modules.

**21 endpoints**, versioned under `/v1`, described by an OpenAPI 3.1 document that the
code generates. Each records the permission it requires as `x-permission`, so the
contract states who may call it.

## 2. Seven layers between a request and the data

| Layer | What it does | On failure |
| --- | --- | --- |
| request id | taken from `X-Request-ID` or generated; returned, logged, audited | — |
| authentication | an HMAC-SHA256 JWT: signature, issuer, expiry; and the account must still exist and be active | 401, one message for every cause |
| authorisation | the endpoint's permission against the caller's roles, read from the account on each request | 403 |
| entitlement | a client's portfolios, from their own record | 404, as if absent |
| rate limit | a token bucket per user | 429 with `Retry-After` |
| idempotency | a write's `Idempotency-Key`: the stored response on a retry | 409 if the body differs |
| audit and metrics | every request appended to the hash chain, counted in Prometheus | readiness fails if the chain breaks |

**Passwords** are stored as salted PBKDF2-HMAC-SHA256 at 600,000 iterations (OWASP
2023) and compared in constant time. Signing in costs a few hundred milliseconds. That is
deliberate: every guess costs an attacker the same. Since the
[Day 9 revisit](the-platform-under-load.md) that holds for a username that does not exist
too. Day 9 skipped the hash there, and the time told an attacker which names were real.

**The service will not start unsafe.** In production it refuses to run with the
development signing key, and it refuses any key shorter than 32 characters.

## 3. Roles, permissions, entitlements

| Role | Permissions |
| --- | --- |
| client | portfolio:read, report:read - own portfolios only |
| analyst | all the analytics reads, trading costs |
| portfolio manager | the analytics, proposing rebalances, entering orders |
| trader | entering orders, trading costs |
| compliance officer | the analytics, approving orders, the audit log |
| administrator | managing users, the audit log - and no client data |

Endpoints check **permissions**, never roles, so a new role is a line in a table. Two
duties are separated:
- whoever **enters** an order cannot **approve** it;
- the **administrator**, who can create users, cannot read a client's portfolio or trade.

**Entitlements** answer an unentitled portfolio with the same 404 as a missing one. A
client can therefore not discover which other portfolios exist.

## 4. Orders under four eyes

An order entered through the API is checked against the mandate before it exists. The
Day 6 engine runs on the portfolio the order would leave. Then:

| Situation | Outcome |
| --- | --- |
| the mandate blocks it | refused with 422, the reasons, and the largest order that would pass |
| up to $250,000, and the mandate allows it | **approved** |
| above $250,000, or the mandate needs an override | **pending approval** |

A pending order is decided by a second person with `orders:approve`. Deciding one's own
order is refused (403) even for a user who holds both roles. The decision is one
conditional update on a pending order. If two approvers act at once, one decides it and
the other is told it was decided (409).

## 5. A tamper-evident audit trail

Every request, allowed or refused, becomes a record:
- who made it, when, what it asked;
- the answer and how long it took;
- the idempotency key.

Each record is chained:

```
record_hash = SHA-256(previous_hash ‖ canonical JSON of the record)
```

Each record therefore commits to everything before it, and tampering shows up as
follows:

| Tampering | How it shows |
| --- | --- |
| a field edited | that record's hash no longer matches |
| a record deleted | a gap in the sequence |
| a record re-sealed after an edit | the next record's link breaks |

`/v1/audit/verify` walks the chain. The readiness probe fails when the chain is broken,
so a deployment whose log was doctored stops taking traffic. A Hypothesis property test
edits any field of any record of a generated chain and checks that verification points
at exactly that record.

Two practical points:
- **Timestamps are hashed as UTC without their zone.** PostgreSQL gives back
  zone-aware times and SQLite naive ones; the hash has to survive both.
- **Appending is optimistic across processes.** Two Uvicorn workers can read the same
  head. The second insert then collides on the sequence number (the primary key) and
  retries against the new head, so the chain never forks. Tested with 400 concurrent
  requests against the Docker deployment: 408 records, chain intact. Appending one
  record at a time is also the throughput limit. A deployment at scale would seal
  batches (a Merkle tree per batch) and anchor the head hash outside the database.

## 6. Retrying safely

Networks time out after the server has acted. A client that retries a "create order"
can create it twice. Writes therefore accept an `Idempotency-Key`:
- the first request's response is stored under the key, per user, with a fingerprint
  of the body;
- a retry with the same key and body gets the stored response, marked
  `Idempotent-Replayed: true`, and nothing is done again;
- the same key with a different body is refused with 409;
- the order and its key are stored in one transaction, so a retry that arrives at the
  same moment as the original gets the original's answer. It never gets a second order,
  and never a 500.

## 7. A working day, measured

`meridian.devtools.workload` drives the API over HTTP against the real modules, as
seven people would:

| Person | What they do |
| --- | --- |
| the client | reads her reports, and tries once to see the risk model |
| the analyst | reads the analytics |
| the portfolio manager | checks and enters orders, and once retries after a timeout |
| the trader | enters orders, reads trading costs |
| compliance | approves and rejects orders, reads and verifies the audit log |
| the administrator | verifies the chain |
| an intruder | guesses passwords and presents a forged token |

The charts show what the platform recorded about itself, from its Prometheus metrics
and its audit log:
- about 590 requests;
- 23 refused for want of a valid token and 9 for want of permission;
- the mandate blocking the oversized orders;
- reads served in tens of milliseconds, the audit write included;
- the chain intact at the end.

## 8. Running it

```bash
docker compose up --build
```

| Service | What it is |
| --- | --- |
| **db** | PostgreSQL 16 with a named volume |
| **migrate** | `alembic upgrade head`, which must complete before the API starts |
| **api** | the image, served by Uvicorn with 2 workers |
| **prometheus** | scrapes `/metrics` every five seconds |
| **grafana** | a provisioned Prometheus datasource and the Meridian dashboard |

The API image is multi-stage. The dependencies are built as wheels in their own layer,
so a code change does not rebuild them. The runtime has no compiler, runs as a user
without root, and checks its own health.

CI builds the image, starts the stack, and smoke-tests it: health, readiness, a login,
a protected read, and a 401 without a token.

## What is not here

| Missing | What a deployment would add |
| --- | --- |
| single sign-on | OpenID Connect against the firm's identity provider instead of local passwords (an account switched off locally is refused at once, but sessions are not listed or revoked one by one) |
| TLS | terminated at a reverse proxy in front of the API |
| a shared rate limit | Redis, so the limit holds across workers and containers |
| external anchoring of the audit chain | the head hash published outside the database |
| write endpoints for the book of record | the ledger is replayed from its blotter, as on Day 3 |
