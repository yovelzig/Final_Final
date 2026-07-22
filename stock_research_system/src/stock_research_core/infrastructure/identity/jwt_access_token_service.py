"""PyJWT-backed short-lived access tokens, satisfying `AccessTokenServicePort`.

Version: `jwt-access-v1`. Access tokens are never persisted anywhere -
`decode_access_token` is the only way to recover their claims, and it
performs full validation (signature, issuer, audience, expiration, and
presence of every required claim) in one call, raising
`InvalidAccessTokenError` on any failure rather than returning a
partially-trusted result.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt

from stock_research_core.application.exceptions import InvalidAccessTokenError
from stock_research_core.application.identity.models import AccessTokenClaims
from stock_research_core.domain.identity.enums import AccountRole

ACCESS_TOKEN_VERSION = "jwt-access-v1"
DEFAULT_ALGORITHM = "HS256"

_MIN_SECRET_LENGTH = 32
_OBVIOUSLY_WEAK_SECRETS = frozenset(
    {"secret", "changeme", "password", "test", "testsecret", "development", "insecure"}
)


def assert_secret_is_strong(secret: str, *, allow_weak_for_tests: bool = False) -> None:
    """Refuse startup with an absent or obviously weak JWT signing secret.

    `allow_weak_for_tests=True` is the one sanctioned escape hatch, used
    only by test fixtures that construct a throwaway service - never by
    application/API startup code.
    """
    if allow_weak_for_tests:
        return
    if not secret or len(secret) < _MIN_SECRET_LENGTH:
        raise InvalidAccessTokenError(
            f"AUTH_JWT_SECRET must be at least {_MIN_SECRET_LENGTH} characters long."
        )
    if secret.strip().lower() in _OBVIOUSLY_WEAK_SECRETS:
        raise InvalidAccessTokenError("AUTH_JWT_SECRET must not be a well-known placeholder value.")


class JwtAccessTokenService:
    """Issues and validates JWT access tokens, satisfying `AccessTokenServicePort`."""

    version = ACCESS_TOKEN_VERSION

    def __init__(
        self,
        *,
        secret: str,
        issuer: str = "finquest",
        audience: str = "finquest-api",
        algorithm: str = DEFAULT_ALGORITHM,
        access_token_minutes: int = 15,
        allow_weak_secret_for_tests: bool = False,
    ) -> None:
        assert_secret_is_strong(secret, allow_weak_for_tests=allow_weak_secret_for_tests)
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._algorithm = algorithm
        self._access_token_minutes = access_token_minutes

    def issue_access_token(
        self, *, account_id: UUID, learner_id: UUID | None, role: AccountRole
    ) -> tuple[str, AccessTokenClaims]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=self._access_token_minutes)
        token_id = uuid4()

        payload = {
            "sub": str(account_id),
            "learner_id": str(learner_id) if learner_id is not None else None,
            "role": role.value,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": str(token_id),
            "iss": self._issuer,
            "aud": self._audience,
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        claims = AccessTokenClaims(
            subject=account_id, learner_id=learner_id, role=role, issued_at=now, expires_at=expires_at,
            token_id=token_id, issuer=self._issuer, audience=self._audience,
        )
        return token, claims

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["sub", "role", "iat", "exp", "jti", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidAccessTokenError("The access token is invalid or expired.") from exc

        try:
            subject = UUID(payload["sub"])
            token_id = UUID(payload["jti"])
            role = AccountRole(payload["role"])
            learner_id = UUID(payload["learner_id"]) if payload.get("learner_id") else None
        except (ValueError, KeyError) as exc:
            raise InvalidAccessTokenError("The access token has malformed claims.") from exc

        return AccessTokenClaims(
            subject=subject,
            learner_id=learner_id,
            role=role,
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            token_id=token_id,
            issuer=payload["iss"],
            audience=payload["aud"],
        )
