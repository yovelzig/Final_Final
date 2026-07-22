"""Unit tests for `Argon2PasswordHasher`."""

from __future__ import annotations

from stock_research_core.infrastructure.identity.argon2_password_hasher import Argon2PasswordHasher


def test_hash_password_never_returns_the_plaintext() -> None:
    hasher = Argon2PasswordHasher()
    password = "Str0ng!Passw0rd"
    hashed = hasher.hash_password(password)
    assert password not in hashed
    assert hashed.startswith("$argon2")


def test_verify_password_accepts_correct_password() -> None:
    hasher = Argon2PasswordHasher()
    password = "Str0ng!Passw0rd"
    hashed = hasher.hash_password(password)
    assert hasher.verify_password(password, hashed) is True


def test_verify_password_rejects_incorrect_password() -> None:
    hasher = Argon2PasswordHasher()
    hashed = hasher.hash_password("Str0ng!Passw0rd")
    assert hasher.verify_password("WrongPassword123!", hashed) is False


def test_hashing_the_same_password_twice_produces_different_hashes() -> None:
    """Argon2 salts each hash independently."""
    hasher = Argon2PasswordHasher()
    password = "Str0ng!Passw0rd"
    assert hasher.hash_password(password) != hasher.hash_password(password)


def test_needs_rehash_is_false_for_a_freshly_created_hash() -> None:
    hasher = Argon2PasswordHasher()
    hashed = hasher.hash_password("Str0ng!Passw0rd")
    assert hasher.needs_rehash(hashed) is False
