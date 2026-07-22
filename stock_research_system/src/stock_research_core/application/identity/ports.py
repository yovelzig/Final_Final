"""Application-level Protocols for the identity/authentication subsystem.

Pure `Protocol` definitions - no SQLAlchemy, FastAPI, PyJWT, or pwdlib
import here. Concrete implementations live under
`stock_research_core.infrastructure.identity` (password hashing, JWT,
opaque refresh tokens, rate limiting) and
`stock_research_core.infrastructure.database.repositories` (the 3
identity repositories).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import Field

from stock_research_core.application.identity.models import AccessTokenClaims
from stock_research_core.domain.identity.enums import AccountRole, AccountStatus
from stock_research_core.domain.identity.models import (
    AccountRefreshToken,
    AuthenticationAuditEvent,
    UserAccount,
)
from stock_research_core.domain.models import DomainModel


class AccountCredential(DomainModel):
    """Infrastructure-safe carrier for a stored password hash.

    Only ever produced by `UserAccountRepositoryPort.get_credential_by_normalized_email`
    and consumed inside `IdentityService`'s login/password-change flows -
    never returned across the API boundary, never logged.
    """

    account: UserAccount
    password_hash: str = Field(min_length=1)


class PasswordHasherPort(Protocol):
    """Hashes and verifies passwords. Implementations must run off the event loop when async."""

    def hash_password(self, password: str) -> str: ...

    def verify_password(self, password: str, password_hash: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class AccessTokenServicePort(Protocol):
    """Issues and validates short-lived JWT access tokens."""

    def issue_access_token(
        self, *, account_id: UUID, learner_id: UUID | None, role: AccountRole
    ) -> tuple[str, AccessTokenClaims]: ...

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        """Decode and fully validate `token` (signature, issuer, audience, expiration,
        required claims). Raises `InvalidAccessTokenError` on any failure."""
        ...


class RefreshTokenServicePort(Protocol):
    """Generates, hashes, and verifies opaque refresh tokens."""

    def generate_token(self) -> str: ...

    def hash_token(self, raw_token: str) -> str: ...

    def verify_token(self, raw_token: str, token_hash: str) -> bool: ...

    def calculate_expiration(self, *, issued_at: datetime) -> datetime: ...


class RateLimiterPort(Protocol):
    """Deterministic rate-limit check. The initial implementation is process-local only."""

    async def check(self, *, key: str, limit: int, window_seconds: int) -> bool: ...


class UserAccountRepositoryPort(Protocol):
    """Persists and queries `UserAccount` rows. Password hashes never cross this Protocol
    except through `create_account`/`change_password_hash` (write) and
    `get_credential_by_normalized_email` (the one dedicated read path)."""

    async def create_account(self, *, account: UserAccount, password_hash: str) -> UserAccount: ...

    async def get_by_id(self, account_id: UUID) -> UserAccount | None: ...

    async def get_by_normalized_email(self, normalized_email: str) -> UserAccount | None: ...

    async def get_credential_by_normalized_email(
        self, normalized_email: str
    ) -> AccountCredential | None: ...

    async def get_for_update(self, account_id: UUID) -> UserAccount | None: ...

    async def normalized_email_exists(self, normalized_email: str) -> bool: ...

    async def update_status(
        self, account_id: UUID, *, status: AccountStatus, locked_until: datetime | None
    ) -> UserAccount: ...

    async def update_login_counters(
        self,
        account_id: UUID,
        *,
        failed_login_count: int,
        last_login_at: datetime | None = None,
        status: AccountStatus | None = None,
        locked_until: datetime | None = None,
    ) -> UserAccount: ...

    async def link_learner(self, account_id: UUID, learner_id: UUID) -> UserAccount: ...

    async def change_password_hash(self, account_id: UUID, *, password_hash: str) -> UserAccount: ...

    async def list_accounts(
        self,
        *,
        role: AccountRole | None = None,
        status: AccountStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[UserAccount], int]: ...


class RefreshTokenRepositoryPort(Protocol):
    """Persists and queries refresh-token metadata (never the raw token)."""

    async def create_token(self, token: AccountRefreshToken) -> AccountRefreshToken: ...

    async def get_by_hash(self, token_hash: str) -> AccountRefreshToken | None:
        """Look up a token by hash regardless of status - required for reuse detection."""
        ...

    async def rotate_token(
        self, *, token_hash: str, replacement: AccountRefreshToken, rotated_at: datetime
    ) -> AccountRefreshToken | None:
        """Atomically transition the ACTIVE token at `token_hash` to ROTATED and persist
        `replacement`. Returns the (updated) rotated-from token, or `None` if no ACTIVE
        token matched `token_hash` (a concurrent rotation already won, or reuse of an
        already-rotated token) - the compare-and-swap that guarantees at most one
        successful replacement under concurrent refresh."""
        ...

    async def revoke_token(self, refresh_token_id: UUID, *, revoked_at: datetime) -> AccountRefreshToken: ...

    async def revoke_family(self, token_family_id: UUID, *, revoked_at: datetime) -> int: ...

    async def revoke_all_for_account(self, account_id: UUID, *, revoked_at: datetime) -> int: ...

    async def list_active_sessions(self, account_id: UUID) -> list[AccountRefreshToken]: ...


class AuthenticationAuditRepositoryPort(Protocol):
    """Appends and queries immutable authentication/security audit events."""

    async def append_event(self, event: AuthenticationAuditEvent) -> AuthenticationAuditEvent: ...

    async def list_recent_for_account(
        self, account_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[AuthenticationAuditEvent], int]: ...

    async def list_recent_security_events(
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[AuthenticationAuditEvent], int]: ...
