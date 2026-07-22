"""Shared, dependency-free helpers for detecting sensitive content in
job parameters, result summaries, error fields, and log records.

Used by both the domain layer (`domain.operations.models` validators,
which must stay infrastructure-free) and the infrastructure logging
redaction filter (`infrastructure.operations.structured_logging`), so
the definition of "sensitive" is defined exactly once.
"""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "jwt",
    "api_key",
    "apikey",
    "authorization",
    "refresh_token",
    "access_token",
    "database_url",
    "db_url",
    "connection_string",
    "private_key",
)

_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Looks like a `header.payload.signature` compact JWT.
_JWT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$")

# `scheme://user:password@host` - a credential embedded in a connection URL.
_CREDENTIAL_URL_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")


def key_is_sensitive(key: str) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def find_sensitive_keys(data: Any, *, _path: str = "") -> list[str]:
    """Recursively collect dotted paths of any dict key that looks sensitive."""
    found: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{_path}.{key}" if _path else str(key)
            if key_is_sensitive(str(key)):
                found.append(path)
            found.extend(find_sensitive_keys(value, _path=path))
    elif isinstance(data, list):
        for index, item in enumerate(data):
            found.extend(find_sensitive_keys(item, _path=f"{_path}[{index}]"))
    return found


def contains_traceback(value: Any) -> bool:
    """True if a raw Python traceback appears anywhere in `value`."""
    if isinstance(value, str):
        return _TRACEBACK_MARKER in value
    if isinstance(value, dict):
        return any(contains_traceback(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_traceback(item) for item in value)
    return False


def contains_credential_leak(text: str) -> bool:
    """True if `text` looks like it embeds a JWT, a credential-bearing URL,
    or a raw `Authorization: Bearer ...` header - narrow, pattern-based
    checks chosen so ordinary English sentences that merely mention the
    word "token" are never flagged."""
    if _CREDENTIAL_URL_PATTERN.search(text):
        return True
    if "authorization: bearer" in text.lower():
        return True
    for word in text.split():
        if _JWT_PATTERN.match(word.strip(".,;:'\"()[]{}")):
            return True
    return False


def redact(value: Any) -> Any:
    """Recursively redact sensitive dict keys and credential-shaped strings.

    Returns a new structure; never mutates `value` in place. Intended for
    logging pipelines, not for domain validation (which should reject
    sensitive input outright rather than silently redact it).
    """
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key_is_sensitive(str(key)):
                result[key] = "***REDACTED***"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if contains_traceback(value) or contains_credential_leak(value):
            return "***REDACTED***"
        return value
    return value
