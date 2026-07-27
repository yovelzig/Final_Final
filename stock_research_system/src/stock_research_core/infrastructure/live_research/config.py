"""Configuration for Live Research provider infrastructure adapters
(Phase G2A1: Perplexity Search, SEC EDGAR).

Reads settings from environment variables (and an optional `.env` file),
matching `infrastructure.database.config`'s pattern. Both providers
default to disabled (`..._enabled=False`) - the safe, rollback-neutral
setting. Importing or constructing either settings class never makes a
network call, and constructing a *disabled* settings object never
requires a secret (API key / User-Agent) to be set.
"""

from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
DEFAULT_SEC_BASE_URL = "https://data.sec.gov"

_MAX_PERPLEXITY_MAX_RESULTS = 20
_MAX_TOKEN_BOUND = 100_000
_MAX_SEC_REQUESTS_PER_SECOND = 10.0
_MAX_SEC_USER_AGENT_LENGTH = 250

_EMAIL_PATTERN = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


def _require_finite_positive(name: str, value: float) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{name} must not be a bool")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and greater than zero, got {value!r}")


def _looks_like_declared_identity(user_agent: str) -> bool:
    """True if `user_agent` looks like `<product/company> <contact>` - at
    least two whitespace-separated tokens, one of which is an email
    address or a URL. Mirrors SEC's own fair-access guidance (e.g.
    `"Sample Company Name AdminContact@sample.com"`)."""
    tokens = user_agent.split()
    if len(tokens) < 2:
        return False
    return any(
        _EMAIL_PATTERN.match(token.strip(",;()<>")) or _URL_PATTERN.match(token) for token in tokens
    )


def _contains_control_characters(value: str) -> bool:
    """True if `value` contains an ASCII control character (0x00-0x1F or
    0x7F) - e.g. a null byte or an embedded CR/LF that could otherwise be
    used to smuggle extra header lines or corrupt logs."""
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)


def _normalize_https_base_url(name: str, value: str) -> str:
    """Validates and normalizes an HTTPS base URL, shared by both
    `BaseSettings` validation and direct adapter construction:

    - strips surrounding whitespace
    - requires the scheme to be exactly `https`
    - requires a hostname
    - rejects an embedded username/password
    - rejects a query string or fragment
    - returns the value with any trailing slash removed
    """
    stripped = value.strip()
    parsed = urlsplit(stripped)
    if parsed.scheme != "https":
        raise ValueError(f"{name} must use https://")
    if not parsed.hostname:
        raise ValueError(f"{name} must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} must not embed username/password credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not include a query or fragment component")
    return stripped.rstrip("/")


