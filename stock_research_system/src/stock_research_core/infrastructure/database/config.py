"""Database configuration settings.

Reads connection settings from environment variables (and an optional
`.env` file). Importing this module never opens a connection or creates
an engine — it only describes how one *would* be created.
"""

from __future__ import annotations

import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DATABASE_URL = "postgresql+asyncpg://stock_user:stock_password@localhost:5433/stock_research"
_DEV_TEST_DATABASE_URL = (
    "postgresql+asyncpg://stock_user:stock_password@localhost:5433/stock_research_test"
)
_CREDENTIALS_PATTERN = re.compile(r"//([^:/@]+):([^@/]+)@")


def mask_database_url(url: str) -> str:
    """Return `url` with the password (and username) hidden for safe display."""
    return _CREDENTIALS_PATTERN.sub(r"//\1:***@", url)


class DatabaseSettings(BaseSettings):
    """Database connection settings, sourced from the environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = _DEV_DATABASE_URL
    test_database_url: str | None = _DEV_TEST_DATABASE_URL
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10

    @field_validator("database_url")
    @classmethod
    def _require_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql"):
            raise ValueError(
                "database_url must be a PostgreSQL connection string "
                "(e.g. 'postgresql+asyncpg://...'); SQLite is not supported outside tests."
            )
        return value

    @field_validator("test_database_url")
    @classmethod
    def _require_postgresql_for_tests(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("postgresql"):
            raise ValueError(
                "test_database_url must be a PostgreSQL connection string "
                "(e.g. 'postgresql+asyncpg://...')."
            )
        return value

    def masked_database_url(self) -> str:
        return mask_database_url(self.database_url)

    def masked_test_database_url(self) -> str | None:
        return mask_database_url(self.test_database_url) if self.test_database_url else None
