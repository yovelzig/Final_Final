"""Application-level object-storage models.

Frozen, slotted dataclasses describing an object stored in the shared
object-storage backend, and what was retrieved for it. No boto3 or
other infrastructure dependency here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ObjectReference:
    """Identifies and describes a single stored object, without its body."""

    bucket: str
    key: str
    content_type: str
    byte_length: int
    sha256: str | None
    etag: str | None = None
    version_id: str | None = None
    last_modified: datetime | None = None

    def __post_init__(self) -> None:
        if not self.bucket:
            raise ValueError("bucket must be non-empty")
        if not self.key:
            raise ValueError("key must be non-empty")
        if not self.content_type:
            raise ValueError("content_type must be non-empty")
        if self.byte_length < 0:
            raise ValueError("byte_length must be >= 0")
        if self.sha256 is not None and not _SHA256_HEX_RE.fullmatch(self.sha256):
            raise ValueError("sha256 must be exactly 64 lowercase hexadecimal characters")


@dataclass(frozen=True, slots=True)
class StoredObject:
    """A retrieved object: its raw body plus the reference describing it."""

    body: bytes
    reference: ObjectReference

    def __post_init__(self) -> None:
        if len(self.body) != self.reference.byte_length:
            raise ValueError("len(body) must equal reference.byte_length")