class PerplexitySearchSettings(BaseSettings):
    """Perplexity Search API adapter configuration.

    `live_research_perplexity_enabled=False` (the default) requires no
    API key and performs no validation beyond the numeric bounds below -
    deploying this settings class alone changes nothing until a separate,
    reviewed activation step flips the flag.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    live_research_perplexity_enabled: bool = False
    live_research_perplexity_base_url: str = DEFAULT_PERPLEXITY_BASE_URL
    live_research_perplexity_api_key: SecretStr = SecretStr("")
    live_research_perplexity_timeout_seconds: float = 30.0
    live_research_perplexity_max_results: int = 10
    live_research_perplexity_max_tokens: int = 10_000
    live_research_perplexity_max_tokens_per_page: int = 4_096

    @field_validator(
        "live_research_perplexity_max_tokens", "live_research_perplexity_max_tokens_per_page", mode="before"
    )
    @classmethod
    def _reject_bool_or_float_tokens(cls, value: Any) -> Any:
        # Runs before Pydantic's own int coercion (which would otherwise
        # silently accept a bool as 0/1, or a whole-number float as int).
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError("must be an int, not a bool or float")
        return value

    @model_validator(mode="after")
    def _validate(self) -> "PerplexitySearchSettings":
        raw_key = self.live_research_perplexity_api_key.get_secret_value()
        if raw_key and not raw_key.strip():
            raise ValueError("live_research_perplexity_api_key must not be whitespace-only")
        self.live_research_perplexity_api_key = SecretStr(raw_key.strip())

        if self.live_research_perplexity_enabled:
            if not self.live_research_perplexity_api_key.get_secret_value():
                raise ValueError(
                    "live_research_perplexity_api_key is required when "
                    "live_research_perplexity_enabled is True"
                )
            self.live_research_perplexity_base_url = _normalize_https_base_url(
                "live_research_perplexity_base_url", self.live_research_perplexity_base_url
            )
        _require_finite_positive(
            "live_research_perplexity_timeout_seconds", self.live_research_perplexity_timeout_seconds
        )
        if not (1 <= self.live_research_perplexity_max_results <= _MAX_PERPLEXITY_MAX_RESULTS):
            raise ValueError(
                f"live_research_perplexity_max_results must be within [1, {_MAX_PERPLEXITY_MAX_RESULTS}]"
            )
        if not (0 < self.live_research_perplexity_max_tokens <= _MAX_TOKEN_BOUND):
            raise ValueError(
                f"live_research_perplexity_max_tokens must be within (0, {_MAX_TOKEN_BOUND}]"
            )
        if not (0 < self.live_research_perplexity_max_tokens_per_page <= _MAX_TOKEN_BOUND):
            raise ValueError(
                f"live_research_perplexity_max_tokens_per_page must be within (0, {_MAX_TOKEN_BOUND}]"
            )
        return self


class SecEdgarSettings(BaseSettings):
    """SEC EDGAR public data API adapter configuration.

    `live_research_sec_enabled=False` (the default) requires no declared
    User-Agent. There is no authentication token here on purpose - SEC
    EDGAR's public data APIs require only a declared, contactable
    User-Agent identity, never an API key.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    live_research_sec_enabled: bool = False
    live_research_sec_base_url: str = DEFAULT_SEC_BASE_URL
    live_research_sec_user_agent: str = ""
    live_research_sec_timeout_seconds: float = 30.0
    live_research_sec_requests_per_second: float = 5.0

    @field_validator("live_research_sec_timeout_seconds", "live_research_sec_requests_per_second", mode="before")
    @classmethod
    def _reject_bool_numeric_inputs(cls, value: Any) -> Any:
        # Runs before Pydantic's own float coercion (which would
        # otherwise silently accept a bool as 0.0/1.0).
        if isinstance(value, bool):
            raise ValueError("must not be a bool")
        return value

    @model_validator(mode="after")
    def _validate(self) -> "SecEdgarSettings":
        stripped_user_agent = self.live_research_sec_user_agent.strip()
        if len(stripped_user_agent) > _MAX_SEC_USER_AGENT_LENGTH:
            raise ValueError(
                f"live_research_sec_user_agent must be at most {_MAX_SEC_USER_AGENT_LENGTH} characters"
            )
        if _contains_control_characters(stripped_user_agent):
            raise ValueError("live_research_sec_user_agent must not contain control characters")
        self.live_research_sec_user_agent = stripped_user_agent

        if self.live_research_sec_enabled:
            if not stripped_user_agent:
                raise ValueError(
                    "live_research_sec_user_agent is required when live_research_sec_enabled is True"
                )
            if not _looks_like_declared_identity(stripped_user_agent):
                raise ValueError(
                    "live_research_sec_user_agent must declare a product/company identity and contact "
                    "information (an email address or a URL), e.g. 'FinQuest research@example.com'"
                )
            self.live_research_sec_base_url = _normalize_https_base_url(
                "live_research_sec_base_url", self.live_research_sec_base_url
            )
        _require_finite_positive("live_research_sec_timeout_seconds", self.live_research_sec_timeout_seconds)
        if not math.isfinite(self.live_research_sec_requests_per_second) or (
            self.live_research_sec_requests_per_second <= 0
        ):
            raise ValueError("live_research_sec_requests_per_second must be finite and greater than zero")
        if self.live_research_sec_requests_per_second > _MAX_SEC_REQUESTS_PER_SECOND:
            raise ValueError(
                f"live_research_sec_requests_per_second must not exceed {_MAX_SEC_REQUESTS_PER_SECOND}"
            )
        return self
