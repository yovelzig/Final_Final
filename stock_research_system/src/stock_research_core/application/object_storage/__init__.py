"""Object-storage application contract: models, port, and key rules."""

from stock_research_core.application.object_storage.keys import (
    DEFAULT_ALLOWED_KEY_PREFIXES,
    build_seed_knowledge_key,
    validate_object_key,
)
from stock_research_core.application.object_storage.models import ObjectReference, StoredObject
from stock_research_core.application.object_storage.ports import ObjectStoragePort

__all__ = [
    "DEFAULT_ALLOWED_KEY_PREFIXES",
    "ObjectReference",
    "ObjectStoragePort",
    "StoredObject",
    "build_seed_knowledge_key",
    "validate_object_key",
]
