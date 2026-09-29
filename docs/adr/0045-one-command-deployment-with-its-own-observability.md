# 45. One-command deployment, with its own observability, tested in CI

- **Status:** Accepted
- **Date:** 2026-09-30

## Context

"It works on my machine" is not a deployment. A reviewer should be able to run the
whole platform - database, schema, API, monitoring - with one command. CI should
prove that the image builds and serves from a clean checkout.

## Decision

- A **multi-stage Dockerfile**:
  - dependencies built as wheels in their own layer (a code change does not rebuild
    them), then the platform's wheel;
  - a slim runtime with no compiler, a user without root, OCI labels and a
    `HEALTHCHECK`;
  - production mode by default.
- **Docker Compose** runs five services:
  - PostgreSQL 16, with a volume and a health check;
  - a **migration job** (`alembic upgrade head`) that must complete before the API
    starts;
  - the API (Uvicorn, two workers);
  - Prometheus, scraping `/metrics`;
  - Grafana, with a provisioned datasource and dashboard.
- **Metrics** come from `prometheus-client`: requests by method, route template and
  status; latency histograms by route; refusals; audit records; audit failures.
- **CI** gains a job that builds the image, starts the database, migration and API,
  and smoke-tests them: health, readiness, a login, a protected read, and a 401
  without a token.

## Consequences

- `docker compose up --build` gives:
  - the API at :8000/docs;
  - Grafana at :3000;
  - Prometheus at :9090.
  Each was verified locally against PostgreSQL, including 400 concurrent requests.
- Running the stack exposed two faults that a single process never shows, both fixed
  before release:
  - two workers seeding the demonstration users at once;
  - two workers appending to the audit chain at once.
- The compose file is for one machine. Kubernetes manifests, secrets management and
  TLS termination are a deployment's concern, noted rather than faked.
