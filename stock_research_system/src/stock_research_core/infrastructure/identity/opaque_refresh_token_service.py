"""Opaque, cryptographically random refresh tokens, satisfying `RefreshTokenServicePort`.

Version: `opaque-refresh-v1`. Only the SHA-256 hash of a refresh token
is ever persisted (`AccountRefreshToken.token_hash`) - the raw token
exists only transiently, in the `IssuedTokenPair` returned to the
caller at issuance/rotation time.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

_TOKEN_BYTES = 32  # 256 bits of randomness, per spec ss11


class OpaqueRefreshTokenService:
    """Generates, hashes, and verifies opaque refresh tokens, satisfying `RefreshTokenServicePort`."""

    version = "opaque-refresh-v1"

    def __init__(self, *, refresh_token_days: int = 30) -> None:
        self._refresh_token_days = refresh_token_days

    def generate_token(self) -> str:
        return secrets.token_urlsafe(_TOKEN_BYTES)

    def hash_token(self, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def verify_token(self, raw_token: str, token_hash: str) -> bool:
        return hmac.compare_digest(self.hash_token(raw_token), token_hash)

    def calculate_expiration(self, *, issued_at: datetime) -> datetime:
        return issued_at + timedelta(days=self._refresh_token_days)
