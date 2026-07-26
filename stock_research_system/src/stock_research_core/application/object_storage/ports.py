"""Application-level object-storage port.

A pure `Protocol` describing what the shared object-storage backend
does, not how. No boto3 (or any other infrastructure library) is
imported here; concrete implementations live under
`stock_research_core.infrastructure`.
"""

from __future__ import annotations

from typing import Protocol

from stock_research_core.application.object_storage.models import ObjectReference, StoredObject


class ObjectStoragePort(Protocol):
    """Puts, fetches, and inspects objects in the shared object-storage backend."""

    async def put_object(
        self, *, key: str, body: bytes, content_type: str
    ) -> ObjectReference: ...

    async def get_object(
        self, *, key: str, version_id: str | None = None
    ) -> StoredObject: ...

    async def head_object(
        self, *, key: str, version_id: str | None = None
    ) -> ObjectReference: ...
