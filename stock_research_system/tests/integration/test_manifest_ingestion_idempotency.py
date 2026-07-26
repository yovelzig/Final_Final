"""PostgreSQL integration tests proving manifest-driven seed ingestion is
idempotent end to end: the real `KnowledgeIngestionService` (heading-aware
chunker + deterministic fake embeddings) and real PostgreSQL via
`uow_factory`, wired to `ManifestIngestionService` through a small
in-memory `ObjectStoragePort` fake (test-only, per the C3 spec - no real
S3 call is ever made, no fake adapter lives under `src/`).

Covers: first ingestion creates one document and its chunks, an
identical second ingestion is a no-op, changed content archives the
previous approved version, and stored chunks never contain front-matter
keys.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.manifest_ingestion import ManifestIngestionService
from stock_research_core.application.ai_tutor.seed_manifest import (
    canonicalize_source_text,
    compute_manifest_file_hash,
    load_seed_manifest,
)
from stock_research_core.application.exceptions import ObjectNotFoundError
from stock_research_core.application.object_storage.models import ObjectReference, StoredObject
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# -- in-memory ObjectStoragePort fake (test-only, per C3 spec: not in src/) -------------------------


@dataclass
class _StoredVersion:
    body: bytes
    content_type: str
    sha256: str
    version_id: str


class FakeObjectStorage:
    """Minimal in-memory `ObjectStoragePort` implementation for tests only."""

    def __init__(self) -> None:
        self._versions: dict[str, list[_StoredVersion]] = {}
        self._version_seq = 0
        self.put_calls = 0
        self.get_calls = 0
        self.head_calls = 0

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> ObjectReference:
        self.put_calls += 1
        self._version_seq += 1
        version_id = f"v{self._version_seq}"
        sha256 = hashlib.sha256(body).hexdigest()
        self._versions.setdefault(key, []).append(
            _StoredVersion(body=body, content_type=content_type, sha256=sha256, version_id=version_id)
        )
        return ObjectReference(
            bucket="fake-bucket", key=key, content_type=content_type, byte_length=len(body),
            sha256=sha256, version_id=version_id,
        )

    async def head_object(self, *, key: str, version_id: str | None = None) -> ObjectReference:
        self.head_calls += 1
        record = self._resolve(key, version_id)
        if record is None:
            raise ObjectNotFoundError(f"no object at key {key!r}")
        return ObjectReference(
            bucket="fake-bucket", key=key, content_type=record.content_type, byte_length=len(record.body),
            sha256=record.sha256, version_id=record.version_id,
        )

    async def get_object(self, *, key: str, version_id: str | None = None) -> StoredObject:
        self.get_calls += 1
        record = self._resolve(key, version_id)
        if record is None:
            raise ObjectNotFoundError(f"no object at key {key!r} version {version_id!r}")
        return StoredObject(
            body=record.body,
            reference=ObjectReference(
                bucket="fake-bucket", key=key, content_type=record.content_type, byte_length=len(record.body),
                sha256=record.sha256, version_id=record.version_id,
            ),
        )

    def _resolve(self, key: str, version_id: str | None) -> _StoredVersion | None:
        versions = self._versions.get(key, [])
        if not versions:
            return None
        if version_id is None:
            return versions[-1]
        return next((v for v in versions if v.version_id == version_id), None)


# -- fixtures ---------------------------------------------------------------------------------------


def _front_matter_source(*, document_id: str, title: str, body_paragraph: str = "Body content.") -> str:
    return (
        "---\n"
        f'document_id: "{document_id}"\n'
        f'title: "{title}"\n'
        "version: 1\n"
        'language: "en"\n'
        'review_status: "approved_seed"\n'
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
        "## Section One\n"
        "\n"
        f"{body_paragraph}\n"
    )


def _write_seed_document(seed_root: Path, *, filename: str, source_text: str) -> str:
    path = seed_root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source_text, encoding="utf-8", newline="\n")
    return compute_manifest_file_hash(canonicalize_source_text(path.read_bytes()))


def _write_manifest(seed_root: Path, documents: list[dict]) -> Path:
    manifest = {
        "collection": "finquest_core_financial_education", "version": 1, "language": "en",
        "document_count": len(documents), "documents": documents,
    }
    manifest_path = seed_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _ingestion_service(uow_factory) -> KnowledgeIngestionService:
    return KnowledgeIngestionService(
        unit_of_work_factory=uow_factory, chunker=HeadingAwareWordChunker(),
        embedding_provider=DeterministicFakeEmbeddingAdapter(),
    )


def _manifest_service(seed_root: Path, storage: FakeObjectStorage, uow_factory) -> ManifestIngestionService:
    return ManifestIngestionService(
        object_storage=storage, knowledge_ingestion_service=_ingestion_service(uow_factory),
        seed_documents_root=seed_root, clock=lambda: NOW,
    )


def _seed_single_document(tmp_path: Path, *, body_paragraph: str = "Body content.") -> tuple[Path, dict]:
    seed_root = tmp_path / "seed_documents"
    source_text = _front_matter_source(document_id="kb-en-001", title="Doc A", body_paragraph=body_paragraph)
    file_hash = _write_seed_document(seed_root, filename="en/01_doc_a.md", source_text=source_text)
    entry = {
        "document_id": "kb-en-001", "filename": "en/01_doc_a.md", "title": "Doc A",
        "review_status": "approved_seed", "content_hash": file_hash,
    }
    manifest_path = _write_manifest(seed_root, [entry])
    return seed_root, entry


# -- tests ------------------------------------------------------------------------------------------


async def test_first_ingestion_creates_one_document_and_chunks(tmp_path: Path, uow_factory) -> None:
    seed_root, _entry = _seed_single_document(tmp_path)
    manifest = load_seed_manifest(seed_root / "manifest.json")
    storage = FakeObjectStorage()
    service = _manifest_service(seed_root, storage, uow_factory)

    summary = await service.ingest(manifest=manifest)

    assert summary.succeeded_count == 1
    assert summary.results[0].documents_created == 1
    assert storage.put_calls == 1

    async with uow_factory() as uow:
        documents = await uow.knowledge.list_approved_documents()
        assert len(documents) == 1
        chunks = await uow.knowledge.list_chunks_for_document(documents[0].document_id)
    assert len(chunks) >= 1


async def test_second_identical_ingestion_is_a_no_op(tmp_path: Path, uow_factory) -> None:
    seed_root, _entry = _seed_single_document(tmp_path)
    manifest = load_seed_manifest(seed_root / "manifest.json")
    storage = FakeObjectStorage()
    service = _manifest_service(seed_root, storage, uow_factory)

    first = await service.ingest(manifest=manifest)
    assert first.results[0].documents_created == 1

    second = await service.ingest(manifest=manifest)
    assert second.results[0].documents_created == 0
    assert second.results[0].documents_skipped_unchanged == 1
    assert second.results[0].upload_performed is False
    assert storage.put_calls == 1  # object was not re-uploaded on the second pass

    async with uow_factory() as uow:
        documents = await uow.knowledge.list_approved_documents()
    assert len(documents) == 1  # still exactly one approved document, not a duplicate


async def test_changed_content_archives_the_previous_version(tmp_path: Path, uow_factory) -> None:
    seed_root, entry = _seed_single_document(tmp_path)
    manifest = load_seed_manifest(seed_root / "manifest.json")
    storage = FakeObjectStorage()
    service = _manifest_service(seed_root, storage, uow_factory)

    first = await service.ingest(manifest=manifest)
    assert first.results[0].documents_created == 1

    async with uow_factory() as uow:
        original_docs = await uow.knowledge.list_approved_documents()
    original_document_id = original_docs[0].document_id

    # Edit the source file's body and refresh the manifest's content_hash to match.
    updated_text = _front_matter_source(
        document_id="kb-en-001", title="Doc A", body_paragraph="Updated body content."
    )
    new_hash = _write_seed_document(seed_root, filename="en/01_doc_a.md", source_text=updated_text)
    entry["content_hash"] = new_hash
    _write_manifest(seed_root, [entry])
    updated_manifest = load_seed_manifest(seed_root / "manifest.json")

    second = await service.ingest(manifest=updated_manifest)

    assert second.results[0].succeeded is True
    assert second.results[0].documents_created == 1
    assert second.results[0].documents_archived == 1
    assert second.results[0].upload_performed is True
    assert storage.put_calls == 2  # changed content is re-uploaded

    async with uow_factory() as uow:
        current_docs = await uow.knowledge.list_approved_documents()
    assert len(current_docs) == 1
    assert current_docs[0].document_id != original_document_id
    assert "Updated body content." in current_docs[0].content_text


async def test_chunks_exclude_front_matter(tmp_path: Path, uow_factory) -> None:
    seed_root, _entry = _seed_single_document(tmp_path)
    manifest = load_seed_manifest(seed_root / "manifest.json")
    storage = FakeObjectStorage()
    service = _manifest_service(seed_root, storage, uow_factory)

    await service.ingest(manifest=manifest)

    async with uow_factory() as uow:
        documents = await uow.knowledge.list_approved_documents()
        chunks = await uow.knowledge.list_chunks_for_document(documents[0].document_id)

    assert documents[0].content_text.startswith("# Doc A")
    for forbidden in ("review_status:", "document_id:", "language:", "concept_ids:", "source_policy:"):
        assert forbidden not in documents[0].content_text
        for chunk in chunks:
            assert forbidden not in chunk.content


async def test_partial_batch_failure_does_not_roll_back_earlier_successes(tmp_path: Path, uow_factory) -> None:
    seed_root = tmp_path / "seed_documents"
    good_text = _front_matter_source(document_id="kb-en-001", title="Doc A")
    bad_text = _front_matter_source(document_id="kb-en-002", title="Doc B")
    good_hash = _write_seed_document(seed_root, filename="en/01_doc_a.md", source_text=good_text)
    _write_seed_document(seed_root, filename="en/02_doc_b.md", source_text=bad_text)

    manifest_path = _write_manifest(
        seed_root,
        [
            {
                "document_id": "kb-en-001", "filename": "en/01_doc_a.md", "title": "Doc A",
                "review_status": "approved_seed", "content_hash": good_hash,
            },
            {
                # Deliberately wrong hash - this entry must fail without affecting kb-en-001.
                "document_id": "kb-en-002", "filename": "en/02_doc_b.md", "title": "Doc B",
                "review_status": "approved_seed", "content_hash": "b" * 64,
            },
        ],
    )
    manifest = load_seed_manifest(manifest_path)
    storage = FakeObjectStorage()
    service = _manifest_service(seed_root, storage, uow_factory)

    summary = await service.ingest(manifest=manifest)

    assert summary.succeeded_count == 1
    assert summary.failed_count == 1

    async with uow_factory() as uow:
        documents = await uow.knowledge.list_approved_documents()
    assert len(documents) == 1
    assert documents[0].title == "Doc A"
