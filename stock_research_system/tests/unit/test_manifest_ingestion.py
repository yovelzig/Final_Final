"""Unit tests for the C3 manifest-ingestion orchestrator.

Uses a small in-memory `ObjectStoragePort` fake (defined here, not in
`src/`) and a fake `KnowledgeIngestionService` double so these tests
exercise only `ManifestIngestionService`'s own orchestration logic - S3
key building, hash verification, dry-run write-avoidance, batch
selection, and per-document failure isolation - without a real
PostgreSQL database. The real `KnowledgeIngestionService` wired to a
real database is exercised separately in
`tests/integration/test_manifest_ingestion_idempotency.py`.

`source_key` backward-compatibility is tested directly against
`KnowledgeIngestionService.ingest_local_document` using a minimal
in-memory `KnowledgeRepositoryPort` fake, since that behavior lives in
`knowledge_ingestion.py` itself, not in the orchestrator.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.manifest_ingestion import ManifestIngestionService
from stock_research_core.application.ai_tutor.seed_manifest import (
    canonicalize_source_text,
    compute_manifest_file_hash,
    load_seed_manifest,
)
from stock_research_core.application.exceptions import (
    ObjectNotFoundError,
    SeedManifestDocumentNotFoundError,
)
from stock_research_core.application.object_storage.models import ObjectReference, StoredObject
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeIngestionRunStatus,
    KnowledgeSourceType,
)
from stock_research_core.application.ai_tutor.models import KnowledgeIngestionRunRecord
from stock_research_core.domain.ai_tutor.models import KnowledgeSource
from stock_research_core.domain.models import utc_now
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# -- in-memory ObjectStoragePort fake (test-only, per C3 spec: not in src/) -------------------------


@dataclass
class _StoredVersion:
    body: bytes
    content_type: str
    sha256: str
    version_id: str


class FakeObjectStorage:
    """Minimal in-memory `ObjectStoragePort` implementation for tests only.

    Tracks per-call counters (proving dry-run makes zero writes),
    produces deterministic sequential version IDs, and supports
    optionally injecting failures for specific keys.
    """

    def __init__(self) -> None:
        self._versions: dict[str, list[_StoredVersion]] = {}
        self._version_seq = 0
        self.put_calls = 0
        self.get_calls = 0
        self.head_calls = 0
        self.get_calls_by_version: list[tuple[str, str | None]] = []
        self.corrupt_on_download: set[str] = set()
        self.fail_put_for_keys: set[str] = set()

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> ObjectReference:
        self.put_calls += 1
        if key in self.fail_put_for_keys:
            raise RuntimeError(f"injected put_object failure for {key!r}")
        self._version_seq += 1
        version_id = f"v{self._version_seq}"
        sha256 = hashlib.sha256(body).hexdigest()
        record = _StoredVersion(body=body, content_type=content_type, sha256=sha256, version_id=version_id)
        self._versions.setdefault(key, []).append(record)
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
        self.get_calls_by_version.append((key, version_id))
        record = self._resolve(key, version_id)
        if record is None:
            raise ObjectNotFoundError(f"no object at key {key!r} version {version_id!r}")
        body = record.body
        if key in self.corrupt_on_download:
            body = body + b"\x00corrupted-in-transit"
        return StoredObject(
            body=body,
            reference=ObjectReference(
                bucket="fake-bucket", key=key, content_type=record.content_type, byte_length=len(body),
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


# -- fake KnowledgeIngestionService double ------------------------------------------------------------


@dataclass
class _RecordedIngestCall:
    file_path: Path
    source_title: str
    source_key: str | None
    approval_status: KnowledgeApprovalStatus


@dataclass
class _FakeIngestionSummary:
    documents_created: int = 1
    documents_skipped_unchanged: int = 0
    documents_archived: int = 0


class FakeKnowledgeIngestionService:
    """Duck-typed stand-in for `KnowledgeIngestionService`, recording calls
    so tests can assert the orchestrator strips front matter and wires
    `source_key`/`source_title` correctly, without a real database."""

    def __init__(self) -> None:
        self.calls: list[_RecordedIngestCall] = []
        self.next_summary = _FakeIngestionSummary()
        self.captured_body: str | None = None

    async def ingest_local_document(
        self, *, file_path: Path, source_title: str, approval_status, skill_ids, available_at, source_key=None
    ):
        self.captured_body = file_path.read_text(encoding="utf-8")
        self.calls.append(
            _RecordedIngestCall(
                file_path=file_path, source_title=source_title, source_key=source_key,
                approval_status=approval_status,
            )
        )
        return self.next_summary


# -- fixtures: a small on-disk manifest + matching seed documents -----------------------------------


def _front_matter_source(
    *, document_id: str, title: str, review_status: str = "approved_seed", version: int = 1, body_extra: str = ""
) -> str:
    return (
        "---\n"
        f'document_id: "{document_id}"\n'
        f'title: "{title}"\n'
        f"version: {version}\n"
        'language: "en"\n'
        f'review_status: "{review_status}"\n'
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
        f"Body content for {document_id}.{body_extra}\n"
    )


def _write_seed_document(seed_root: Path, *, filename: str, source_text: str) -> str:
    path = seed_root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source_text, encoding="utf-8", newline="\n")
    return compute_manifest_file_hash(canonicalize_source_text(path.read_bytes()))


def _write_manifest(seed_root: Path, documents: list[dict]) -> Path:
    manifest = {
        "collection": "finquest_core_financial_education",
        "version": 1,
        "language": "en",
        "document_count": len(documents),
        "documents": documents,
    }
    manifest_path = seed_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


@pytest.fixture
def seed_world(tmp_path: Path):
    seed_root = tmp_path / "seed_documents"
    doc_a_text = _front_matter_source(document_id="kb-en-001", title="Doc A")
    doc_b_text = _front_matter_source(document_id="kb-en-002", title="Doc B", review_status="draft_requires_source_review")
    hash_a = _write_seed_document(seed_root, filename="en/01_doc_a.md", source_text=doc_a_text)
    hash_b = _write_seed_document(seed_root, filename="en/02_doc_b.md", source_text=doc_b_text)
    manifest_path = _write_manifest(
        seed_root,
        [
            {
                "document_id": "kb-en-001", "filename": "en/01_doc_a.md", "title": "Doc A",
                "review_status": "approved_seed", "content_hash": hash_a,
            },
            {
                "document_id": "kb-en-002", "filename": "en/02_doc_b.md", "title": "Doc B",
                "review_status": "draft_requires_source_review", "content_hash": hash_b,
            },
        ],
    )
    manifest = load_seed_manifest(manifest_path)
    return {"seed_root": seed_root, "manifest": manifest, "manifest_path": manifest_path}


def _service(seed_root: Path, storage: FakeObjectStorage, ingestion: FakeKnowledgeIngestionService) -> ManifestIngestionService:
    return ManifestIngestionService(
        object_storage=storage, knowledge_ingestion_service=ingestion, seed_documents_root=seed_root, clock=lambda: NOW,
    )


# -- batch selection: approved-only default behavior -------------------------------------------------


async def test_default_batch_processes_only_approved_seed_entries(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    summary = await service.ingest(manifest=seed_world["manifest"])

    assert summary.processed_count == 1
    assert summary.results[0].document_code == "kb-en-001"
    assert summary.results[0].succeeded is True
    assert len(summary.skipped_entries) == 1
    assert summary.skipped_entries[0].document_code == "kb-en-002"
    assert summary.skipped_entries[0].review_status == "draft_requires_source_review"
    assert len(ingestion.calls) == 1


async def test_source_key_and_title_passed_through_to_ingestion_service(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    await service.ingest(manifest=seed_world["manifest"])

    [call] = ingestion.calls
    assert call.source_key == "kb-en-001"
    assert call.source_title == "Doc A"


async def test_stripped_body_excludes_front_matter_keys(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    await service.ingest(manifest=seed_world["manifest"])

    assert ingestion.captured_body is not None
    assert ingestion.captured_body.startswith("# Doc A")
    for forbidden in ("review_status:", "document_id:", "language:"):
        assert forbidden not in ingestion.captured_body


# -- single-document mode ------------------------------------------------------------------------------


async def test_single_document_mode_selects_exactly_one(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    summary = await service.ingest(manifest=seed_world["manifest"], document_code="kb-en-001")

    assert summary.processed_count == 1
    assert summary.results[0].document_code == "kb-en-001"
    assert len(ingestion.calls) == 1


async def test_unknown_single_document_code_is_a_controlled_error(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    with pytest.raises(SeedManifestDocumentNotFoundError):
        await service.ingest(manifest=seed_world["manifest"], document_code="kb-en-999")

    assert ingestion.calls == []


async def test_single_document_mode_for_non_approved_entry_is_skipped_not_processed(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    summary = await service.ingest(manifest=seed_world["manifest"], document_code="kb-en-002")

    assert summary.processed_count == 0
    assert len(summary.skipped_entries) == 1
    assert ingestion.calls == []


# -- dry run: zero write operations -------------------------------------------------------------------


async def test_dry_run_performs_zero_write_operations(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    summary = await service.ingest(manifest=seed_world["manifest"], dry_run=True)

    assert summary.dry_run is True
    assert storage.put_calls == 0
    assert storage.get_calls == 0
    assert storage.head_calls == 1  # read-only validation is allowed
    assert ingestion.calls == []
    assert summary.results[0].upload_performed is False
    assert summary.results[0].documents_created == 0


async def test_dry_run_reports_planned_upload_when_object_missing(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    summary = await service.ingest(manifest=seed_world["manifest"], dry_run=True)

    assert summary.results[0].object_version_id is None  # nothing uploaded yet, so no real version exists


# -- head_object / put_object skip-if-unchanged behavior ------------------------------------------------


async def test_unchanged_object_skips_upload(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    first = await service.ingest(manifest=seed_world["manifest"])
    assert first.results[0].upload_performed is True
    assert storage.put_calls == 1

    second = await service.ingest(manifest=seed_world["manifest"])
    assert second.results[0].upload_performed is False
    assert storage.put_calls == 1  # no second upload
    assert second.results[0].object_version_id == first.results[0].object_version_id


async def test_get_object_uses_the_exact_version_id_from_put(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    summary = await service.ingest(manifest=seed_world["manifest"])

    version_id = summary.results[0].object_version_id
    assert version_id is not None
    assert (summary.results[0].object_key, version_id) in storage.get_calls_by_version


# -- integrity checks -------------------------------------------------------------------------------


async def test_local_file_hash_mismatch_fails_that_entry_only(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    tampered = seed_world["seed_root"] / "en" / "01_doc_a.md"
    tampered.write_text(tampered.read_text(encoding="utf-8") + "\nUnexpected edit.\n", encoding="utf-8")

    summary = await service.ingest(manifest=seed_world["manifest"])

    assert summary.results[0].succeeded is False
    assert "content_hash" in summary.results[0].failure_reason
    assert ingestion.calls == []


async def test_downloaded_hash_mismatch_fails_that_entry(seed_world) -> None:
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_world["seed_root"], storage, ingestion)

    object_key = "knowledge/seed/en/01_doc_a.md"
    storage.corrupt_on_download.add(object_key)

    summary = await service.ingest(manifest=seed_world["manifest"], document_code="kb-en-001")

    assert summary.results[0].succeeded is False
    assert "downloaded object hash" in summary.results[0].failure_reason
    assert ingestion.calls == []


# -- partial batch failure does not roll back earlier successes ------------------------------------------


async def test_partial_batch_failure_does_not_affect_other_entries(tmp_path: Path) -> None:
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
                # Deliberately wrong hash so this entry fails at the local-file-hash check.
                "document_id": "kb-en-002", "filename": "en/02_doc_b.md", "title": "Doc B",
                "review_status": "approved_seed", "content_hash": "b" * 64,
            },
        ],
    )
    manifest = load_seed_manifest(manifest_path)
    storage = FakeObjectStorage()
    ingestion = FakeKnowledgeIngestionService()
    service = _service(seed_root, storage, ingestion)

    summary = await service.ingest(manifest=manifest)

    assert summary.processed_count == 2
    assert summary.succeeded_count == 1
    assert summary.failed_count == 1
    by_code = {result.document_code: result for result in summary.results}
    assert by_code["kb-en-001"].succeeded is True
    assert by_code["kb-en-002"].succeeded is False
    assert len(ingestion.calls) == 1
    assert ingestion.calls[0].source_key == "kb-en-001"


# -- source_key backward compatibility (KnowledgeIngestionService itself) ------------------------------


class _FakeKnowledgeRepo:
    """Minimal in-memory `KnowledgeRepositoryPort` covering only the
    methods `ingest_local_document` calls - enough to prove `source_key`
    backward compatibility without a real database."""

    def __init__(self) -> None:
        self.sources: dict[UUID, KnowledgeSource] = {}
        self.documents: dict[UUID, object] = {}

    async def get_source(self, source_id: UUID):
        return self.sources.get(source_id)

    async def upsert_source(self, source: KnowledgeSource) -> KnowledgeSource:
        self.sources[source.source_id] = source
        return source

    async def start_ingestion_run(
        self, *, source_id, document_id, chunking_version, embedding_model, embedding_version
    ) -> KnowledgeIngestionRunRecord:
        return KnowledgeIngestionRunRecord(
            run_id=uuid4(), source_id=source_id, document_id=document_id,
            status=KnowledgeIngestionRunStatus.STARTED, chunking_version=chunking_version,
            embedding_model=embedding_model, embedding_version=embedding_version, started_at=utc_now(),
        )

    async def complete_ingestion_run(self, run_id, **kwargs) -> KnowledgeIngestionRunRecord:
        return KnowledgeIngestionRunRecord(
            run_id=run_id, status=kwargs.get("status", KnowledgeIngestionRunStatus.COMPLETED),
            chunking_version="v", embedding_model="m", embedding_version="v", started_at=utc_now(),
            completed_at=utc_now(),
            documents_processed=kwargs.get("documents_processed", 0),
            chunks_created=kwargs.get("chunks_created", 0),
            embeddings_created=kwargs.get("embeddings_created", 0),
        )

    async def get_document(self, document_id: UUID):
        return self.documents.get(document_id)

    async def upsert_document(self, document):
        self.documents[document.document_id] = document
        return document

    async def upsert_chunks(self, chunks):
        return chunks

    async def upsert_embeddings(self, embeddings, vectors):
        return embeddings

    async def list_approved_documents(self, **kwargs):
        return []

    async def archive_document(self, document_id):
        raise AssertionError("archive_document should not be called in these tests")


class _FakeUnitOfWork:
    def __init__(self, repo: _FakeKnowledgeRepo) -> None:
        self.knowledge = repo

    async def __aenter__(self) -> "_FakeUnitOfWork":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def commit(self) -> None:
        pass


def _real_ingestion_service(repo: _FakeKnowledgeRepo) -> KnowledgeIngestionService:
    return KnowledgeIngestionService(
        unit_of_work_factory=lambda: _FakeUnitOfWork(repo),
        chunker=HeadingAwareWordChunker(),
        embedding_provider=DeterministicFakeEmbeddingAdapter(),
    )


async def test_ingest_local_document_without_source_key_keeps_prior_behavior(tmp_path: Path) -> None:
    repo = _FakeKnowledgeRepo()
    service = _real_ingestion_service(repo)
    file_path = tmp_path / "doc.md"
    file_path.write_text("# Title\n\nSome content.\n", encoding="utf-8")

    first = await service.ingest_local_document(
        file_path=file_path, source_title="My Local Doc", approval_status=KnowledgeApprovalStatus.APPROVED,
        skill_ids=[], available_at=NOW,
    )
    second = await service.ingest_local_document(
        file_path=file_path, source_title="My Local Doc", approval_status=KnowledgeApprovalStatus.APPROVED,
        skill_ids=[], available_at=NOW,
    )

    assert first.documents_created == 1
    assert second.documents_created == 0
    assert second.documents_skipped_unchanged == 1


async def test_ingest_local_document_source_key_overrides_identity_derivation(tmp_path: Path) -> None:
    repo = _FakeKnowledgeRepo()
    service = _real_ingestion_service(repo)
    file_path = tmp_path / "doc.md"
    file_path.write_text("# Title\n\nSome content.\n", encoding="utf-8")

    by_title = await service.ingest_local_document(
        file_path=file_path, source_title="Human Readable Title", approval_status=KnowledgeApprovalStatus.APPROVED,
        skill_ids=[], available_at=NOW,
    )
    by_key = await service.ingest_local_document(
        file_path=file_path, source_title="A Totally Different Title", source_key="kb-en-001",
        approval_status=KnowledgeApprovalStatus.APPROVED, skill_ids=[], available_at=NOW,
    )

    # Different logical identities (title-derived vs key-derived) -> two distinct sources/documents.
    assert by_title.documents_created == 1
    assert by_key.documents_created == 1
    assert len(repo.sources) == 2
    assert len(repo.documents) == 2


async def test_ingest_local_document_same_source_key_is_idempotent_despite_title_change(tmp_path: Path) -> None:
    repo = _FakeKnowledgeRepo()
    service = _real_ingestion_service(repo)
    file_path = tmp_path / "doc.md"
    file_path.write_text("# Title\n\nSome content.\n", encoding="utf-8")

    first = await service.ingest_local_document(
        file_path=file_path, source_title="Title Version A", source_key="kb-en-001",
        approval_status=KnowledgeApprovalStatus.APPROVED, skill_ids=[], available_at=NOW,
    )
    second = await service.ingest_local_document(
        file_path=file_path, source_title="Title Version B (renamed)", source_key="kb-en-001",
        approval_status=KnowledgeApprovalStatus.APPROVED, skill_ids=[], available_at=NOW,
    )

    assert first.documents_created == 1
    assert second.documents_created == 0
    assert second.documents_skipped_unchanged == 1
    # The human-readable title on the stored source reflects the latest call.
    [source] = repo.sources.values()
    assert source.title == "Title Version B (renamed)"
