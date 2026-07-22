"""Application-level identity models: the authenticated-principal view,
token claims/results, and composite registration/login results.

Plain Pydantic models; no SQLAlchemy, FastAPI, PyJWT, or pwdlib
dependency here. `IssuedTokenPair` is transport-sensitive - it carries
the raw refresh token only at the moment of issuance and is never
persisted (only its hash is, via `AccountRefreshToken.token_hash`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stock_research_core.domain.identity.enums import AccountRole
from stock_research_core.domain.identity.models import UserAccount
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import DomainModel


class AuthenticatedPrincipal(DomainModel):
    """The identity of the caller behind the current request, derived from a validated access token."""

    account_id: UUID
    learner_id: UUID | None
    role: AccountRole
    email: str
    display_name: str


class AccessTokenClaims(DomainModel):
    """The validated claim set decoded from an access token."""

    subject: UUID
    learner_id: UUID | None
    role: AccountRole
    issued_at: datetime
    expires_at: datetime
    token_id: UUID
    issuer: str = Field(min_length=1)
    audience: str = Field(min_length=1)


class IssuedTokenPair(DomainModel):
    """One freshly issued access/refresh token pair.

    Contains the raw refresh token only at issuance time - never
    persist this model. Only `AccountRefreshToken.token_hash` (its
    SHA-256 hash) is ever stored.
    """

    access_token: str = Field(min_length=1)
    access_token_expires_at: datetime
    refresh_token: str = Field(min_length=1)
    refresh_token_expires_at: datetime
    token_type: str = Field(default="bearer", min_length=1)


class RegistrationResult(DomainModel):
    """The outcome of a successful learner registration."""

    account: UserAccount
    learner: LearnerProfile
    tokens: IssuedTokenPair


class LoginResult(DomainModel):
    """The outcome of a successful login."""

    account: UserAccount
    tokens: IssuedTokenPair
