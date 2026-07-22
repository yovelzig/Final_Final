"""Unit tests for `application.identity.security.validate_password_policy`.

Pure logic - no hashing, no I/O.
"""

from __future__ import annotations

import pytest

from stock_research_core.application.exceptions import InvalidPasswordError
from stock_research_core.application.identity.security import validate_password_policy

EMAIL = "learner@example.com"


def test_accepts_a_strong_password() -> None:
    validate_password_policy("Str0ng!Passw0rd", normalized_email=EMAIL)


def test_rejects_blank_password() -> None:
    with pytest.raises(InvalidPasswordError):
        validate_password_policy("   ", normalized_email=EMAIL)


def test_rejects_too_short_password() -> None:
    with pytest.raises(InvalidPasswordError):
        validate_password_policy("Ab1!5", normalized_email=EMAIL)


def test_rejects_too_long_password() -> None:
    with pytest.raises(InvalidPasswordError):
        validate_password_policy("Ab1!" * 40, normalized_email=EMAIL)


def test_rejects_password_with_fewer_than_three_character_classes() -> None:
    with pytest.raises(InvalidPasswordError):
        validate_password_policy("alllowercaseletters", normalized_email=EMAIL)
    with pytest.raises(InvalidPasswordError):
        validate_password_policy("alllower1234567890", normalized_email=EMAIL)


def test_accepts_password_with_exactly_three_character_classes() -> None:
    validate_password_policy("LowercaseUPPER1234", normalized_email=EMAIL)


def test_rejects_password_equal_to_email() -> None:
    with pytest.raises(InvalidPasswordError):
        validate_password_policy(EMAIL, normalized_email=EMAIL)


def test_rejects_password_containing_email() -> None:
    with pytest.raises(InvalidPasswordError):
        validate_password_policy(f"{EMAIL}Extra1!", normalized_email=EMAIL)


def test_rejects_common_passwords() -> None:
    with pytest.raises(InvalidPasswordError):
        validate_password_policy("Password123", normalized_email=EMAIL)


def test_never_includes_the_password_in_the_error_message() -> None:
    secret = "TopSecretPassw0rd!"
    with pytest.raises(InvalidPasswordError) as exc_info:
        validate_password_policy(secret, normalized_email=secret.lower())
    assert secret not in str(exc_info.value)
