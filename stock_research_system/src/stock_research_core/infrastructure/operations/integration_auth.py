"""n8n / integration-client API-key generation, hashing, and constant-time
verification.

The raw key is generated once (by the admin CLI), returned to the
operator, and never stored or logged again - only its SHA-256 hash is
persisted (`IntegrationClient.api_key_hash`). SHA-256 (not Argon2/bcrypt)
is deliberate: the input is a high-entropy, machine-generated random
token, not a low-entropy human password, so a slow password-hashing KDF
buys nothing and only adds cost to every authenticated request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_RAW_KEY_BYTES = 32  # 256 bits of randomness, per spec ss16
_KEY_ID_BYTES = 8


def generate_key_id() -> str:
    return secrets.token_hex(_KEY_ID_BYTES)


def generate_raw_api_key() -> str:
    return secrets.token_urlsafe(_RAW_KEY_BYTES)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, *, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(raw_key), expected_hash)
