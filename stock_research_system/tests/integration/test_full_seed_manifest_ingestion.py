"""Full-corpus PostgreSQL integration test for Phase F1b/C3 local
integration: ingests the real, committed 15-document seed-knowledge
corpus (`knowledge/seed_documents/manifest.json`) through the real
`ManifestIngestionService` and `KnowledgeIngestionService`, against a
small in-test `ObjectStoragePort` fake (test-only, per the C3 spec - no
boto3, no moto, no LocalStack, no real AWS, and no fake implementation
lives under `src/`).

Covers: the first run selects and succeeds on all 15 approved-seed
entries, stores the complete canonical source under
`knowledge/seed/en/`, and produces documents/chunks with front matter
stripped; an identical second run is a no-op (no new documents, no
redundant uploads); and a retrieval smoke check proves one seed
document is findable and citation-eligible through the existing hybrid
retriever.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.manifest_ingestion import ManifestIngestionService
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.seed_manifest import (
    canonicalize_source_text,
    load_seed_manifest,
    resolve_document_path,
)
from stock_research_core.application.exceptions import ObjectNotFoundError
from stock_research_core.application.object_storage.models import ObjectReference, StoredObject
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SEED_DOCUMENTS_ROOT = _PROJECT_ROOT / "knowledge" / "seed_documents"
_MANIFEST_PATH = _SEED_DOCUMENTS_ROOT / "manifest.json"

_FORBIDDEN_FRONT_MATTER_KEYS = ("review_status:", "concept_ids:", "source_policy:", "document_id:", "language:")


# -- in-memory ObjectStoragePort fake (test-only, per C3 spec: not in src/) -------------------------


@dataclass
class _StoredVersion:
    body: bytes
    content_type: str
    sha256: str
    version_id: str


class FakeObjectStorage:
    """Minimal in-memory `ObjectStoragePort` implementation for tests only.

    Exposes stored bodies/hashes directly so this test can assert the
    complete canonical source file was stored and its hash matches the
    manifest, without ever touching a real S3 bucket.
    """

    def __init__(self) -> None:
        self._versions: dict[str, list[_StoredVersion]] = {}
        self._version_seq = 0
        self.put_calls = 0
        self.get_calls = 0
        self.head_calls = 0

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> ObjectReference:
        import hashlib

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

    def stored_body(self, key: str) -> bytes:
        return self._versions[key][-1].body

    def stored_sha256(self, key: str) -> str:
        return self._versions[key][-1].sha256


def _manifest_service(storage: FakeObjectStorage, uow_factory, embedding_provider=None) -> ManifestIngestionService:
    ingestion_service = KnowledgeIngestionService(
        unit_of_work_factory=uow_factory,
        chunker=HeadingAwareWordChunker(),
        embedding_provider=embedding_provider or DeterministicFakeEmbeddingAdapter(),
    )
    return ManifestIngestionService(
        object_storage=storage, knowledge_ingestion_service=ingestion_service,
        seed_documents_root=_SEED_DOCUMENTS_ROOT, clock=lambda: NOW,
    )


# -- first run: the full, real, committed 15-document corpus -----------------------------------------


async def test_first_run_ingests_all_fifteen_approved_seed_documents(uow_factory) -> None:
    manifest = load_seed_manifest(_MANIFEST_PATH, seed_documents_root=_SEED_DOCUMENTS_ROOT)
    assert manifest.document_count == 15
    assert len(manifest.approved_documents()) == 15

    storage = FakeObjectStorage()
    service = _manifest_service(storage, uow_factory)

    summary = await service.ingest(manifest=manifest)

    assert summary.processed_count == 15
    assert summary.failed_count == 0
    assert summary.succeeded_count == 15
    assert len(summary.skipped_entries) == 0

    for entry, result in zip(manifest.approved_documents(), summary.results):
        assert result.succeeded is True
        assert result.object_key.startswith("knowledge/seed/en/")
        assert result.documents_created == 1

        # Every fake object stores the complete canonical source file, and
        # its stored hash matches the manifest's own content_hash.
        file_path = resolve_document_path(_SEED_DOCUMENTS_ROOT, entry.filename, language=manifest.language)
        expected_bytes = canonicalize_source_text(file_path.read_bytes())
        assert storage.stored_body(result.object_key) == expected_bytes
        assert storage.stored_sha256(result.object_key) == entry.content_hash

    async with uow_factory() as uow:
        documents = await uow.knowledge.list_approved_documents()
        assert len(documents) == 15

        for document in documents:
            chunks = await uow.knowledge.list_chunks_for_document(document.document_id)
            assert len(chunks) >= 1
            for forbidden in _FORBIDDEN_FRONT_MATTER_KEYS:
                assert forbidden not in document.content_text
                for chunk in chunks:
                    assert forbidden not in chunk.content


# -- second, identical run: a full no-op -------------------------------------------------------------


async def test_second_identical_run_is_a_full_no_op(uow_factory) -> None:
    manifest = load_seed_manifest(_MANIFEST_PATH, seed_documents_root=_SEED_DOCUMENTS_ROOT)
    storage = FakeObjectStorage()
    service = _manifest_service(storage, uow_factory)

    first = await service.ingest(manifest=manifest)
    assert first.failed_count == 0
    put_calls_after_first = storage.put_calls
    assert put_calls_after_first == 15

    second = await service.ingest(manifest=manifest)

    assert second.failed_count == 0
    assert second.processed_count == 15
    for result in second.results:
        assert result.documents_created == 0
        assert result.documents_skipped_unchanged == 1
        assert result.upload_performed is False

    # No redundant object upload occurs when the stored metadata hash matches.
    assert storage.put_calls == put_calls_after_first

    async with uow_factory() as uow:
        documents = await uow.knowledge.list_approved_documents()
    assert len(documents) == 15  # still exactly 15, no duplicates


# -- retrieval smoke: one concept clearly covered by one seed document --------------------------------


async def test_retrieval_smoke_finds_a_citation_eligible_approved_result(uow_factory) -> None:
    manifest = load_seed_manifest(_MANIFEST_PATH, seed_documents_root=_SEED_DOCUMENTS_ROOT)
    storage = FakeObjectStorage()
    embedding_provider = DeterministicFakeEmbeddingAdapter()
    service = _manifest_service(storage, uow_factory, embedding_provider=embedding_provider)

    summary = await service.ingest(manifest=manifest)
    assert summary.failed_count == 0

    retriever = HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)
    context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())

    _retrieval_run, candidates = await retriever.retrieve(
        query="What is compound interest and how does compounding frequency affect it?",
        context=context,
        top_k=8,
    )

    assert len(candidates) >= 1

    titles = {candidate.document.title for candidate in candidates}
    assert any("Interest" in title or "Compound" in title for title in titles), (
        f"expected a result whose document title covers compound interest, got: {titles}"
    )

    for candidate in candidates:
        # Human-readable titles, not a bare manifest code.
        assert candidate.document.title
        assert not candidate.document.title.startswith("kb-en-")
        assert candidate.source.title
        # Citation-eligible: non-empty chunk content with front matter stripped.
        assert candidate.chunk.content.strip()
        for forbidden in _FORBIDDEN_FRONT_MATTER_KEYS:
            assert forbidden not in candidate.chunk.content
