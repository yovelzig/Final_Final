"""Production `ObjectStoragePort` implementation backed by S3.

Credentials always come from boto3's default credential chain
(environment, shared config, or the EC2 Instance Profile in
production) - no static AWS access key is ever passed to boto3. Every
synchronous boto3 call, including `StreamingBody.read()`, runs off the
event loop via `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from stock_research_core.application.exceptions import (
    ObjectNotFoundError,
    ObjectStorageAccessDeniedError,
    ObjectStorageError,
)
from stock_research_core.application.object_storage.keys import validate_object_key
from stock_research_core.application.object_storage.models import ObjectReference, StoredObject
from stock_research_core.application.object_storage.ports import ObjectStoragePort
from stock_research_core.infrastructure.object_storage.config import ObjectStorageSettings

_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 30
_MAX_RETRY_ATTEMPTS = 3

_NOT_FOUND_ERROR_CODES = frozenset({"NoSuchKey", "NotFound", "404"})
_ACCESS_DENIED_ERROR_CODES = frozenset({"AccessDenied", "403"})

_METADATA_SHA256_KEY = "finquest-sha256"


def _build_client(settings: ObjectStorageSettings) -> Any:
    s3_config = {"addressing_style": "path"} if settings.s3_force_path_style else None
    boto_config = BotoConfig(
        connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        read_timeout=_READ_TIMEOUT_SECONDS,
        retries={"mode": "standard", "max_attempts": _MAX_RETRY_ATTEMPTS},
        s3=s3_config,
    )
    return boto3.client("s3", region_name=settings.aws_region, config=boto_config)


def _strip_etag_quotes(etag: str | None) -> str | None:
    return etag.strip('"') if etag is not None else None


def _map_client_error(exc: ClientError, *, bucket: str, key: str) -> ObjectStorageError:
    error = exc.response.get("Error", {})
    code = error.get("Code", "")
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")

    if code in _NOT_FOUND_ERROR_CODES or status == 404:
        return ObjectNotFoundError(f"no object at s3://{bucket}/{key} (code={code or status})")
    if code in _ACCESS_DENIED_ERROR_CODES or status == 403:
        return ObjectStorageAccessDeniedError(
            f"access denied for s3://{bucket}/{key} (code={code or status})"
        )
    return ObjectStorageError(f"S3 request failed for s3://{bucket}/{key} (code={code or status})")


def _map_boto_core_error(exc: BotoCoreError, *, bucket: str, key: str) -> ObjectStorageError:
    return ObjectStorageError(f"S3 request failed for s3://{bucket}/{key} ({type(exc).__name__})")


class S3ObjectStorageAdapter(ObjectStoragePort):
    """`ObjectStoragePort` implementation backed by a real (or injected) S3 client."""

    def __init__(self, settings: ObjectStorageSettings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else _build_client(settings)

    def _validate_key(self, key: str) -> str:
        return validate_object_key(key, allowed_prefixes=self._settings.allowed_key_prefixes)

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> ObjectReference:
        validated_key = self._validate_key(key)
        sha256_hex = hashlib.sha256(body).hexdigest()

        try:
            response = await asyncio.to_thread(
                self._put_object_sync, validated_key, body, content_type, sha256_hex
            )
        except ClientError as exc:
            raise _map_client_error(
                exc, bucket=self._settings.s3_bucket_name, key=validated_key
            ) from exc
        except BotoCoreError as exc:
            raise _map_boto_core_error(
                exc, bucket=self._settings.s3_bucket_name, key=validated_key
            ) from exc

        return ObjectReference(
            bucket=self._settings.s3_bucket_name,
            key=validated_key,
            content_type=content_type,
            byte_length=len(body),
            sha256=sha256_hex,
            etag=_strip_etag_quotes(response.get("ETag")),
            version_id=response.get("VersionId"),
            last_modified=None,
        )

    def _put_object_sync(
        self, key: str, body: bytes, content_type: str, sha256_hex: str
    ) -> dict[str, Any]:
        return self._client.put_object(
            Bucket=self._settings.s3_bucket_name,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata={_METADATA_SHA256_KEY: sha256_hex},
        )

    async def head_object(
        self, *, key: str, version_id: str | None = None
    ) -> ObjectReference:
        validated_key = self._validate_key(key)

        try:
            response = await asyncio.to_thread(self._head_object_sync, validated_key, version_id)
        except ClientError as exc:
            raise _map_client_error(
                exc, bucket=self._settings.s3_bucket_name, key=validated_key
            ) from exc
        except BotoCoreError as exc:
            raise _map_boto_core_error(
                exc, bucket=self._settings.s3_bucket_name, key=validated_key
            ) from exc

        metadata = response.get("Metadata") or {}
        return ObjectReference(
            bucket=self._settings.s3_bucket_name,
            key=validated_key,
            content_type=response.get("ContentType") or "application/octet-stream",
            byte_length=response.get("ContentLength", 0),
            sha256=metadata.get(_METADATA_SHA256_KEY),
            etag=_strip_etag_quotes(response.get("ETag")),
            version_id=response.get("VersionId"),
            last_modified=response.get("LastModified"),
        )

    def _head_object_sync(self, key: str, version_id: str | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"Bucket": self._settings.s3_bucket_name, "Key": key}
        if version_id is not None:
            kwargs["VersionId"] = version_id
        return self._client.head_object(**kwargs)

    async def get_object(self, *, key: str, version_id: str | None = None) -> StoredObject:
        validated_key = self._validate_key(key)

        try:
            body, metadata = await asyncio.to_thread(
                self._get_object_sync, validated_key, version_id
            )
        except ClientError as exc:
            raise _map_client_error(
                exc, bucket=self._settings.s3_bucket_name, key=validated_key
            ) from exc
        except BotoCoreError as exc:
            raise _map_boto_core_error(
                exc, bucket=self._settings.s3_bucket_name, key=validated_key
            ) from exc

        expected_sha256 = metadata["sha256"]
        if expected_sha256 is not None:
            actual_sha256 = hashlib.sha256(body).hexdigest()
            if actual_sha256 != expected_sha256:
                raise ObjectStorageError(
                    f"downloaded content for s3://{self._settings.s3_bucket_name}/{validated_key} "
                    "does not match its recorded finquest-sha256 metadata"
                )
        else:
            actual_sha256 = None

        reference = ObjectReference(
            bucket=self._settings.s3_bucket_name,
            key=validated_key,
            content_type=metadata["content_type"],
            byte_length=len(body),
            sha256=actual_sha256,
            etag=metadata["etag"],
            version_id=metadata["version_id"],
            last_modified=metadata["last_modified"],
        )
        return StoredObject(body=body, reference=reference)

    def _get_object_sync(
        self, key: str, version_id: str | None
    ) -> tuple[bytes, dict[str, Any]]:
        kwargs: dict[str, Any] = {"Bucket": self._settings.s3_bucket_name, "Key": key}
        if version_id is not None:
            kwargs["VersionId"] = version_id

        response = self._client.get_object(**kwargs)
        body = response["Body"].read()
        response_metadata = response.get("Metadata") or {}

        metadata = {
            "content_type": response.get("ContentType") or "application/octet-stream",
            "sha256": response_metadata.get(_METADATA_SHA256_KEY),
            "etag": _strip_etag_quotes(response.get("ETag")),
            "version_id": response.get("VersionId"),
            "last_modified": response.get("LastModified"),
        }
        return body, metadata
