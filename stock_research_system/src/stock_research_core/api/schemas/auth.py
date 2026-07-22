"""Request/response DTOs for `/api/v1/auth/*`.

`PublicAccount` never carries `password_hash`, `failed_login_count`, or
`locked_until` - the only account fields ever serialized here are the
ones a legitimate owner (or an admin, via `admin.py`'s own DTOs) should
see.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.application.identity.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from stock_research_core.domain.identity.enums import AccountRole, AccountStatus
from stock_research_core.domain.identity.models import UserAccount
from stock_research_core.domain.learning.enums import DifficultyLevel
from stock_research_core.domain.learning.models import LearnerProfile


class RegisterRequest(ApiSchema):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    display_name: str = Field(min_length=1, max_length=150)
    preferred_language: str = Field(default="en", min_length=2, max_length=10)
    daily_goal_minutes: int = Field(default=10, ge=5, le=180)


class LoginRequest(ApiSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RefreshRequest(ApiSchema):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(ApiSchema):
    refresh_token: str = Field(min_length=1)


class TokenPairResponse(ApiSchema):
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    token_type: str


class PublicAccount(ApiSchema):
    account_id: UUID
    email: str
    display_name: str
    learner_id: UUID | None
    role: AccountRole
    status: AccountStatus
    created_at: datetime
    last_login_at: datetime | None

    @staticmethod
    def from_domain(account: UserAccount) -> PublicAccount:
        return PublicAccount(
            account_id=account.account_id, email=account.email, display_name=account.display_name,
            learner_id=account.learner_id, role=account.role, status=account.status,
            created_at=account.created_at, last_login_at=account.last_login_at,
        )


class PublicLearner(ApiSchema):
    learner_id: UUID
    display_name: str
    preferred_language: str
    financial_experience_level: DifficultyLevel
    daily_goal_minutes: int
    active: bool
    created_at: datetime

    @staticmethod
    def from_domain(learner: LearnerProfile) -> PublicLearner:
        return PublicLearner(
            learner_id=learner.learner_id, display_name=learner.display_name,
            preferred_language=learner.preferred_language,
            financial_experience_level=learner.financial_experience_level,
            daily_goal_minutes=learner.daily_goal_minutes, active=learner.active,
            created_at=learner.created_at,
        )


class RegisterResponse(ApiSchema):
    account: PublicAccount
    learner: PublicLearner
    tokens: TokenPairResponse


class LoginResponse(ApiSchema):
    account: PublicAccount
    tokens: TokenPairResponse


class MeResponse(ApiSchema):
    account: PublicAccount
    learner: PublicLearner | None


class LogoutAllResponse(ApiSchema):
    revoked_session_count: int
