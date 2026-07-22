"""Unit tests for `JwtAccessTokenService` and `assert_secret_is_strong`.

No database, no HTTP - pure PyJWT round-trip behavior.
"""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest

from stock_research_core.application.exceptions import InvalidAccessTokenError
from stock_research_core.domain.identity.enums import AccountRole
from stock_research_core.infrastructure.identity.jwt_access_token_service import (
    JwtAccessTokenService,
    assert_secret_is_strong,
)

_STRONG_SECRET = "a" * 40


def _service(**overrides: object) -> JwtAccessTokenService:
    defaults: dict = dict(secret=_STRONG_SECRET)
    defaults.update(overrides)
    return JwtAccessTokenService(**defaults)


class TestAssertSecretIsStrong:
    def test_rejects_empty_secret(self) -> None:
        with pytest.raises(InvalidAccessTokenError):
            assert_secret_is_strong("")

    def test_rejects_short_secret(self) -> None:
        with pytest.raises(InvalidAccessTokenError):
            assert_secret_is_strong("short")

    def test_rejects_well_known_placeholder_even_if_padded_to_length(self) -> None:
        # "changeme" alone is short enough to already fail the length check;
        # this confirms the exact-match placeholder deny-list is also checked
        # (case/whitespace-insensitively) for a value that clears the length bar.
        with pytest.raises(InvalidAccessTokenError):
            assert_secret_is_strong("  ChangeMe  " + " " * 25)

    def test_accepts_strong_secret(self) -> None:
        assert_secret_is_strong(_STRONG_SECRET)

    def test_allow_weak_for_tests_bypasses_every_check(self) -> None:
        assert_secret_is_strong("", allow_weak_for_tests=True)
        assert_secret_is_strong("changeme", allow_weak_for_tests=True)


class TestJwtAccessTokenServiceConstruction:
    def test_refuses_construction_with_a_weak_secret(self) -> None:
        with pytest.raises(InvalidAccessTokenError):
            JwtAccessTokenService(secret="weak")

    def test_allows_weak_secret_when_explicitly_flagged_for_tests(self) -> None:
        JwtAccessTokenService(secret="", allow_weak_secret_for_tests=True)


class TestIssueAndDecode:
    def test_round_trips_claims(self) -> None:
        service = _service()
        account_id, learner_id = uuid4(), uuid4()

        token, issued_claims = service.issue_access_token(
            account_id=account_id, learner_id=learner_id, role=AccountRole.LEARNER
        )
        decoded = service.decode_access_token(token)

        assert decoded.subject == account_id == issued_claims.subject
        assert decoded.learner_id == learner_id
        assert decoded.role == AccountRole.LEARNER
        assert decoded.token_id == issued_claims.token_id
        assert decoded.issuer == "finquest"
        assert decoded.audience == "finquest-api"

    def test_admin_token_has_no_learner_id(self) -> None:
        service = _service()
        token, _ = service.issue_access_token(account_id=uuid4(), learner_id=None, role=AccountRole.ADMIN)
        decoded = service.decode_access_token(token)
        assert decoded.learner_id is None
        assert decoded.role == AccountRole.ADMIN

    def test_rejects_token_signed_with_a_different_secret(self) -> None:
        service_a = _service(secret="a" * 40)
        service_b = _service(secret="b" * 40)
        token, _ = service_a.issue_access_token(account_id=uuid4(), learner_id=None, role=AccountRole.LEARNER)
        with pytest.raises(InvalidAccessTokenError):
            service_b.decode_access_token(token)

    def test_rejects_expired_token(self) -> None:
        service = _service(access_token_minutes=0)
        token, _ = service.issue_access_token(account_id=uuid4(), learner_id=None, role=AccountRole.LEARNER)
        time.sleep(1.2)
        with pytest.raises(InvalidAccessTokenError):
            service.decode_access_token(token)

    def test_rejects_garbage_token(self) -> None:
        service = _service()
        with pytest.raises(InvalidAccessTokenError):
            service.decode_access_token("not-a-jwt-at-all")

    def test_rejects_token_with_wrong_audience(self) -> None:
        service = _service()
        other_audience_service = _service(audience="some-other-api")
        token, _ = other_audience_service.issue_access_token(
            account_id=uuid4(), learner_id=None, role=AccountRole.LEARNER
        )
        with pytest.raises(InvalidAccessTokenError):
            service.decode_access_token(token)

    def test_rejects_token_missing_a_required_claim(self) -> None:
        service = _service()
        payload = {
            "sub": str(uuid4()), "role": AccountRole.LEARNER.value,
            "iat": int(time.time()), "exp": int(time.time()) + 900,
            # "jti" deliberately omitted
            "iss": "finquest", "aud": "finquest-api",
        }
        token = jwt.encode(payload, _STRONG_SECRET, algorithm="HS256")
        with pytest.raises(InvalidAccessTokenError):
            service.decode_access_token(token)

    def test_each_issued_token_has_a_unique_token_id(self) -> None:
        service = _service()
        account_id = uuid4()
        _, claims_a = service.issue_access_token(account_id=account_id, learner_id=None, role=AccountRole.LEARNER)
        _, claims_b = service.issue_access_token(account_id=account_id, learner_id=None, role=AccountRole.LEARNER)
        assert claims_a.token_id != claims_b.token_id
