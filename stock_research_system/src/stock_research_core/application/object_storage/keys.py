"""Object-storage key contract.

Defines the allowed key prefixes for the shared object-storage backend
and reusable path-safety validation, independent of any adapter.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from stock_research_core.application.exceptions import ObjectStoragePrefixNotAllowedError

DEFAULT_ALLOWED_KEY_PREFIXES: tuple[str, ...] = (
    "knowledge/",
    "knowledge-extracted/",
    "research-artifacts/",
)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:")


def _validate_path_safety(value: str, *, label: str) -> None:
    """Raise `ValueError` if `value` is not a safe, relative POSIX-style path."""
    if not value:
        raise ValueError(f"{label} must be non-empty")
    if "\\" in value:
        raise ValueError(f"{label} must not contain backslashes")
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{label} must not contain control characters")
    if value.startswith("/") or _DRIVE_LETTER_RE.match(value):
        raise ValueError(f"{label} must be a relative path")

    for segment in value.split("/"):
        if segment in ("", ".", ".."):
            raise ValueError(
                f"{label} must not contain empty, '.', or '..' path segments"
            )


def validate_object_key(
    key: str,
    *,
    allowed_prefixes: Sequence[str] = DEFAULT_ALLOWED_KEY_PREFIXES,
) -> str:
    """Validate `key` as a safe, relative POSIX-style key inside an allowed prefix.

    Returns `key` unchanged on success so it can be used inline.
    """
    _validate_path_safety(key, label="key")

    if not any(key.startswith(prefix) for prefix in allowed_prefixes):
        raise ObjectStoragePrefixNotAllowedError(
            f"key {key!r} is not inside any allowed prefix: {list(allowed_prefixes)!r}"
        )

    return key


def build_seed_knowledge_key(*, knowledge_prefix: str, manifest_filename: str) -> str:
    """Build the key for a seed-knowledge manifest: `knowledge/seed/{manifest_filename}`."""
    _validate_path_safety(manifest_filename, label="manifest_filename")

    key = f"{knowledge_prefix.rstrip('/')}/seed/{manifest_filename}"
    return validate_object_key(key)
