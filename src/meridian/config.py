"""Runtime configuration.

Settings come from the environment with a ``MERIDIAN_`` prefix, so the same image
runs against SQLite on a laptop and PostgreSQL in CI or production without code
changes. Defaults are chosen so a fresh clone works with no configuration at all.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MERIDIAN_", env_file=".env", extra="ignore")

    database_url: str = Field(default=f"sqlite:///{(DEFAULT_DATA_DIR / 'meridian.sqlite').as_posix()}")
    echo_sql: bool = False
    base_currency: str = "USD"
    default_calendar: str = "XNYS"
    data_dir: Path = DEFAULT_DATA_DIR
    cache_dir: Path = DEFAULT_DATA_DIR / "cache"
    reports_dir: Path = PROJECT_ROOT / "reports"
    log_level: str = "INFO"
    log_json: bool = False
    # ------------------------------------------------------------------ the web platform
    #: signs the API's access tokens. The default is for a laptop only; the service refuses to start
    #: in production mode with it (see meridian.api.app)
    jwt_secret: str = "meridian-development-secret-change-me-0123456789"
    jwt_ttl_minutes: int = 30
    environment: str = "development"  # development | production
    api_rate_limit: int = 120  # requests per minute per user
    four_eyes_threshold: float = 250_000.0  # orders above this value need a second person's approval
    demo_users: bool = True  # create the demonstration users on start-up if there are none
    password_iterations: int = 600_000  # PBKDF2-SHA256 work factor (OWASP 2023); lowered only in tests

    @field_validator("environment")
    @classmethod
    def _environment(cls, value: str) -> str:
        if value not in ("development", "production"):
            raise ValueError("environment must be development or production")
        return value

    @field_validator("base_currency")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.cache_dir, self.reports_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests that patch the environment."""
    get_settings.cache_clear()
