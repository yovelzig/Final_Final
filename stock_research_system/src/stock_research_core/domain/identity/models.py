"""Domain models for the FinQuest identity/authentication subsystem.

Technology-independent: no SQLAlchemy, FastAPI, PyJWT, pwdlib, or HTTP
library import may appear here. None of these models may ever carry a
password hash, access token, refresh token, or signing key - secrets
live only in infrastructure-internal records
(`infrastructure.database.mappers.identity_mappers`) that a public
mapper never returns.

`UserAccount` is a distinct identity concept from
`domain.learning.models.LearnerProfile`: it references a learner only
by UUID (`learner_id`), never by an embedded object, matching the same
"other entities are plain UUIDs" convention used throughout this
codebase (e.g. `domain.virtual_portfolio`).
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import EmailStr, Field, ValidationInfo, field_validator, model_validator

from stock_research_core.domain.identity.enums import (
    AccountRole,
    AccountStatus,
    AuthenticationEventType,
    AuthenticationResult,
    RefreshTokenStatus,
)
from stock_research_core.domain.models import DomainModel, utc_now

_HASH_PATTERN = re.compile(r"^[0-9a-f]{16,128}$")
_REASON_CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


def _validate_hash_like(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if not _HASH_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a lowercase hexadecimal hash, not a raw value")
    return normalized


class UserAccount(DomainModel):
    """A local authentication identity. Never carries a password hash or token."""

    account_id: UUID = Field(default_factory=uuid4)
    email: EmailStr
    normalized_email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=150)

    learner_id: UUID | None = None
    role: AccountRole = AccountRole.LEARNER
    status: AccountStatus = AccountStatus.ACTIVE

    failed_login_count: int = Field(default=0, ge=0)
    locked_until: datetime | None = None
    last_login_at: datetime | None = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("normalized_email")
    @classmethod
    def _normalize_email_field(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def _validate_account(self) -> UserAccount:
        if self.normalized_email != str(self.email).strip().lower():
            raise ValueError("normalized_email must be the lowercase, trimmed form of email")
        if self.status == AccountStatus.LOCKED and self.locked_until is None:
            raise ValueError("a LOCKED account requires locked_until")
        if self.status == AccountStatus.ACTIVE and self.locked_until is not None:
            raise ValueError(
                "an ACTIVE account must not have a lingering locked_until value - unlocking must clear it"
            )
        return self


class AccountRefreshToken(DomainModel):
    """Metadata for one issued refresh token. The raw token never appears here - only its hash."""

    refresh_token_id: UUID = Field(default_factory=uuid4)
    account_id: UUID

    token_family_id: UUID = Field(default_factory=uuid4)
    token_hash: str = Field(min_length=32, max_length=128)
    status: RefreshTokenStatus = RefreshTokenStatus.ACTIVE

    issued_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by_token_id: UUID | None = None

    user_agent_hash: str | None = Field(default=None, max_length=128)
    client_ip_hash: str | None = Field(default=None, max_length=128)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("token_hash")
    @classmethod
    def _validate_token_hash(cls, value: str) -> str:
        return _validate_hash_like(value, "token_hash")

    @field_validator("user_agent_hash", "client_ip_hash")
    @classmethod
    def _validate_optional_hash(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _validate_hash_like(value, info.field_name)

    @model_validator(mode="after")
    def _validate_token(self) -> AccountRefreshToken:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must follow issued_at")
        if self.status == RefreshTokenStatus.ROTATED and (
            self.rotated_at is None or self.replaced_by_token_id is None
        ):
            raise ValueError("a ROTATED token requires rotated_at and replaced_by_token_id")
        if self.status == RefreshTokenStatus.REVOKED and self.revoked_at is None:
            raise ValueError("a REVOKED token requires revoked_at")
        return self


class AuthenticationAuditEvent(DomainModel):
    """One immutable authentication/security audit record. Never carries a password or token."""

    event_id: UUID = Field(default_factory=uuid4)
    account_id: UUID | None = None

    event_type: AuthenticationEventType
    result: AuthenticationResult

    correlation_id: str = Field(min_length=1, max_length=200)
    email_hash: str | None = Field(default=None, max_length=128)
    client_ip_hash: str | None = Field(default=None, max_length=128)
    user_agent_hash: str | None = Field(default=None, max_length=128)

    reason_code: str | None = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("email_hash", "client_ip_hash", "user_agent_hash")
    @classmethod
    def _validate_optional_hash(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _validate_hash_like(value, info.field_name)

    @field_validator("reason_code")
    @classmethod
    def _validate_reason_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not _REASON_CODE_PATTERN.fullmatch(normalized):
            raise ValueError("reason_code must be a sanitized UPPER_SNAKE_CASE identifier, not free text")
        return normalized
