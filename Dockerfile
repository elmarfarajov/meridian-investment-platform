# syntax=docker/dockerfile:1.7
# Meridian Investment Platform - the API image.
#
# Two stages: the first builds wheels for the platform and its dependencies,
# the second installs them into a slim runtime with no compiler, as a user
# without root, and checks its own health.

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10
WORKDIR /src
# the dependencies first, in a layer of their own: a change to the platform's code does not rebuild them
COPY pyproject.toml ./
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
[print(item) for item in p['dependencies'] + p['optional-dependencies']['postgres']]" > requirements.txt \
    && pip wheel --wheel-dir /wheels -r requirements.txt
COPY README.md LICENSE ./
COPY src ./src
RUN pip wheel --no-deps --wheel-dir /wheels .

FROM python:${PYTHON_VERSION}-slim AS runtime
LABEL org.opencontainers.image.title="meridian-investment-platform" \
      org.opencontainers.image.description="Institutional investment platform: accounting, performance, risk, compliance, tax-aware rebalancing, execution and reporting" \
      org.opencontainers.image.source="https://github.com/elmarfarajov/meridian-investment-platform" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    MERIDIAN_ENVIRONMENT=production MERIDIAN_LOG_JSON=true \
    MERIDIAN_DATA_DIR=/var/lib/meridian MERIDIAN_REPORTS_DIR=/var/lib/meridian/reports
RUN groupadd --system meridian && useradd --system --gid meridian --home /var/lib/meridian meridian \
    && mkdir -p /var/lib/meridian/reports && chown -R meridian:meridian /var/lib/meridian
COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels
WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
USER meridian
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "meridian.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "2"]
