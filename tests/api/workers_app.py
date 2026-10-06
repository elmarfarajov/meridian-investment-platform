"""The platform as Uvicorn serves it in several worker processes, with the tests' stand-in for the modules.

``uvicorn workers_app:app --app-dir tests/api --workers 4`` starts it; the settings
come from the environment, as in the container.
"""

from __future__ import annotations

from conftest import FakeData
from meridian.api.app import create_app
from meridian.config import Settings

app = create_app(Settings(), FakeData())
