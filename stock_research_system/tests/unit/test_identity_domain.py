"""Unit tests for the identity domain models (`UserAccount`,
`AccountRefreshToken`, `AuthenticationAuditEvent`) - pure Pydantic
validation, no I/O, no fakes needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.identity.enums import (
    AccountRole,
    AccountStatus,
    AuthenticationEventType,
    AuthenticationResult,
    RefreshTokenStatus,
)
from stock_research_core.domain.identity.models import AccountRefreshToken, AuthenticationAuditEvent, UserAccount

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_VALID_HASH = "a" * 64


def _account(**overrides: object) -> UserAccount:
    defaults: dict = dict(email="Learner@Example.com", normalized_email="learner@example.com", display_name="L")
    defaults.update(overrides)
    return UserAccount(**defaults)


class TestUserAccount:
    def test_normalizes_email_case_and_whitespace(self) -> None:
        account = UserAccount(email="  Foo@Example.COM  ", normalized_email="foo@example.com", display_name="F")
        assert account.normalized_email == "foo@example.com"

    def test_normalized_email_must_match_email(self) -> None:
        with pytest.raises(ValidationError):
            _account(email="a@example.com", normalized_email="different@example.com")

    def test_locked_status_requires_locked_until(self) -> None:
        with pytest.raises(ValidationError):
            _account(status=AccountStatus.LOCKED, locked_until=None)
        # Valid when locked_until is present.
        account = _account(status=AccountStatus.LOCKED, locked_until=NOW + timedelta(minutes=15))
        assert account.status == AccountStatus.LOCKED

    def test_active_status_forbids_lingering_locked_until(self) -> None:
        with pytest.raises(ValidationError):
            _account(status=AccountStatus.ACTIVE, locked_until=NOW + timedelta(minutes=15))

    def test_defaults_are_learner_and_active(self) -> None:
        account = _account()
        assert account.role == AccountRole.LEARNER
        assert account.status == AccountStatus.ACTIVE
        assert account.learner_id is None
        assert account.failed_login_count == 0

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            _account(password_hash="should-never-be-a-field")

    def test_rejects_blank_display_name(self) -> None:
        with pytest.raises(ValidationError):
            _account(display_name="")


class TestAccountRefreshToken:
    def _token(self, **overrides: object) -> AccountRefreshToken:
        defaults: dict = dict(
            account_id=uuid4(), token_hash=_VALID_HASH, issued_at=NOW, expires_at=NOW + timedelta(days=30)
        )
        defaults.update(overrides)
        return AccountRefreshToken(**defaults)

    def test_token_hash_must_look_like_a_hash(self) -> None:
        with pytest.raises(ValidationError):
            self._token(token_hash="not-a-hex-hash!!")

    def test_token_hash_is_lowercased(self) -> None:
        token = self._token(token_hash=_VALID_HASH.upper())
        assert token.token_hash == _VALID_HASH

    def test_expires_at_must_follow_issued_at(self) -> None:
        with pytest.raises(ValidationError):
            self._token(issued_at=NOW, expires_at=NOW - timedelta(seconds=1))

    def test_rotated_status_requires_rotation_fields(self) -> None:
        with pytest.raises(ValidationError):
            self._token(status=RefreshTokenStatus.ROTATED)
        token = self._token(
            status=RefreshTokenStatus.ROTATED, rotated_at=NOW, replaced_by_token_id=uuid4()
        )
        assert token.status == RefreshTokenStatus.ROTATED

    def test_revoked_status_requires_revoked_at(self) -> None:
        with pytest.raises(ValidationError):
            self._token(status=RefreshTokenStatus.REVOKED)
        token = self._token(status=RefreshTokenStatus.REVOKED, revoked_at=NOW)
        assert token.revoked_at == NOW

    def test_optional_hashes_validated_when_present(self) -> None:
        with pytest.raises(ValidationError):
            self._token(client_ip_hash="not-hex")
        token = self._token(client_ip_hash=_VALID_HASH.upper())
        assert token.client_ip_hash == _VALID_HASH

    def test_never_carries_a_raw_token_field(self) -> None:
        assert "raw_token" not in AccountRefreshToken.model_fields
        assert "token" not in AccountRefreshToken.model_fields


class TestAuthenticationAuditEvent:
    def _event(self, **overrides: object) -> AuthenticationAuditEvent:
        defaults: dict = dict(
            event_type=AuthenticationEventType.LOGIN_SUCCEEDED, result=AuthenticationResult.SUCCESS,
            correlation_id="corr-1",
        )
        defaults.update(overrides)
        return AuthenticationAuditEvent(**defaults)

    def test_account_id_is_optional_for_unknown_accounts(self) -> None:
        event = self._event(account_id=None)
        assert event.account_id is None

    def test_reason_code_must_be_upper_snake_case(self) -> None:
        with pytest.raises(ValidationError):
            self._event(reason_code="not valid free text!")
        event = self._event(reason_code="duplicate_email")
        assert event.reason_code == "DUPLICATE_EMAIL"

    def test_email_hash_must_look_like_a_hash(self) -> None:
        with pytest.raises(ValidationError):
            self._event(email_hash="plaintext@example.com")

    def test_never_carries_a_password_or_token_field(self) -> None:
        forbidden = {"password", "password_hash", "token", "refresh_token", "access_token"}
        assert forbidden.isdisjoint(AuthenticationAuditEvent.model_fields.keys())
