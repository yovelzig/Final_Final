"""Manifest-driven seed-knowledge ingestion orchestrator (Phase C3).

Wires `SeedManifest` (seed_manifest.py) to the frozen `ObjectStoragePort`
contract and the existing `KnowledgeIngestionService` - no second RAG
pipeline, no new chunker/embedding/repository logic here. This module
only ever depends on `ObjectStoragePort` (a Protocol); no concrete S3
adapter is imported or constructed anywhere in this file.

Per document, in order: canonicalize and hash the local source file,
compare against the manifest's `content_hash`, `head_object` the
expected S3 key, `put_object` only when missing/changed (retaining the
exact returned `version_id`), `get_object` by that exact `version_id`
and re-verify the hash, strip and validate front matter, write only the
Markdown body to a bounded temporary file, and call
`KnowledgeIngestionService.ingest_local_document(source_key=..., source_title=...)`.
The S3 key and version ID are only ever returned in this module's own
per-document result - they are never written to PostgreSQL.

A dry run performs zero write operations: it may load/validate the
manifest, read and hash local files, parse front matter, build keys, and
call `head_object`, but never `put_object`, `get_object`, temp-file
creation, `ingest_local_document`, or a database commit.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.seed_manifest import (
    APPROVED_SEED_REVIEW_STATUS,
    SeedManifest,
    SeedManifestDocument,
    canonicalize_source_text,
    compute_manifest_file_hash,
    parse_and_validate_front_matter,
    resolve_document_path,
)
from stock_research_core.application.exceptions import (
    ObjectNotFoundError,
    SeedDocumentIntegrityError,
    SeedManifestDocumentNotFoundError,
)
from stock_research_core.application.object_storage.keys import build_seed_knowledge_key
from stock_research_core.application.object_storage.models import ObjectReference
from stock_research_core.application.object_storage.ports import ObjectStoragePort
from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus
from stock_research_core.domain.models import utc_now

# Same limit the existing local-document parser enforces, so a bounded
# temporary ingestion file can never exceed what `parse_local_document`
# would itself accept.
MAX_INGESTIBLE_BODY_BYTES = 20 * 1024 * 1024  # 20 MB

_MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ManifestDocumentResult:
    """The outcome of processing one manifest entry."""

    document_code: str
    object_key: str
    object_version_id: str | None
    upload_performed: bool
    documents_created: int = 0
    documents_skipped_unchanged: int = 0
    documents_archived: int = 0
    succeeded: bool = True
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ManifestSkippedEntry:
    """A manifest entry that was not selected for processing."""

    document_code: str
    review_status: str
    reason: str


@dataclass(frozen=True, slots=True)
class ManifestIngestionSummary:
    """The outcome of one `ManifestIngestionService.ingest()` call."""

    dry_run: bool
    results: tuple[ManifestDocumentResult, ...] = field(default_factory=tuple)
    skipped_entries: tuple[ManifestSkippedEntry, ...] = field(default_factory=tuple)

    @property
    def processed_count(self) -> int:
        return len(self.results)

    @property
    def succeeded_count(self) -> int:
        return sum(1 for result in self.results if result.succeeded)

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.results if not result.succeeded)


class ManifestIngestionService:
    """Orchestrates manifest-driven seed-document ingestion end to end."""

    def __init__(
        self,
        *,
        object_storage: ObjectStoragePort,
        knowledge_ingestion_service: KnowledgeIngestionService,
        seed_documents_root: Path,
        knowledge_prefix: str = "knowledge/",
        clock: Clock = utc_now,
    ) -> None:
        self._object_storage = object_storage
        self._knowledge_ingestion_service = knowledge_ingestion_service
        self._seed_documents_root = seed_documents_root
        self._knowledge_prefix = knowledge_prefix
        self._clock = clock

    async def ingest(
        self,
        *,
        manifest: SeedManifest,
        document_code: str | None = None,
        dry_run: bool = False,
        approval_status: KnowledgeApprovalStatus = KnowledgeApprovalStatus.APPROVED,
        available_at: datetime | None = None,
    ) -> ManifestIngestionSummary:
        selected, skipped = self._select_entries(manifest, document_code)
        effective_available_at = available_at or self._clock()

        results = [
            await self._process_entry(
                entry,
                manifest=manifest,
                dry_run=dry_run,
                approval_status=approval_status,
                available_at=effective_available_at,
            )
            for entry in selected
        ]

        return ManifestIngestionSummary(dry_run=dry_run, results=tuple(results), skipped_entries=tuple(skipped))

    @staticmethod
    def _select_entries(
        manifest: SeedManifest, document_code: str | None
    ) -> tuple[list[SeedManifestDocument], list[ManifestSkippedEntry]]:
        if document_code is not None:
            entry = manifest.get(document_code)
            if entry is None:
                raise SeedManifestDocumentNotFoundError(
                    f"no manifest entry found for document code {document_code!r}"
                )
            if not entry.is_approved_seed:
                return [], [
                    ManifestSkippedEntry(
                        document_code=entry.document_id,
                        review_status=entry.review_status,
                        reason=f"review_status {entry.review_status!r} is not {APPROVED_SEED_REVIEW_STATUS!r}",
                    )
                ]
            return [entry], []

        selected = [document for document in manifest.documents if document.is_approved_seed]
        skipped = [
            ManifestSkippedEntry(
                document_code=document.document_id,
                review_status=document.review_status,
                reason=f"review_status {document.review_status!r} is not {APPROVED_SEED_REVIEW_STATUS!r}",
            )
            for document in manifest.documents
            if not document.is_approved_seed
        ]
        return selected, skipped

    async def _process_entry(
        self,
        entry: SeedManifestDocument,
        *,
        manifest: SeedManifest,
        dry_run: bool,
        approval_status: KnowledgeApprovalStatus,
        available_at: datetime,
    ) -> ManifestDocumentResult:
        object_key = build_seed_knowledge_key(
            knowledge_prefix=self._knowledge_prefix, manifest_filename=entry.filename
        )
        try:
            return await self._process_entry_unsafe(
                entry,
                manifest=manifest,
                dry_run=dry_run,
                approval_status=approval_status,
                available_at=available_at,
                object_key=object_key,
            )
        except Exception as exc:  # noqa: BLE001 - one failed entry must not abort the batch
            return ManifestDocumentResult(
                document_code=entry.document_id,
                object_key=object_key,
                object_version_id=None,
                upload_performed=False,
                succeeded=False,
                failure_reason=str(exc),
            )

    async def _process_entry_unsafe(
        self,
        entry: SeedManifestDocument,
        *,
        manifest: SeedManifest,
        dry_run: bool,
        approval_status: KnowledgeApprovalStatus,
        available_at: datetime,
        object_key: str,
    ) -> ManifestDocumentResult:
        file_path = resolve_document_path(self._seed_documents_root, entry.filename, language=manifest.language)
        canonical_bytes = canonicalize_source_text(file_path.read_bytes())
        manifest_file_hash = compute_manifest_file_hash(canonical_bytes)
        if manifest_file_hash != entry.content_hash:
            raise SeedDocumentIntegrityError(
                f"{entry.document_id}: local file hash {manifest_file_hash} does not match "
                f"manifest content_hash {entry.content_hash}"
            )

        existing_ref: ObjectReference | None
        try:
            existing_ref = await self._object_storage.head_object(key=object_key)
        except ObjectNotFoundError:
            existing_ref = None

        needs_upload = existing_ref is None or existing_ref.sha256 != manifest_file_hash

        if dry_run:
            return ManifestDocumentResult(
                document_code=entry.document_id,
                object_key=object_key,
                object_version_id=None if needs_upload else existing_ref.version_id,
                upload_performed=False,
            )

        if needs_upload:
            put_ref = await self._object_storage.put_object(
                key=object_key, body=canonical_bytes, content_type=_MARKDOWN_CONTENT_TYPE
            )
            version_id = put_ref.version_id
            upload_performed = True
        else:
            version_id = existing_ref.version_id
            upload_performed = False

        downloaded = await self._object_storage.get_object(key=object_key, version_id=version_id)
        downloaded_hash = hashlib.sha256(downloaded.body).hexdigest()
        if downloaded_hash != manifest_file_hash:
            raise SeedDocumentIntegrityError(
                f"{entry.document_id}: downloaded object hash {downloaded_hash} does not match "
                f"expected manifest_file_hash {manifest_file_hash}"
            )

        _parsed_front_matter, body = parse_and_validate_front_matter(
            downloaded.body.decode("utf-8"),
            manifest_document=entry,
            expected_language=manifest.language,
        )

        tmp_path = self._write_bounded_temp_markdown(body, document_id=entry.document_id)
        try:
            ingestion_summary = await self._knowledge_ingestion_service.ingest_local_document(
                file_path=tmp_path,
                source_title=entry.title,
                source_key=entry.document_id,
                approval_status=approval_status,
                skill_ids=[],
                available_at=available_at,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        return ManifestDocumentResult(
            document_code=entry.document_id,
            object_key=object_key,
            object_version_id=version_id,
            upload_performed=upload_performed,
            documents_created=ingestion_summary.documents_created,
            documents_skipped_unchanged=ingestion_summary.documents_skipped_unchanged,
            documents_archived=ingestion_summary.documents_archived,
        )

    @staticmethod
    def _write_bounded_temp_markdown(body: str, *, document_id: str) -> Path:
        body_bytes = body.encode("utf-8")
        if len(body_bytes) > MAX_INGESTIBLE_BODY_BYTES:
            raise SeedDocumentIntegrityError(
                f"{document_id}: document body is {len(body_bytes)} bytes, exceeding the "
                f"{MAX_INGESTIBLE_BODY_BYTES}-byte ingestion limit"
            )

        descriptor, raw_path = tempfile.mkstemp(prefix="finquest-seed-ingest-", suffix=".md")
        tmp_path = Path(raw_path)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body_bytes)
        return tmp_path
