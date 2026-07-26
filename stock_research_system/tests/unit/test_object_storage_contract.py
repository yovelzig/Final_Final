"""Unit tests for the shared object-storage application contract.

Pure dataclass/Protocol/validation checks - no boto3, no infrastructure,
no database.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stock_research_core.application.exceptions import ObjectStoragePrefixNotAllowedError
from stock_research_core.application.object_storage.keys import (
    DEFAULT_ALLOWED_KEY_PREFIXES,
    build_seed_knowledge_key,
    validate_object_key,
)
from stock_research_core.application.object_storage.models import ObjectReference, StoredObject
from stock_research_core.application.object_storage.ports import ObjectStoragePort

_SHA256 = "a" * 64
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _reference(**overrides: object) -> ObjectReference:
    defaults: dict[str, object] = dict(
        bucket="finquest-knowledge",
        key="knowledge/seed/manifest.json",
        content_type="application/json",
        byte_length=4,
        sha256=_SHA256,
    )
    defaults.update(overrides)
    return ObjectReference(**defaults)


# -- ObjectReference -----------------------------------------------------------------------------


def test_object_reference_accepts_valid_values() -> None:
    ref = _reference(etag='"abc123"', version_id="v1", last_modified=NOW)
    assert ref.bucket == "finquest-knowledge"
    assert ref.sha256 == _SHA256
    assert ref.etag == '"abc123"'
    assert ref.version_id == "v1"
    assert ref.last_modified == NOW


def test_object_reference_allows_none_sha256() -> None:
    ref = _reference(sha256=None)
    assert ref.sha256 is None


def test_object_reference_is_frozen() -> None:
    ref = _reference()
    with pytest.raises(AttributeError):
        ref.bucket = "other"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["bucket", "key", "content_type"])
def test_object_reference_rejects_empty_strings(field: str) -> None:
    with pytest.raises(ValueError):
        _reference(**{field: ""})


def test_object_reference_rejects_negative_byte_length() -> None:
    with pytest.raises(ValueError):
        _reference(byte_length=-1)


def test_object_reference_accepts_zero_byte_length() -> None:
    ref = _reference(byte_length=0)
    assert ref.byte_length == 0


@pytest.mark.parametrize(
    "bad_sha256",
    [
        "short",
        "g" * 64,  # not hex
        "A" * 64,  # uppercase not allowed
        "a" * 63,
        "a" * 65,
    ],
)
def test_object_reference_rejects_malformed_sha256(bad_sha256: str) -> None:
    with pytest.raises(ValueError):
        _reference(sha256=bad_sha256)


# -- StoredObject --------------------------------------------------------------------------------


def test_stored_object_accepts_matching_body_length() -> None:
    body = b"abcd"
    obj = StoredObject(body=body, reference=_reference(byte_length=len(body)))
    assert obj.body == body


def test_stored_object_rejects_mismatched_body_length() -> None:
    with pytest.raises(ValueError):
        StoredObject(body=b"abc", reference=_reference(byte_length=4))


def test_stored_object_is_frozen() -> None:
    obj = StoredObject(body=b"abcd", reference=_reference(byte_length=4))
    with pytest.raises(AttributeError):
        obj.body = b"xxxx"  # type: ignore[misc]


# -- ObjectStoragePort -----------------------------------------------------------------------------


class _FakeObjectStorage:
    """Minimal structural implementation used to prove the port's shape."""

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> ObjectReference:
        return ObjectReference(
            bucket="fake",
            key=key,
            content_type=content_type,
            byte_length=len(body),
            sha256=None,
        )

    async def get_object(self, *, key: str, version_id: str | None = None) -> StoredObject:
        body = b"data"
        return StoredObject(
            body=body,
            reference=ObjectReference(
                bucket="fake",
                key=key,
                content_type="application/octet-stream",
                byte_length=len(body),
                sha256=None,
                version_id=version_id,
            ),
        )

    async def head_object(self, *, key: str, version_id: str | None = None) -> ObjectReference:
        return ObjectReference(
            bucket="fake",
            key=key,
            content_type="application/octet-stream",
            byte_length=0,
            sha256=None,
            version_id=version_id,
        )


async def test_fake_object_storage_satisfies_port() -> None:
    storage: ObjectStoragePort = _FakeObjectStorage()

    put_ref = await storage.put_object(key="knowledge/foo.txt", body=b"hi", content_type="text/plain")
    assert put_ref.key == "knowledge/foo.txt"

    fetched = await storage.get_object(key="knowledge/foo.txt")
    assert fetched.reference.key == "knowledge/foo.txt"

    head_ref = await storage.head_object(key="knowledge/foo.txt", version_id="v1")
    assert head_ref.version_id == "v1"


def test_port_does_not_declare_disallowed_methods() -> None:
    for forbidden in ("delete_object", "list_objects", "generate_presigned_url"):
        assert not hasattr(ObjectStoragePort, forbidden)


# -- keys: validate_object_key ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "knowledge/seed/manifest.json",
        "knowledge-extracted/2026/01/doc.txt",
        "research-artifacts/report.pdf",
    ],
)
def test_validate_object_key_accepts_keys_in_allowed_prefixes(key: str) -> None:
    assert validate_object_key(key) == key


def test_validate_object_key_rejects_prefix_outside_allow_list() -> None:
    with pytest.raises(ObjectStoragePrefixNotAllowedError):
        validate_object_key("other-bucket-area/file.txt")


def test_validate_object_key_respects_custom_allowed_prefixes() -> None:
    key = "custom-prefix/file.txt"
    assert validate_object_key(key, allowed_prefixes=("custom-prefix/",)) == key
    with pytest.raises(ObjectStoragePrefixNotAllowedError):
        validate_object_key(key, allowed_prefixes=DEFAULT_ALLOWED_KEY_PREFIXES)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "knowledge\\seed\\manifest.json",
        "/knowledge/seed/manifest.json",
        "C:/knowledge/seed/manifest.json",
        "knowledge//seed/manifest.json",
        "knowledge/./manifest.json",
        "knowledge/../secrets/manifest.json",
        "knowledge/seed/manifest.json\x00",
        "knowledge/seed/manifest\x1f.json",
    ],
)
def test_validate_object_key_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(ValueError):
        validate_object_key(key)


# -- keys: build_seed_knowledge_key -----------------------------------------------------------------


def test_build_seed_knowledge_key_maps_to_expected_layout() -> None:
    key = build_seed_knowledge_key(knowledge_prefix="knowledge/", manifest_filename="manifest.json")
    assert key == "knowledge/seed/manifest.json"


def test_build_seed_knowledge_key_normalizes_trailing_slash_on_prefix() -> None:
    key = build_seed_knowledge_key(knowledge_prefix="knowledge", manifest_filename="manifest.json")
    assert key == "knowledge/seed/manifest.json"


@pytest.mark.parametrize(
    "manifest_filename",
    [
        "",
        "../manifest.json",
        "sub/../manifest.json",
        "sub\\manifest.json",
        "manifest.json\x00",
    ],
)
def test_build_seed_knowledge_key_rejects_unsafe_manifest_filename(manifest_filename: str) -> None:
    with pytest.raises(ValueError):
        build_seed_knowledge_key(knowledge_prefix="knowledge/", manifest_filename=manifest_filename)
