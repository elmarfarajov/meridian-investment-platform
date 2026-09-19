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
