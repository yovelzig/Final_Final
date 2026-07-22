"""Argon2id password hashing, satisfying `PasswordHasherPort`.

All methods here are synchronous by design (matching the Port's plain
`def` signatures) - `IdentityService` (async) is responsible for
running them off the event loop via `asyncio.to_thread`, since Argon2
hashing is deliberately CPU/memory-expensive and would otherwise block
every other concurrent request.
"""

from __future__ import annotations

from pwdlib import PasswordHash


class Argon2PasswordHasher:
    """Argon2id password hasher (via `pwdlib`), satisfying `PasswordHasherPort`."""

    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()

    def hash_password(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        return self._password_hash.verify(password, password_hash)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._password_hash.current_hasher.check_needs_rehash(password_hash)
