"""Enumerations for the FinQuest identity/authentication domain.

This module has no knowledge of any infrastructure (databases, queues,
HTTP frameworks, JWT/password libraries, etc.).
"""

from enum import StrEnum


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"
    PENDING = "PENDING"


class AccountRole(StrEnum):
    LEARNER = "LEARNER"
    CONTENT_EDITOR = "CONTENT_EDITOR"
    ADMIN = "ADMIN"


class AuthenticationEventType(StrEnum):
    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    TOKEN_REFRESHED = "TOKEN_REFRESHED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    LOGOUT_COMPLETED = "LOGOUT_COMPLETED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"


class AuthenticationResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"


class RefreshTokenStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ROTATED = "ROTATED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
