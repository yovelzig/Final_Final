"""Maps between identity ORM rows and identity domain models.

`user_account_orm_to_domain` never reads `UserAccountORM.password_hash`
- the only function in this module that touches it is
`user_account_credential_from_row`, used exclusively by
`SqlAlchemyUserAccountRepository.get_credential_by_normalized_email`
(the one dedicated authentication read path). No other repository
method, and no code outside `infrastructure.database.repositories
.user_account_repository`, may call it.
"""

from __future__ import annotations

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.application.identity.ports import AccountCredential
from stock_research_core.domain.identity.enums import (
    AccountRole,
    AccountStatus,
    AuthenticationEventType,
    AuthenticationResult,
    RefreshTokenStatus,
)
from stock_research_core.domain.identity.models import (
    AccountRefreshToken,
    AuthenticationAuditEvent,
    UserAccount,
)
from stock_research_core.infrastructure.database.orm.account_refresh_token import AccountRefreshTokenORM
from stock_research_core.infrastructure.database.orm.authentication_audit_event import (
    AuthenticationAuditEventORM,
)
from stock_research_core.infrastructure.database.orm.user_account import UserAccountORM


def user_account_orm_to_domain(row: UserAccountORM) -> UserAccount:
    try:
        return UserAccount(
            account_id=row.account_id,
            email=row.email,
            normalized_email=row.normalized_email,
            display_name=row.display_name,
            learner_id=row.learner_id,
            role=AccountRole(row.role),
            status=AccountStatus(row.status),
            failed_login_count=row.failed_login_count,
            locked_until=row.locked_until,
            last_login_at=row.last_login_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored user account row '{row.account_id}' could not be mapped to a domain UserAccount."
        ) from exc


def user_account_credential_from_row(row: UserAccountORM) -> AccountCredential:
    """Authentication-only accessor. Never call this outside repository/auth code."""
    return AccountCredential(account=user_account_orm_to_domain(row), password_hash=row.password_hash)


def account_refresh_token_orm_to_domain(row: AccountRefreshTokenORM) -> AccountRefreshToken:
    try:
        return AccountRefreshToken(
            refresh_token_id=row.refresh_token_id,
            account_id=row.account_id,
            token_family_id=row.token_family_id,
            token_hash=row.token_hash,
            status=RefreshTokenStatus(row.status),
            issued_at=row.issued_at,
            expires_at=row.expires_at,
            rotated_at=row.rotated_at,
            revoked_at=row.revoked_at,
            replaced_by_token_id=row.replaced_by_token_id,
            user_agent_hash=row.user_agent_hash,
            client_ip_hash=row.client_ip_hash,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored refresh token row '{row.refresh_token_id}' could not be mapped to a domain "
            "AccountRefreshToken."
        ) from exc


def authentication_audit_event_orm_to_domain(row: AuthenticationAuditEventORM) -> AuthenticationAuditEvent:
    try:
        return AuthenticationAuditEvent(
            event_id=row.event_id,
            account_id=row.account_id,
            event_type=AuthenticationEventType(row.event_type),
            result=AuthenticationResult(row.result),
            correlation_id=row.correlation_id,
            email_hash=row.email_hash,
            client_ip_hash=row.client_ip_hash,
            user_agent_hash=row.user_agent_hash,
            reason_code=row.reason_code,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored authentication audit event row '{row.event_id}' could not be mapped to a domain "
            "AuthenticationAuditEvent."
        ) from exc
