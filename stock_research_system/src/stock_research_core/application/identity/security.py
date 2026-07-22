"""Deterministic password policy validation.

Pure logic, no I/O, no hashing - `infrastructure.identity
.argon2_password_hasher` handles hashing itself. Never includes the
supplied password in any raised exception message.
"""

from __future__ import annotations

import re

from stock_research_core.application.exceptions import InvalidPasswordError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
_REQUIRED_CHARACTER_CLASSES = 3

# Deliberately small and explicit per spec ss9 - not an exhaustive
# breached-password database, which is out of scope for this phase.
_COMMON_PASSWORDS = frozenset(
    {
        "password", "password123", "1234567890", "qwerty12345", "letmein12345",
        "welcome12345", "iloveyou123", "admin1234567", "changeme12345",
    }
)

_LOWERCASE_PATTERN = re.compile(r"[a-z]")
_UPPERCASE_PATTERN = re.compile(r"[A-Z]")
_DIGIT_PATTERN = re.compile(r"[0-9]")
_SYMBOL_PATTERN = re.compile(r"[^a-zA-Z0-9]")


def validate_password_policy(password: str, *, normalized_email: str) -> None:
    """Raise `InvalidPasswordError` if `password` fails the FinQuest password policy."""
    if not password.strip():
        raise InvalidPasswordError("Password must not be blank.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidPasswordError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvalidPasswordError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters long.")

    classes_present = sum(
        1
        for pattern in (_LOWERCASE_PATTERN, _UPPERCASE_PATTERN, _DIGIT_PATTERN, _SYMBOL_PATTERN)
        if pattern.search(password)
    )
    if classes_present < _REQUIRED_CHARACTER_CLASSES:
        raise InvalidPasswordError(
            "Password must contain at least three of: a lowercase letter, an uppercase letter, "
            "a number, and a symbol."
        )

    lowered = password.strip().lower()
    normalized = normalized_email.strip().lower()
    if normalized and lowered == normalized:
        raise InvalidPasswordError("Password must not be the same as your email address.")
    if normalized and normalized in lowered:
        raise InvalidPasswordError("Password must not contain your email address.")
    if lowered in _COMMON_PASSWORDS:
        raise InvalidPasswordError("This password is too common. Choose a stronger password.")
