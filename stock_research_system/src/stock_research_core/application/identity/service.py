"""`IdentityService`: registration, login, refresh, logout, and
principal resolution for the FinQuest identity subsystem.

Depends only on Protocols (`PasswordHasherPort`, `AccessTokenServicePort`,
`RefreshTokenServicePort`) and the shared `UnitOfWorkPort` - no
SQLAlchemy, FastAPI, PyJWT, or pwdlib import here. Every public method
runs inside exactly one Unit of Work (one transaction); on any raised
exception the transaction is never committed (`SqlAlchemyUnitOfWork
.__aexit__` rolls back), so a failure never leaves a half-created
account or a rotated-but-unresigned token pair.

Login always returns the same generic `AuthenticationFailedError` for
"no such account" and "wrong password" - never revealing whether an
email is registered.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from stock_research_core.application.exceptions import (
    AccountDisabledError,
    AccountLockedError,
    AuthenticationFailedError,
    DuplicateAccountError,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
)
from stock_research_core.application.identity.models import (
    AccessTokenClaims,
    AuthenticatedPrincipal,
    IssuedTokenPair,
    LoginResult,
    RegistrationResult,
)
from stock_research_core.application.identity.ports import (
    AccessTokenServicePort,
    PasswordHasherPort,
    RefreshTokenServicePort,
)
from stock_research_core.application.identity.security import validate_password_policy
from stock_research_core.domain.identity.enums import (
    AccountRole,
    AccountStatus,
    AuthenticationEventType,
    AuthenticationResult,
    RefreshTokenStatus,
)
from stock_research_core.domain.identity.models import AccountRefreshToken, AuthenticationAuditEvent, UserAccount
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import utc_now

DEFAULT_MAX_FAILED_LOGINS = 5
DEFAULT_LOCKOUT_MINUTES = 15

Clock = Callable[[], datetime]


def _hash_email(normalized_email: str) -> str:
    return hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()


class IdentityService:
    """Registration, authentication, and session lifecycle for local FinQuest accounts."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], Any],
        password_hasher: PasswordHasherPort,
        access_token_service: AccessTokenServicePort,
        refresh_token_service: RefreshTokenServicePort,
        clock: Clock = utc_now,
        max_failed_logins: int = DEFAULT_MAX_FAILED_LOGINS,
        lockout_minutes: int = DEFAULT_LOCKOUT_MINUTES,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._password_hasher = password_hasher
        self._access_token_service = access_token_service
        self._refresh_token_service = refresh_token_service
        self._clock = clock
        self._max_failed_logins = max_failed_logins
        self._lockout_minutes = lockout_minutes

    # -- registration -----------------------------------------------

    async def register_learner(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        preferred_language: str = "en",
        daily_goal_minutes: int = 10,
        correlation_id: str,
        client_ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> RegistrationResult:
        normalized_email = email.strip().lower()
        validate_password_policy(password, normalized_email=normalized_email)

        async with self._unit_of_work_factory() as uow:
            if await uow.user_accounts.normalized_email_exists(normalized_email):
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.ACCOUNT_CREATED, result=AuthenticationResult.FAILURE,
                    correlation_id=correlation_id, account_id=None, email_hash=_hash_email(normalized_email),
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code="DUPLICATE_EMAIL",
                )
                await uow.commit()
                raise DuplicateAccountError("An account with this email address already exists.")

            created_learner = await uow.learners.create(
                LearnerProfile(
                    display_name=display_name, preferred_language=preferred_language,
                    daily_goal_minutes=daily_goal_minutes,
                )
            )

            password_hash = await asyncio.to_thread(self._password_hasher.hash_password, password)
            account = UserAccount(
                email=email, normalized_email=normalized_email, display_name=display_name,
                learner_id=created_learner.learner_id, role=AccountRole.LEARNER, status=AccountStatus.ACTIVE,
            )
            created_account = await uow.user_accounts.create_account(account=account, password_hash=password_hash)

            tokens, _refresh_row = await self._issue_token_pair(
                uow, account=created_account, client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash
            )

            await self._append_audit(
                uow, event_type=AuthenticationEventType.ACCOUNT_CREATED, result=AuthenticationResult.SUCCESS,
                correlation_id=correlation_id, account_id=created_account.account_id, email_hash=None,
                client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code=None,
            )
            await uow.commit()

        return RegistrationResult(account=created_account, learner=created_learner, tokens=tokens)

    # -- login -----------------------------------------------

    async def login(
        self,
        *,
        email: str,
        password: str,
        correlation_id: str,
        client_ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> LoginResult:
        normalized_email = email.strip().lower()
        now = self._clock()

        async with self._unit_of_work_factory() as uow:
            credential = await uow.user_accounts.get_credential_by_normalized_email(normalized_email)
            if credential is None:
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.LOGIN_FAILED, result=AuthenticationResult.FAILURE,
                    correlation_id=correlation_id, account_id=None, email_hash=_hash_email(normalized_email),
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code="UNKNOWN_ACCOUNT",
                )
                await uow.commit()
                raise AuthenticationFailedError("Invalid email or password.")

            account = credential.account

            if account.status == AccountStatus.LOCKED and account.locked_until is not None and account.locked_until <= now:
                account = await uow.user_accounts.update_status(
                    account.account_id, status=AccountStatus.ACTIVE, locked_until=None
                )
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.ACCOUNT_UNLOCKED, result=AuthenticationResult.SUCCESS,
                    correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code="LOCK_EXPIRED",
                )

            if account.status == AccountStatus.DISABLED:
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.LOGIN_FAILED, result=AuthenticationResult.DENIED,
                    correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code="ACCOUNT_DISABLED",
                )
                await uow.commit()
                raise AccountDisabledError("This account is disabled.")

            if account.status == AccountStatus.LOCKED:
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.LOGIN_FAILED, result=AuthenticationResult.DENIED,
                    correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code="ACCOUNT_LOCKED",
                )
                await uow.commit()
                raise AccountLockedError("This account is temporarily locked. Try again later.")

            try:
                password_ok = await asyncio.to_thread(
                    self._password_hasher.verify_password, password, credential.password_hash
                )
            except Exception:  # noqa: BLE001 - a malformed stored hash must fail closed, never 500
                password_ok = False

            if not password_ok:
                failed_count = account.failed_login_count + 1
                if failed_count >= self._max_failed_logins:
                    locked_until = now + timedelta(minutes=self._lockout_minutes)
                    await uow.user_accounts.update_login_counters(
                        account.account_id, failed_login_count=failed_count, status=AccountStatus.LOCKED,
                        locked_until=locked_until,
                    )
                    await self._append_audit(
                        uow, event_type=AuthenticationEventType.ACCOUNT_LOCKED, result=AuthenticationResult.DENIED,
                        correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                        client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash,
                        reason_code="MAX_FAILED_LOGINS",
                    )
                else:
                    await uow.user_accounts.update_login_counters(
                        account.account_id, failed_login_count=failed_count
                    )
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.LOGIN_FAILED, result=AuthenticationResult.FAILURE,
                    correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code="INVALID_PASSWORD",
                )
                await uow.commit()
                raise AuthenticationFailedError("Invalid email or password.")

            if await asyncio.to_thread(self._password_hasher.needs_rehash, credential.password_hash):
                new_hash = await asyncio.to_thread(self._password_hasher.hash_password, password)
                await uow.user_accounts.change_password_hash(account.account_id, password_hash=new_hash)
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.PASSWORD_CHANGED, result=AuthenticationResult.SUCCESS,
                    correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code="REHASH",
                )

            updated_account = await uow.user_accounts.update_login_counters(
                account.account_id, failed_login_count=0, last_login_at=now
            )

            tokens, _refresh_row = await self._issue_token_pair(
                uow, account=updated_account, client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash
            )

            await self._append_audit(
                uow, event_type=AuthenticationEventType.LOGIN_SUCCEEDED, result=AuthenticationResult.SUCCESS,
                correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code=None,
            )
            await uow.commit()

        return LoginResult(account=updated_account, tokens=tokens)

    # -- refresh -----------------------------------------------

    async def refresh(
        self,
        *,
        refresh_token: str,
        correlation_id: str,
        client_ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> IssuedTokenPair:
        now = self._clock()
        token_hash = self._refresh_token_service.hash_token(refresh_token)

        async with self._unit_of_work_factory() as uow:
            stored = await uow.refresh_tokens.get_by_hash(token_hash)
            if stored is None:
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.TOKEN_REFRESHED, result=AuthenticationResult.FAILURE,
                    correlation_id=correlation_id, account_id=None, email_hash=None, client_ip_hash=client_ip_hash,
                    user_agent_hash=user_agent_hash, reason_code="TOKEN_NOT_FOUND",
                )
                await uow.commit()
                raise InvalidRefreshTokenError("The refresh token is invalid.")

            if stored.status != RefreshTokenStatus.ACTIVE:
                await uow.refresh_tokens.revoke_family(stored.token_family_id, revoked_at=now)
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.TOKEN_REVOKED, result=AuthenticationResult.DENIED,
                    correlation_id=correlation_id, account_id=stored.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash,
                    reason_code="TOKEN_REUSE_DETECTED",
                )
                await uow.commit()
                raise InvalidRefreshTokenError("This refresh token has already been used or revoked.")

            if stored.expires_at <= now:
                await uow.refresh_tokens.revoke_token(stored.refresh_token_id, revoked_at=now)
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.TOKEN_REFRESHED, result=AuthenticationResult.FAILURE,
                    correlation_id=correlation_id, account_id=stored.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code="TOKEN_EXPIRED",
                )
                await uow.commit()
                raise InvalidRefreshTokenError("This refresh token has expired.")

            account = await uow.user_accounts.get_by_id(stored.account_id)
            if account is None or account.status in (AccountStatus.DISABLED, AccountStatus.LOCKED):
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.TOKEN_REFRESHED, result=AuthenticationResult.DENIED,
                    correlation_id=correlation_id, account_id=stored.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash,
                    reason_code="ACCOUNT_NOT_ELIGIBLE",
                )
                await uow.commit()
                raise InvalidRefreshTokenError("This account cannot refresh its session.")

            raw_new_token = self._refresh_token_service.generate_token()
            new_token_hash = self._refresh_token_service.hash_token(raw_new_token)
            new_expires_at = self._refresh_token_service.calculate_expiration(issued_at=now)
            replacement = AccountRefreshToken(
                account_id=account.account_id, token_family_id=stored.token_family_id, token_hash=new_token_hash,
                status=RefreshTokenStatus.ACTIVE, issued_at=now, expires_at=new_expires_at,
                user_agent_hash=user_agent_hash, client_ip_hash=client_ip_hash,
            )
            rotated = await uow.refresh_tokens.rotate_token(
                token_hash=token_hash, replacement=replacement, rotated_at=now
            )
            if rotated is None:
                await uow.refresh_tokens.revoke_family(stored.token_family_id, revoked_at=now)
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.TOKEN_REVOKED, result=AuthenticationResult.DENIED,
                    correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                    client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash,
                    reason_code="CONCURRENT_ROTATION_LOST",
                )
                await uow.commit()
                raise InvalidRefreshTokenError("This refresh token has already been used or revoked.")

            access_token, access_claims = self._access_token_service.issue_access_token(
                account_id=account.account_id, learner_id=account.learner_id, role=account.role
            )

            await self._append_audit(
                uow, event_type=AuthenticationEventType.TOKEN_REFRESHED, result=AuthenticationResult.SUCCESS,
                correlation_id=correlation_id, account_id=account.account_id, email_hash=None,
                client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash, reason_code=None,
            )
            await uow.commit()

        return IssuedTokenPair(
            access_token=access_token, access_token_expires_at=access_claims.expires_at,
            refresh_token=raw_new_token, refresh_token_expires_at=new_expires_at,
        )

    # -- logout -----------------------------------------------

    async def logout(self, *, refresh_token: str, correlation_id: str) -> None:
        """Idempotent: revoking an already-inactive or unknown token is not an error."""
        now = self._clock()
        token_hash = self._refresh_token_service.hash_token(refresh_token)

        async with self._unit_of_work_factory() as uow:
            stored = await uow.refresh_tokens.get_by_hash(token_hash)
            if stored is not None and stored.status == RefreshTokenStatus.ACTIVE:
                await uow.refresh_tokens.revoke_token(stored.refresh_token_id, revoked_at=now)
                await self._append_audit(
                    uow, event_type=AuthenticationEventType.LOGOUT_COMPLETED, result=AuthenticationResult.SUCCESS,
                    correlation_id=correlation_id, account_id=stored.account_id, email_hash=None,
                    client_ip_hash=None, user_agent_hash=None, reason_code=None,
                )
            await uow.commit()

    async def logout_all(self, *, account_id: UUID, correlation_id: str) -> int:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            revoked_count = await uow.refresh_tokens.revoke_all_for_account(account_id, revoked_at=now)
            await self._append_audit(
                uow, event_type=AuthenticationEventType.LOGOUT_COMPLETED, result=AuthenticationResult.SUCCESS,
                correlation_id=correlation_id, account_id=account_id, email_hash=None, client_ip_hash=None,
                user_agent_hash=None, reason_code=None,
            )
            await uow.commit()
        return revoked_count

    # -- principal resolution -----------------------------------------------

    async def get_principal(self, claims: AccessTokenClaims) -> AuthenticatedPrincipal:
        async with self._unit_of_work_factory() as uow:
            account = await uow.user_accounts.get_by_id(claims.subject)

        if account is None:
            raise InvalidAccessTokenError("The account for this token no longer exists.")
        if account.status == AccountStatus.DISABLED:
            raise AccountDisabledError("This account is disabled.")
        if account.status == AccountStatus.LOCKED:
            raise AccountLockedError("This account is temporarily locked.")
        if account.role != claims.role:
            raise InvalidAccessTokenError("This token's role no longer matches the account.")
        if account.learner_id != claims.learner_id:
            raise InvalidAccessTokenError("This token's learner claim no longer matches the account.")

        return AuthenticatedPrincipal(
            account_id=account.account_id, learner_id=account.learner_id, role=account.role,
            email=account.email, display_name=account.display_name,
        )

    # -- internal helpers -----------------------------------------------

    async def _issue_token_pair(
        self, uow: Any, *, account: UserAccount, client_ip_hash: str | None, user_agent_hash: str | None
    ) -> tuple[IssuedTokenPair, AccountRefreshToken]:
        now = self._clock()
        raw_refresh_token = self._refresh_token_service.generate_token()
        token_hash = self._refresh_token_service.hash_token(raw_refresh_token)
        expires_at = self._refresh_token_service.calculate_expiration(issued_at=now)

        refresh_token_row = AccountRefreshToken(
            account_id=account.account_id, token_hash=token_hash, status=RefreshTokenStatus.ACTIVE,
            issued_at=now, expires_at=expires_at, user_agent_hash=user_agent_hash, client_ip_hash=client_ip_hash,
        )
        created_token = await uow.refresh_tokens.create_token(refresh_token_row)

        access_token, claims = self._access_token_service.issue_access_token(
            account_id=account.account_id, learner_id=account.learner_id, role=account.role
        )
        tokens = IssuedTokenPair(
            access_token=access_token, access_token_expires_at=claims.expires_at,
            refresh_token=raw_refresh_token, refresh_token_expires_at=expires_at,
        )
        return tokens, created_token

    async def _append_audit(
        self,
        uow: Any,
        *,
        event_type: AuthenticationEventType,
        result: AuthenticationResult,
        correlation_id: str,
        account_id: UUID | None,
        email_hash: str | None,
        client_ip_hash: str | None,
        user_agent_hash: str | None,
        reason_code: str | None,
    ) -> None:
        event = AuthenticationAuditEvent(
            account_id=account_id, event_type=event_type, result=result, correlation_id=correlation_id,
            email_hash=email_hash, client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash,
            reason_code=reason_code,
        )
        await uow.authentication_audit.append_event(event)
