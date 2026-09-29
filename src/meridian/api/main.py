"""The ASGI entry point: ``uvicorn meridian.api.main:app``."""

from __future__ import annotations

from ..observability import configure_logging
from .app import create_app

configure_logging()
app = create_app()
