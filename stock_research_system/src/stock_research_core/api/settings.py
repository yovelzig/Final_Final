"""API-specific configuration.

Reads settings from environment variables (and an optional `.env`
file), matching `infrastructure.database.config.DatabaseSettings` and
`infrastructure.ai_tutor.config`. Importing this module never validates
a JWT secret or opens a connection - `AuthSettings.require_strong_secret()`
is called explicitly by `api.app_factory.create_app()` at startup, not
at import time.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from stock_research_core.infrastructure.identity.jwt_access_token_service import assert_secret_is_strong


class ApiSettings(BaseSettings):
    """FastAPI application, CORS, and rate-limit configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_title: str = "FinQuest API"
    api_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    api_cors_origins: str = "http://localhost:3000"
    api_docs_enabled: bool = True
    api_rate_limit_enabled: bool = True
    api_login_rate_limit: int = 10
    api_login_rate_window_seconds: int = 60

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


class AuthSettings(BaseSettings):
    """JWT access-token, refresh-token, and account-lockout configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    auth_jwt_secret: str = ""
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_issuer: str = "finquest"
    auth_jwt_audience: str = "finquest-api"
    auth_access_token_minutes: int = 15

    auth_refresh_token_days: int = 30

    auth_max_failed_logins: int = 5
    auth_lockout_minutes: int = 15

    def require_strong_secret(self, *, testing: bool = False) -> None:
        """Refuse startup with an absent or obviously weak JWT secret outside test mode."""
        assert_secret_is_strong(self.auth_jwt_secret, allow_weak_for_tests=testing)
