"""Unit tests for `IdentityService` - register/login/refresh/logout/logout_all/
get_principal - against fake repositories (no SQLAlchemy, no PostgreSQL).

Uses the real `Argon2PasswordHasher`, `JwtAccessTokenService`, and
`OpaqueRefreshTokenService` infrastructure adapters (already covered by
their own dedicated unit tests) so these tests exercise the exact same
hashing/token machinery production does - only persistence is faked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.exceptions import (
    AccountDisabledError,
    AccountLockedError,
    AuthenticationFailedError,
    DuplicateAccountError,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
)
from stock_research_core.application.identity.models import AccessTokenClaims
from stock_research_core.application.identity.ports import AccountCredential
from stock_research_core.application.identity.service import IdentityService
from stock_research_core.domain.identity.enums import AccountRole, AccountStatus, RefreshTokenStatus
from stock_research_core.domain.identity.models import AccountRefreshToken, AuthenticationAuditEvent, UserAccount
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.infrastructure.identity.argon2_password_hasher import Argon2PasswordHasher
from stock_research_core.infrastructure.identity.jwt_access_token_service import JwtAccessTokenService
from stock_research_core.infrastructure.identity.opaque_refresh_token_service import OpaqueRefreshTokenService

_STRONG_PASSWORD = "Str0ng!Passw0rd"
_EMAIL = "learner@example.com"


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeLearnerRepository:
    def __init__(self) -> None:
        self.learners: dict[UUID, LearnerProfile] = {}

    async def create(self, learner: LearnerProfile) -> LearnerProfile:
        self.learners[learner.learner_id] = learner
        return learner


class FakeUserAccountRepository:
    def __init__(self) -> None:
        self.accounts: dict[UUID, UserAccount] = {}
        self.password_hashes: dict[UUID, str] = {}

    async def create_account(self, *, account: UserAccount, password_hash: str) -> UserAccount:
        self.accounts[account.account_id] = account
        self.password_hashes[account.account_id] = password_hash
        return account

    async def get_by_id(self, account_id: UUID) -> UserAccount | None:
        return self.accounts.get(account_id)

    async def get_by_normalized_email(self, normalized_email: str) -> UserAccount | None:
        return next((a for a in self.accounts.values() if a.normalized_email == normalized_email), None)

    async def get_credential_by_normalized_email(self, normalized_email: str) -> AccountCredential | None:
        account = await self.get_by_normalized_email(normalized_email)
        if account is None:
            return None
        return AccountCredential(account=account, password_hash=self.password_hashes[account.account_id])

    async def get_for_update(self, account_id: UUID) -> UserAccount | None:
        return self.accounts.get(account_id)

    async def normalized_email_exists(self, normalized_email: str) -> bool:
        return any(a.normalized_email == normalized_email for a in self.accounts.values())

    async def update_status(
        self, account_id: UUID, *, status: AccountStatus, locked_until: datetime | None
    ) -> UserAccount:
        updated = self.accounts[account_id].model_copy(update={"status": status, "locked_until": locked_until})
        self.accounts[account_id] = updated
        return updated

    async def update_login_counters(
        self,
        account_id: UUID,
        *,
        failed_login_count: int,
        last_login_at: datetime | None = None,
        status: AccountStatus | None = None,
        locked_until: datetime | None = None,
    ) -> UserAccount:
        update: dict = {"failed_login_count": failed_login_count}
        if last_login_at is not None:
            update["last_login_at"] = last_login_at
        if status is not None:
            update["status"] = status
        if status == AccountStatus.ACTIVE:
            update["locked_until"] = None
        elif locked_until is not None:
            update["locked_until"] = locked_until
        updated = self.accounts[account_id].model_copy(update=update)
        self.accounts[account_id] = updated
        return updated

    async def link_learner(self, account_id: UUID, learner_id: UUID) -> UserAccount:
        updated = self.accounts[account_id].model_copy(update={"learner_id": learner_id})
        self.accounts[account_id] = updated
        return updated

    async def change_password_hash(self, account_id: UUID, *, password_hash: str) -> UserAccount:
        self.password_hashes[account_id] = password_hash
        return self.accounts[account_id]

    async def list_accounts(
        self, *, role: AccountRole | None = None, status: AccountStatus | None = None,
        limit: int = 20, offset: int = 0,
    ) -> tuple[list[UserAccount], int]:
        values = list(self.accounts.values())
        if role is not None:
            values = [a for a in values if a.role == role]
        if status is not None:
            values = [a for a in values if a.status == status]
        return values[offset : offset + limit], len(values)


class FakeRefreshTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, AccountRefreshToken] = {}

    async def create_token(self, token: AccountRefreshToken) -> AccountRefreshToken:
        self.tokens[token.token_hash] = token
        return token

    async def get_by_hash(self, token_hash: str) -> AccountRefreshToken | None:
        return self.tokens.get(token_hash)

    async def rotate_token(
        self, *, token_hash: str, replacement: AccountRefreshToken, rotated_at: datetime
    ) -> AccountRefreshToken | None:
        current = self.tokens.get(token_hash)
        if current is None or current.status != RefreshTokenStatus.ACTIVE:
            return None  # CAS: no active token matched - concurrent rotation or reuse
        rotated = current.model_copy(
            update={"status": RefreshTokenStatus.ROTATED, "rotated_at": rotated_at,
                    "replaced_by_token_id": replacement.refresh_token_id}
        )
        self.tokens[token_hash] = rotated
        self.tokens[replacement.token_hash] = replacement
        return rotated

    async def revoke_token(self, refresh_token_id: UUID, *, revoked_at: datetime) -> AccountRefreshToken:
        for token_hash, token in self.tokens.items():
            if token.refresh_token_id == refresh_token_id:
                updated = token.model_copy(update={"status": RefreshTokenStatus.REVOKED, "revoked_at": revoked_at})
                self.tokens[token_hash] = updated
                return updated
        raise KeyError(refresh_token_id)

    async def revoke_family(self, token_family_id: UUID, *, revoked_at: datetime) -> int:
        count = 0
        for token_hash, token in list(self.tokens.items()):
            if token.token_family_id == token_family_id and token.status == RefreshTokenStatus.ACTIVE:
                self.tokens[token_hash] = token.model_copy(
                    update={"status": RefreshTokenStatus.REVOKED, "revoked_at": revoked_at}
                )
                count += 1
        return count

    async def revoke_all_for_account(self, account_id: UUID, *, revoked_at: datetime) -> int:
        count = 0
        for token_hash, token in list(self.tokens.items()):
            if token.account_id == account_id and token.status == RefreshTokenStatus.ACTIVE:
                self.tokens[token_hash] = token.model_copy(
                    update={"status": RefreshTokenStatus.REVOKED, "revoked_at": revoked_at}
                )
                count += 1
        return count

    async def list_active_sessions(self, account_id: UUID) -> list[AccountRefreshToken]:
        return [
            t for t in self.tokens.values() if t.account_id == account_id and t.status == RefreshTokenStatus.ACTIVE
        ]


class FakeAuthenticationAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuthenticationAuditEvent] = []

    async def append_event(self, event: AuthenticationAuditEvent) -> AuthenticationAuditEvent:
        self.events.append(event)
        return event

    async def list_recent_for_account(
        self, account_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[AuthenticationAuditEvent], int]:
        matches = [e for e in self.events if e.account_id == account_id]
        return matches[offset : offset + limit], len(matches)

    async def list_recent_security_events(
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[AuthenticationAuditEvent], int]:
        return self.events[offset : offset + limit], len(self.events)


class FakeUnitOfWork:
    def __init__(self, factory: "FakeUnitOfWorkFactory") -> None:
        self.learners = factory.learners
        self.user_accounts = factory.user_accounts
        self.refresh_tokens = factory.refresh_tokens
        self.authentication_audit = factory.authentication_audit
        self.committed = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


class FakeUnitOfWorkFactory:
    def __init__(self) -> None:
        self.learners = FakeLearnerRepository()
        self.user_accounts = FakeUserAccountRepository()
        self.refresh_tokens = FakeRefreshTokenRepository()
        self.authentication_audit = FakeAuthenticationAuditRepository()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self)


def _build_service(
    factory: FakeUnitOfWorkFactory, *, clock: Callable[[], datetime], max_failed_logins: int = 5,
    lockout_minutes: int = 15,
) -> IdentityService:
    return IdentityService(
        unit_of_work_factory=factory,
        password_hasher=Argon2PasswordHasher(),
        access_token_service=JwtAccessTokenService(secret="a" * 40),
        refresh_token_service=OpaqueRefreshTokenService(refresh_token_days=30),
        clock=clock,
        max_failed_logins=max_failed_logins,
        lockout_minutes=lockout_minutes,
    )


@pytest.fixture
def clock() -> _MutableClock:
    return _MutableClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def factory() -> FakeUnitOfWorkFactory:
    return FakeUnitOfWorkFactory()


@pytest.fixture
def service(factory: FakeUnitOfWorkFactory, clock: _MutableClock) -> IdentityService:
    return _build_service(factory, clock=clock)


class TestRegisterLearner:
    async def test_creates_account_and_learner_atomically(self, service: IdentityService, factory) -> None:
        result = await service.register_learner(
            email=_EMAIL, password=_STRONG_PASSWORD, display_name="Learner", correlation_id="c1"
        )
        assert result.account.learner_id == result.learner.learner_id
        assert result.account.role == AccountRole.LEARNER
        assert result.tokens.access_token
        assert result.tokens.refresh_token
        assert result.learner.learner_id in factory.learners.learners

    async def test_rejects_duplicate_email(self, service: IdentityService) -> None:
        await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        with pytest.raises(DuplicateAccountError):
            await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="B", correlation_id="c2")

    async def test_duplicate_email_check_is_case_insensitive(self, service: IdentityService) -> None:
        await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        with pytest.raises(DuplicateAccountError):
            await service.register_learner(
                email=_EMAIL.upper(), password=_STRONG_PASSWORD, display_name="B", correlation_id="c2"
            )

    async def test_password_hash_is_never_returned(self, service: IdentityService) -> None:
        result = await service.register_learner(
            email=_EMAIL, password=_STRONG_PASSWORD, display_name="Learner", correlation_id="c1"
        )
        assert not hasattr(result.account, "password_hash")
        assert _STRONG_PASSWORD not in result.model_dump_json()

    async def test_weak_password_is_rejected_before_any_persistence(
        self, service: IdentityService, factory: FakeUnitOfWorkFactory
    ) -> None:
        from stock_research_core.application.exceptions import InvalidPasswordError

        with pytest.raises(InvalidPasswordError):
            await service.register_learner(email=_EMAIL, password="short", display_name="A", correlation_id="c1")
        assert factory.user_accounts.accounts == {}
        assert factory.learners.learners == {}


class TestLogin:
    async def test_succeeds_with_correct_credentials(self, service: IdentityService) -> None:
        await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        result = await service.login(email=_EMAIL, password=_STRONG_PASSWORD, correlation_id="c2")
        assert result.account.email == _EMAIL
        assert result.tokens.access_token

    async def test_unknown_email_and_wrong_password_raise_the_same_generic_error(
        self, service: IdentityService
    ) -> None:
        await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")

        with pytest.raises(AuthenticationFailedError) as unknown_exc:
            await service.login(email="nobody@example.com", password=_STRONG_PASSWORD, correlation_id="c2")
        with pytest.raises(AuthenticationFailedError) as wrong_exc:
            await service.login(email=_EMAIL, password="WrongPassword123!", correlation_id="c3")

        assert str(unknown_exc.value) == str(wrong_exc.value)

    async def test_lockout_after_max_failed_attempts(
        self, factory: FakeUnitOfWorkFactory, clock: _MutableClock
    ) -> None:
        service = _build_service(factory, clock=clock, max_failed_logins=3, lockout_minutes=15)
        reg = await service.register_learner(
            email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1"
        )

        # The first two failures are ordinary wrong-password rejections.
        for _ in range(2):
            with pytest.raises(AuthenticationFailedError):
                await service.login(email=_EMAIL, password="wrong", correlation_id="c-fail")

        # The third failure crosses the threshold - it locks the account, but
        # this same call still reports the generic AuthenticationFailedError
        # (an attacker probing the boundary learns nothing new from it).
        with pytest.raises(AuthenticationFailedError):
            await service.login(email=_EMAIL, password="wrong", correlation_id="c-crosses-threshold")
        assert factory.user_accounts.accounts[reg.account.account_id].status == AccountStatus.LOCKED

        # Only a *subsequent* attempt against the now-locked account surfaces AccountLockedError.
        with pytest.raises(AccountLockedError):
            await service.login(email=_EMAIL, password="wrong", correlation_id="c-lock")

        # Even the CORRECT password is now rejected while locked.
        with pytest.raises(AccountLockedError):
            await service.login(email=_EMAIL, password=_STRONG_PASSWORD, correlation_id="c-still-locked")

    async def test_lock_expires_and_allows_login_again(
        self, factory: FakeUnitOfWorkFactory, clock: _MutableClock
    ) -> None:
        service = _build_service(factory, clock=clock, max_failed_logins=1, lockout_minutes=15)
        await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")

        # The single failure immediately crosses the threshold and locks the account.
        with pytest.raises(AuthenticationFailedError):
            await service.login(email=_EMAIL, password="wrong", correlation_id="c-lock")
        # A subsequent attempt against the now-locked account is denied outright.
        with pytest.raises(AccountLockedError):
            await service.login(email=_EMAIL, password=_STRONG_PASSWORD, correlation_id="c-denied-while-locked")

        clock.now += timedelta(minutes=16)
        result = await service.login(email=_EMAIL, password=_STRONG_PASSWORD, correlation_id="c-unlock")
        assert result.account.status == AccountStatus.ACTIVE

    async def test_disabled_account_cannot_log_in(self, service: IdentityService, factory: FakeUnitOfWorkFactory) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        await factory.user_accounts.update_status(reg.account.account_id, status=AccountStatus.DISABLED, locked_until=None)
        with pytest.raises(AccountDisabledError):
            await service.login(email=_EMAIL, password=_STRONG_PASSWORD, correlation_id="c2")

    async def test_successful_login_resets_failed_login_count(
        self, factory: FakeUnitOfWorkFactory, clock: _MutableClock
    ) -> None:
        service = _build_service(factory, clock=clock, max_failed_logins=5)
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")

        with pytest.raises(AuthenticationFailedError):
            await service.login(email=_EMAIL, password="wrong", correlation_id="c-fail")
        assert factory.user_accounts.accounts[reg.account.account_id].failed_login_count == 1

        await service.login(email=_EMAIL, password=_STRONG_PASSWORD, correlation_id="c-success")
        assert factory.user_accounts.accounts[reg.account.account_id].failed_login_count == 0


class TestRefresh:
    async def test_rotates_token_and_returns_a_new_pair(self, service: IdentityService) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        new_tokens = await service.refresh(refresh_token=reg.tokens.refresh_token, correlation_id="c2")
        assert new_tokens.refresh_token != reg.tokens.refresh_token
        assert new_tokens.access_token != reg.tokens.access_token

    async def test_reused_rotated_token_is_rejected_and_revokes_the_family(self, service: IdentityService) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        new_tokens = await service.refresh(refresh_token=reg.tokens.refresh_token, correlation_id="c2")

        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh(refresh_token=reg.tokens.refresh_token, correlation_id="c-reuse")

        # The entire family (including the token issued by the rotation above) is now dead.
        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh(refresh_token=new_tokens.refresh_token, correlation_id="c-after-reuse")

    async def test_unknown_token_is_rejected(self, service: IdentityService) -> None:
        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh(refresh_token="not-a-real-token", correlation_id="c1")

    async def test_expired_token_is_rejected(self, factory: FakeUnitOfWorkFactory, clock: _MutableClock) -> None:
        service = _build_service(factory, clock=clock)
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        clock.now += timedelta(days=31)
        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh(refresh_token=reg.tokens.refresh_token, correlation_id="c2")


class TestLogout:
    async def test_logout_revokes_the_token(self, service: IdentityService, factory: FakeUnitOfWorkFactory) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        await service.logout(refresh_token=reg.tokens.refresh_token, correlation_id="c2")
        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh(refresh_token=reg.tokens.refresh_token, correlation_id="c3")

    async def test_logout_is_idempotent(self, service: IdentityService) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        await service.logout(refresh_token=reg.tokens.refresh_token, correlation_id="c2")
        await service.logout(refresh_token=reg.tokens.refresh_token, correlation_id="c3")  # must not raise

    async def test_logout_of_unknown_token_does_not_raise(self, service: IdentityService) -> None:
        await service.logout(refresh_token="never-issued", correlation_id="c1")

    async def test_logout_all_revokes_every_active_session(self, service: IdentityService) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        second_login = await service.login(email=_EMAIL, password=_STRONG_PASSWORD, correlation_id="c2")

        count = await service.logout_all(account_id=reg.account.account_id, correlation_id="c3")
        assert count == 2

        for token in (reg.tokens.refresh_token, second_login.tokens.refresh_token):
            with pytest.raises(InvalidRefreshTokenError):
                await service.refresh(refresh_token=token, correlation_id="c4")


class TestGetPrincipal:
    async def test_resolves_a_valid_token_to_a_principal(self, service: IdentityService) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        claims = AccessTokenClaims(
            subject=reg.account.account_id, learner_id=reg.account.learner_id, role=AccountRole.LEARNER,
            issued_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            token_id=uuid4(), issuer="finquest", audience="finquest-api",
        )
        principal = await service.get_principal(claims)
        assert principal.account_id == reg.account.account_id
        assert principal.learner_id == reg.account.learner_id
        assert principal.role == AccountRole.LEARNER

    async def test_rejects_claims_for_a_deleted_account(self, service: IdentityService) -> None:
        claims = AccessTokenClaims(
            subject=uuid4(), learner_id=None, role=AccountRole.LEARNER,
            issued_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            token_id=uuid4(), issuer="finquest", audience="finquest-api",
        )
        with pytest.raises(InvalidAccessTokenError):
            await service.get_principal(claims)

    async def test_rejects_when_account_role_no_longer_matches_the_token(
        self, service: IdentityService, factory: FakeUnitOfWorkFactory
    ) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        await factory.user_accounts.list_accounts()  # no-op, just exercising the fake
        factory.user_accounts.accounts[reg.account.account_id] = factory.user_accounts.accounts[
            reg.account.account_id
        ].model_copy(update={"role": AccountRole.ADMIN})

        claims = AccessTokenClaims(
            subject=reg.account.account_id, learner_id=reg.account.learner_id, role=AccountRole.LEARNER,
            issued_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            token_id=uuid4(), issuer="finquest", audience="finquest-api",
        )
        with pytest.raises(InvalidAccessTokenError):
            await service.get_principal(claims)

    async def test_rejects_a_disabled_account(self, service: IdentityService, factory: FakeUnitOfWorkFactory) -> None:
        reg = await service.register_learner(email=_EMAIL, password=_STRONG_PASSWORD, display_name="A", correlation_id="c1")
        await factory.user_accounts.update_status(reg.account.account_id, status=AccountStatus.DISABLED, locked_until=None)

        claims = AccessTokenClaims(
            subject=reg.account.account_id, learner_id=reg.account.learner_id, role=AccountRole.LEARNER,
            issued_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            token_id=uuid4(), issuer="finquest", audience="finquest-api",
        )
        with pytest.raises(AccountDisabledError):
            await service.get_principal(claims)
