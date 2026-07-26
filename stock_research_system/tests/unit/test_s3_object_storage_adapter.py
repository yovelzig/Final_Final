"""Unit tests for `S3ObjectStorageAdapter` (Phase F1b).

Uses only injected fake/stub clients - no moto, no LocalStack, no real
AWS calls. `boto3.client` itself is monkeypatched where client
*construction* is under test.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from typing import Any

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from stock_research_core.application.exceptions import (
    ObjectNotFoundError,
    ObjectStorageAccessDeniedError,
    ObjectStorageError,
    ObjectStoragePrefixNotAllowedError,
)
from stock_research_core.infrastructure.object_storage import s3_adapter as s3_adapter_module
from stock_research_core.infrastructure.object_storage.config import ObjectStorageSettings
from stock_research_core.infrastructure.object_storage.s3_adapter import S3ObjectStorageAdapter

_ENV_VARS = (
    "OBJECT_STORAGE_PROVIDER",
    "AWS_REGION",
    "S3_BUCKET_NAME",
    "S3_KNOWLEDGE_PREFIX",
    "S3_EXTRACTED_TEXT_PREFIX",
    "S3_RESEARCH_ARTIFACT_PREFIX",
    "S3_FORCE_PATH_STYLE",
)


@pytest.fixture(autouse=True)
def _clean_object_storage_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides: object) -> ObjectStorageSettings:
    return ObjectStorageSettings(**overrides)


def _client_error(code: str, *, status: int, operation: str = "GetObject") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "boom"}, "ResponseMetadata": {"HTTPStatusCode": status}},
        operation,
    )


class _FakeStreamingBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    """Minimal synchronous stand-in for a boto3 S3 client."""

    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.head_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.put_response: Any = {"ETag": '"put-etag"', "VersionId": "put-v1"}
        self.head_response: Any = {}
        self.get_response: Any = {}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        if isinstance(self.put_response, BaseException):
            raise self.put_response
        return self.put_response

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.head_calls.append(kwargs)
        if isinstance(self.head_response, BaseException):
            raise self.head_response
        return self.head_response

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs)
        if isinstance(self.get_response, BaseException):
            raise self.get_response
        return self.get_response


# -- construction: default credential chain, no static credentials -------------------------------


def test_constructs_client_via_default_credential_chain_with_no_static_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_boto3_client(service_name: str, **kwargs: Any) -> object:
        captured["service_name"] = service_name
        captured["kwargs"] = kwargs
        return _FakeS3Client()

    monkeypatch.setattr(s3_adapter_module.boto3, "client", _fake_boto3_client)

    S3ObjectStorageAdapter(_settings())

    assert captured["service_name"] == "s3"
    kwargs = captured["kwargs"]
    assert kwargs["region_name"] == "us-east-2"
    assert "aws_access_key_id" not in kwargs
    assert "aws_secret_access_key" not in kwargs
    assert "aws_session_token" not in kwargs
    assert "config" in kwargs


def test_default_client_uses_bounded_timeouts_and_standard_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_boto3_client(service_name: str, **kwargs: Any) -> object:
        captured["config"] = kwargs["config"]
        return _FakeS3Client()

    monkeypatch.setattr(s3_adapter_module.boto3, "client", _fake_boto3_client)

    S3ObjectStorageAdapter(_settings())

    config = captured["config"]
    assert config.connect_timeout is not None
    assert config.read_timeout is not None
    assert config.retries["mode"] == "standard"
    assert config.retries["max_attempts"] >= 1


def test_force_path_style_configures_addressing_style(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_boto3_client(service_name: str, **kwargs: Any) -> object:
        captured["config"] = kwargs["config"]
        return _FakeS3Client()

    monkeypatch.setattr(s3_adapter_module.boto3, "client", _fake_boto3_client)

    S3ObjectStorageAdapter(_settings(s3_force_path_style=True))

    assert captured["config"].s3["addressing_style"] == "path"


def test_injected_client_bypasses_client_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args: Any, **kwargs: Any) -> object:
        raise AssertionError("boto3.client must not be called when a client is injected")

    monkeypatch.setattr(s3_adapter_module.boto3, "client", _fail)

    fake_client = _FakeS3Client()
    adapter = S3ObjectStorageAdapter(_settings(), client=fake_client)
    assert adapter._client is fake_client


# -- key-prefix validation, before any client call ------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "knowledge/doc.md",
        "knowledge-extracted/doc.txt",
        "research-artifacts/report.pdf",
    ],
)
async def test_put_object_accepts_every_allowed_prefix(key: str) -> None:
    client = _FakeS3Client()
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    ref = await adapter.put_object(key=key, body=b"data", content_type="text/plain")

    assert ref.key == key
    assert len(client.put_calls) == 1


async def test_put_object_rejects_disallowed_prefix_before_calling_client() -> None:
    client = _FakeS3Client()
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    with pytest.raises(ObjectStoragePrefixNotAllowedError):
        await adapter.put_object(key="not-allowed/file.txt", body=b"data", content_type="text/plain")

    assert client.put_calls == []


async def test_head_object_rejects_disallowed_prefix_before_calling_client() -> None:
    client = _FakeS3Client()
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    with pytest.raises(ObjectStoragePrefixNotAllowedError):
        await adapter.head_object(key="other/file.txt")

    assert client.head_calls == []


# -- put_object ------------------------------------------------------------------------------------


async def test_put_object_computes_and_sends_sha256_metadata() -> None:
    client = _FakeS3Client()
    client.put_response = {"ETag": '"abc123"', "VersionId": "v9"}
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    body = b"hello finquest"
    expected_sha256 = hashlib.sha256(body).hexdigest()

    ref = await adapter.put_object(key="knowledge/doc.md", body=body, content_type="text/markdown")

    assert len(client.put_calls) == 1
    call = client.put_calls[0]
    assert call["Bucket"] == adapter._settings.s3_bucket_name
    assert call["Key"] == "knowledge/doc.md"
    assert call["Body"] == body
    assert call["ContentType"] == "text/markdown"
    assert call["Metadata"] == {"finquest-sha256": expected_sha256}

    assert ref.sha256 == expected_sha256
    assert ref.etag == "abc123"
    assert ref.version_id == "v9"
    assert ref.byte_length == len(body)
    assert ref.bucket == adapter._settings.s3_bucket_name


# -- head_object -----------------------------------------------------------------------------------


async def test_head_object_extracts_full_metadata() -> None:
    client = _FakeS3Client()
    last_modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    client.head_response = {
        "ContentType": "application/pdf",
        "ContentLength": 1234,
        "Metadata": {"finquest-sha256": "a" * 64},
        "ETag": '"headetag"',
        "VersionId": "v-head",
        "LastModified": last_modified,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    ref = await adapter.head_object(key="research-artifacts/report.pdf")

    assert ref.bucket == adapter._settings.s3_bucket_name
    assert ref.key == "research-artifacts/report.pdf"
    assert ref.content_type == "application/pdf"
    assert ref.byte_length == 1234
    assert ref.sha256 == "a" * 64
    assert ref.etag == "headetag"
    assert ref.version_id == "v-head"
    assert ref.last_modified == last_modified


async def test_head_object_returns_none_sha256_when_metadata_absent() -> None:
    client = _FakeS3Client()
    client.head_response = {
        "ContentType": "text/plain",
        "ContentLength": 10,
        "Metadata": {},
        "ETag": '"noattr"',
        "VersionId": None,
        "LastModified": None,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    ref = await adapter.head_object(key="knowledge/plain.txt")

    assert ref.sha256 is None


async def test_head_object_forwards_version_id() -> None:
    client = _FakeS3Client()
    client.head_response = {
        "ContentType": "text/plain",
        "ContentLength": 1,
        "Metadata": {},
        "ETag": '"e"',
        "VersionId": "v-3",
        "LastModified": None,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    await adapter.head_object(key="knowledge/versioned.txt", version_id="v-3")

    assert client.head_calls[0]["VersionId"] == "v-3"


# -- get_object ------------------------------------------------------------------------------------


async def test_get_object_forwards_version_id_when_given() -> None:
    body = b"versioned body"
    client = _FakeS3Client()
    client.get_response = {
        "Body": _FakeStreamingBody(body),
        "ContentType": "text/plain",
        "Metadata": {},
        "ETag": '"vetag"',
        "VersionId": "v-42",
        "LastModified": None,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    await adapter.get_object(key="knowledge/versioned.txt", version_id="v-42")

    assert client.get_calls[0]["VersionId"] == "v-42"


async def test_get_object_omits_version_id_when_not_given() -> None:
    body = b"latest body"
    client = _FakeS3Client()
    client.get_response = {
        "Body": _FakeStreamingBody(body),
        "ContentType": "text/plain",
        "Metadata": {},
        "ETag": '"latest"',
        "VersionId": "v-latest",
        "LastModified": None,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    await adapter.get_object(key="knowledge/latest.txt")

    assert "VersionId" not in client.get_calls[0]


async def test_get_object_validates_matching_sha256_and_returns_stored_object() -> None:
    body = b"trusted content"
    expected_sha256 = hashlib.sha256(body).hexdigest()
    client = _FakeS3Client()
    client.get_response = {
        "Body": _FakeStreamingBody(body),
        "ContentType": "text/plain",
        "Metadata": {"finquest-sha256": expected_sha256},
        "ETag": '"trusted"',
        "VersionId": "v-1",
        "LastModified": None,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    stored = await adapter.get_object(key="knowledge/trusted.txt")

    assert stored.body == body
    assert stored.reference.sha256 == expected_sha256
    assert stored.reference.byte_length == len(body)
    assert stored.reference.etag == "trusted"


async def test_get_object_allows_missing_finquest_hash_metadata() -> None:
    body = b"non-finquest object"
    client = _FakeS3Client()
    client.get_response = {
        "Body": _FakeStreamingBody(body),
        "ContentType": "application/octet-stream",
        "Metadata": {},
        "ETag": '"foreign"',
        "VersionId": None,
        "LastModified": None,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    stored = await adapter.get_object(key="knowledge/foreign.bin")

    assert stored.reference.sha256 is None


async def test_get_object_rejects_corrupt_download_hash_mismatch() -> None:
    body = b"tampered content"
    client = _FakeS3Client()
    client.get_response = {
        "Body": _FakeStreamingBody(body),
        "ContentType": "text/plain",
        "Metadata": {"finquest-sha256": "0" * 64},
        "ETag": '"tampered"',
        "VersionId": "v-1",
        "LastModified": None,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    with pytest.raises(ObjectStorageError):
        await adapter.get_object(key="knowledge/tampered.txt")


# -- error mapping -----------------------------------------------------------------------------------


async def test_get_object_maps_no_such_key_to_object_not_found() -> None:
    client = _FakeS3Client()
    client.get_response = _client_error("NoSuchKey", status=404)
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    with pytest.raises(ObjectNotFoundError):
        await adapter.get_object(key="knowledge/missing.txt")


async def test_head_object_maps_access_denied() -> None:
    client = _FakeS3Client()
    client.head_response = _client_error("AccessDenied", status=403, operation="HeadObject")
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    with pytest.raises(ObjectStorageAccessDeniedError):
        await adapter.head_object(key="knowledge/forbidden.txt")


async def test_put_object_maps_generic_client_error_and_sanitizes_message() -> None:
    client = _FakeS3Client()
    client.put_response = ClientError(
        {
            "Error": {"Code": "InternalError", "Message": "boom"},
            "ResponseMetadata": {
                "HTTPStatusCode": 500,
                "HTTPHeaders": {"authorization": "AWS4-HMAC-SHA256 Credential=SECRETKEY"},
            },
        },
        "PutObject",
    )
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    with pytest.raises(ObjectStorageError) as exc_info:
        await adapter.put_object(key="knowledge/x.txt", body=b"x", content_type="text/plain")

    assert not isinstance(exc_info.value, ObjectNotFoundError)
    assert not isinstance(exc_info.value, ObjectStorageAccessDeniedError)
    message = str(exc_info.value)
    assert "SECRETKEY" not in message
    assert "authorization" not in message.lower()


async def test_get_object_maps_boto_core_error() -> None:
    client = _FakeS3Client()
    client.get_response = BotoCoreError()
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    with pytest.raises(ObjectStorageError):
        await adapter.get_object(key="knowledge/whatever.txt")


# -- asyncio event-loop safety -------------------------------------------------------------------------


async def test_put_object_runs_boto3_work_off_the_event_loop_thread() -> None:
    calling_thread = threading.get_ident()

    class _ThreadRecordingClient(_FakeS3Client):
        observed_thread: int | None = None

        def put_object(self, **kwargs: Any) -> dict[str, Any]:
            self.observed_thread = threading.get_ident()
            return super().put_object(**kwargs)

    client = _ThreadRecordingClient()
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    await adapter.put_object(key="knowledge/threaded.txt", body=b"x", content_type="text/plain")

    assert client.observed_thread is not None
    assert client.observed_thread != calling_thread


async def test_get_object_streaming_body_read_runs_off_the_event_loop_thread() -> None:
    calling_thread = threading.get_ident()

    class _ThreadRecordingBody(_FakeStreamingBody):
        observed_thread: int | None = None

        def read(self) -> bytes:
            self.observed_thread = threading.get_ident()
            return super().read()

    body = _ThreadRecordingBody(b"payload")
    client = _FakeS3Client()
    client.get_response = {
        "Body": body,
        "ContentType": "text/plain",
        "Metadata": {},
        "ETag": '"e"',
        "VersionId": None,
        "LastModified": None,
    }
    adapter = S3ObjectStorageAdapter(_settings(), client=client)

    await adapter.get_object(key="knowledge/payload.txt")

    assert body.observed_thread is not None
    assert body.observed_thread != calling_thread
