"""Structured logging.

Every log line is a dict with a timestamp and an event name. On a terminal it is
rendered for humans; with ``MERIDIAN_LOG_JSON=true`` it becomes one JSON object
per line, which is what a log aggregator wants. The reason for structure rather
than formatted strings is auditability: when a valuation or a trade is
questioned months later, the answer has to be greppable by portfolio and by
identifier, not buried in prose.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from .config import Settings, get_settings

_configured = False


def configure_logging(settings: Settings | None = None, *, force: bool = False) -> None:
    """Configure structlog once per process."""
    global _configured
    if _configured and not force:
        return
    settings = settings or get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if settings.log_json:
        processors.append(structlog.processors.format_exc_info)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
