"""PostgreSQL integration tests for `SqlAlchemyKnowledgeRepository.hybrid_search`.

Uses the deterministic, dimension-matched fake embedding adapter (384
dimensions, matching the real `vector(384)` column) so the full pgvector
HNSW query path is exercised without downloading a real model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.manifest_ingestion import ManifestIngestionService
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.seed_manifest import (
    canonicalize_source_text,
    compute_manifest_file_hash,
    load_seed_manifest,
)
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.exceptions import ObjectNotFoundError
from stock_research_core.application.object_storage.models import ObjectReference, StoredObject
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorContextType,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeChunkEmbedding, KnowledgeDocument, KnowledgeSource
from stock_research_core.domain.learning.enums import DifficultyLevel, LessonStatus
from stock_research_core.domain.learning.models import Lesson, LearningModule, LearningPath
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import DeterministicFakeEmbeddingAdapter

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _seed_chunk(
    uow_factory, embedder, *, content: str, approval_status=KnowledgeApprovalStatus.APPROVED,
    status=KnowledgeDocumentStatus.PROCESSED, language: str = "en", lesson_id=None, exercise_id=None,
    scenario_id=None, available_at=NOW, effective_until=None,
) -> tuple[KnowledgeSource, KnowledgeDocument, KnowledgeChunk]:
    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(
            KnowledgeSource(
                source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title=f"Source {uuid4()}",
                approval_status=approval_status,
            )
        )
        document = await uow.knowledge.upsert_document(
            KnowledgeDocument(
                source_id=source.source_id, title="Doc", content_text=content, content_hash=_hash(content),
                status=status, approval_status=approval_status, available_at=available_at,
                effective_until=effective_until, language=language, lesson_id=lesson_id,
                exercise_id=exercise_id, scenario_id=scenario_id, parser_version="v1",
            )
        )
        [chunk] = await uow.knowledge.upsert_chunks(
            [
                KnowledgeChunk(
                    document_id=document.document_id, chunk_index=0, content=content, content_hash=_hash(content),
                    word_count=len(content.split()), estimated_token_count=len(content.split()) + 2,
                    available_at=available_at, effective_until=effective_until,
                    chunking_version="heading-word-chunker-v1",
                )
            ]
        )
        [vector] = await embedder.embed_texts([content])
        await uow.knowledge.upsert_embeddings(
            [
                KnowledgeChunkEmbedding(
                    chunk_id=chunk.chunk_id, embedding_model=embedder.model_name,
                    embedding_version=embedder.embedding_version, embedding_dimension=embedder.dimension,
                )
            ],
            [vector],
        )
        await uow.commit()
    return source, document, chunk


@pytest.fixture
def embedder() -> DeterministicFakeEmbeddingAdapter:
    return DeterministicFakeEmbeddingAdapter()


async def _seed_lesson(uow_factory) -> Lesson:
    unique = uuid4().hex[:8]
    path = LearningPath(
        code=f"path-{unique}", title="Path", description="desc", difficulty=DifficultyLevel.BEGINNER,
        position=0, estimated_minutes=60, published=True,
    )
    async with uow_factory() as uow:
        await uow.curriculum.upsert_path(path)
        module = LearningModule(
            path_id=path.path_id, code=f"module-{unique}", title="Module", description="desc",
            position=0, estimated_minutes=30, published=True,
        )
        await uow.curriculum.upsert_module(module)
        lesson = Lesson(
            module_id=module.module_id, code=f"lesson-{unique}", title="Lesson", summary="Summary",
            content_markdown="Content", difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED,
            position=0, estimated_minutes=5, primary_skill_id=uuid4(),
        )
        # primary_skill_id must reference a real skill row (FK).
        from stock_research_core.domain.learning.enums import FinancialSkillCategory
        from stock_research_core.domain.learning.models import Skill

        skill = await uow.curriculum.upsert_skill(
            Skill(
                code=f"SKILL_{unique.upper()}", name="Skill", category=FinancialSkillCategory.MONEY_BASICS,
                description="d", difficulty=DifficultyLevel.BEGINNER,
            )
        )
        lesson = lesson.model_copy(update={"primary_skill_id": skill.skill_id})
        saved_lesson = await uow.curriculum.upsert_lesson(lesson)
        await uow.commit()
    return saved_lesson


async def test_only_approved_processed_documents_returned(uow_factory, embedder) -> None:
    _s1, _d1, approved_chunk = await _seed_chunk(uow_factory, embedder, content="Diversification reduces risk exposure widely.")
    _s2, _d2, _c2 = await _seed_chunk(
        uow_factory, embedder, content="Diversification reduces risk exposure widely too.",
        approval_status=KnowledgeApprovalStatus.DRAFT,
    )

    [vector] = await embedder.embed_texts(["diversification risk"])
    async with uow_factory() as uow:
        candidates, _count = await uow.knowledge.hybrid_search(
            query_embedding=vector, embedding_model=embedder.model_name, embedding_version=embedder.embedding_version,
            lexical_query="diversification risk", top_k=10,
        )
    chunk_ids = {c.chunk.chunk_id for c in candidates}
    assert approved_chunk.chunk_id in chunk_ids
    assert all(c.source.approval_status == KnowledgeApprovalStatus.APPROVED for c in candidates)
    assert all(c.document.approval_status == KnowledgeApprovalStatus.APPROVED for c in candidates)


async def test_language_filter(uow_factory, embedder) -> None:
    _s, _d, english_chunk = await _seed_chunk(uow_factory, embedder, content="Volatility measures return variation.")
    await _seed_chunk(uow_factory, embedder, content="La volatilite mesure la variation des rendements.", language="fr")

    [vector] = await embedder.embed_texts(["volatility"])
    async with uow_factory() as uow:
        candidates, _count = await uow.knowledge.hybrid_search(
            query_embedding=vector, embedding_model=embedder.model_name, embedding_version=embedder.embedding_version,
            lexical_query="volatility", top_k=10, language="en",
        )
    assert all(c.document.language == "en" for c in candidates)


async def test_knowledge_cutoff_excludes_future_content(uow_factory, embedder) -> None:
    cutoff = NOW
    _s, _d, past_chunk = await _seed_chunk(
        uow_factory, embedder, content="Concentration risk comes from one holding dominating a portfolio.",
        available_at=NOW - timedelta(days=10),
    )
    _s2, _d2, future_chunk = await _seed_chunk(
        uow_factory, embedder, content="Concentration risk dominating outcome revealed after the decision.",
        available_at=NOW + timedelta(days=10),
    )

    [vector] = await embedder.embed_texts(["concentration risk"])
    async with uow_factory() as uow:
        candidates, _count = await uow.knowledge.hybrid_search(
            query_embedding=vector, embedding_model=embedder.model_name, embedding_version=embedder.embedding_version,
            lexical_query="concentration risk", top_k=10, knowledge_cutoff_at=cutoff,
        )
    chunk_ids = {c.chunk.chunk_id for c in candidates}
    assert past_chunk.chunk_id in chunk_ids
    assert future_chunk.chunk_id not in chunk_ids


async def test_effective_until_excludes_expired_content(uow_factory, embedder) -> None:
    _s, _d, expired_chunk = await _seed_chunk(
        uow_factory, embedder, content="Outdated inflation figures from an old report.",
        available_at=NOW - timedelta(days=100), effective_until=NOW - timedelta(days=1),
    )
    [vector] = await embedder.embed_texts(["inflation figures"])
    async with uow_factory() as uow:
        candidates, _count = await uow.knowledge.hybrid_search(
            query_embedding=vector, embedding_model=embedder.model_name, embedding_version=embedder.embedding_version,
            lexical_query="inflation figures", top_k=10, knowledge_cutoff_at=NOW,
        )
    assert expired_chunk.chunk_id not in {c.chunk.chunk_id for c in candidates}


async def test_lesson_match_boosts_metadata_score(uow_factory, embedder) -> None:
    lesson = await _seed_lesson(uow_factory)
    lesson_id = lesson.lesson_id
    _s1, _d1, matching_chunk = await _seed_chunk(
        uow_factory, embedder, content="Bonds pay periodic interest called a coupon regularly.", lesson_id=lesson_id
    )
    _s2, _d2, other_chunk = await _seed_chunk(
        uow_factory, embedder, content="Bonds pay periodic interest called a coupon regularly too."
    )

    [vector] = await embedder.embed_texts(["bonds coupon interest"])
    async with uow_factory() as uow:
        candidates, _count = await uow.knowledge.hybrid_search(
            query_embedding=vector, embedding_model=embedder.model_name, embedding_version=embedder.embedding_version,
            lexical_query="bonds coupon interest", top_k=10, lesson_id=lesson_id,
        )
    by_id = {c.chunk.chunk_id: c for c in candidates}
    assert by_id[matching_chunk.chunk_id].metadata_score > by_id[other_chunk.chunk_id].metadata_score
    assert candidates[0].chunk.chunk_id == matching_chunk.chunk_id


async def test_candidate_count_reflects_pool_size(uow_factory, embedder) -> None:
    for i in range(5):
        await _seed_chunk(uow_factory, embedder, content=f"Compound interest grows savings over time example {i}.")

    [vector] = await embedder.embed_texts(["compound interest"])
    async with uow_factory() as uow:
        candidates, count = await uow.knowledge.hybrid_search(
            query_embedding=vector, embedding_model=embedder.model_name, embedding_version=embedder.embedding_version,
            lexical_query="compound interest", top_k=2,
        )
    assert len(candidates) <= 2
    assert count >= len(candidates)


async def test_no_query_embedding_falls_back_to_lexical_only(uow_factory, embedder) -> None:
    _s, _d, chunk = await _seed_chunk(uow_factory, embedder, content="Exchange-traded funds trade like a single stock.")
    async with uow_factory() as uow:
        candidates, _count = await uow.knowledge.hybrid_search(
            query_embedding=None, embedding_model=None, embedding_version=None,
            lexical_query="exchange-traded funds", top_k=10,
        )
    assert chunk.chunk_id in {c.chunk.chunk_id for c in candidates}


async def test_get_chunk_with_metadata_returns_full_candidate(uow_factory, embedder) -> None:
    _s, document, chunk = await _seed_chunk(uow_factory, embedder, content="A market index tracks a basket of securities.")
    async with uow_factory() as uow:
        candidate = await uow.knowledge.get_chunk_with_metadata(chunk.chunk_id)
    assert candidate is not None
    assert candidate.chunk.chunk_id == chunk.chunk_id
    assert candidate.document.document_id == document.document_id


async def test_get_chunk_with_metadata_returns_none_for_unknown_chunk(uow_factory) -> None:
    async with uow_factory() as uow:
        assert await uow.knowledge.get_chunk_with_metadata(uuid4()) is None


# -- C3 smoke test: a manifest-ingested document is retrievable via hybrid search ---------------------
#
# Small in-memory `ObjectStoragePort` fake, test-only (per the C3 spec -
# no fake adapter lives under `src/`, no real S3 call is ever made).


@dataclass
class _StoredVersion:
    body: bytes
    content_type: str
    sha256: str
    version_id: str


class _FakeObjectStorage:
    def __init__(self) -> None:
        self._versions: dict[str, list[_StoredVersion]] = {}
        self._version_seq = 0

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> ObjectReference:
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
        record = self._resolve(key, version_id)
        if record is None:
            raise ObjectNotFoundError(f"no object at key {key!r}")
        return ObjectReference(
            bucket="fake-bucket", key=key, content_type=record.content_type, byte_length=len(record.body),
            sha256=record.sha256, version_id=record.version_id,
        )

    async def get_object(self, *, key: str, version_id: str | None = None) -> StoredObject:
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


def _manifest_seed_source(*, document_id: str, title: str, body_paragraph: str) -> str:
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


async def test_manifest_ingested_document_is_retrievable_via_hybrid_search(tmp_path: Path, uow_factory, embedder) -> None:
    """End-to-end C3 smoke test: `ManifestIngestionService` (against a fake
    `ObjectStoragePort`) ingests one approved seed document through the
    real `KnowledgeIngestionService`, and the existing
    `HybridKnowledgeRetriever` - unmodified - surfaces it for a matching
    query. Proves C3 plugs into retrieval without a second RAG pipeline."""
    seed_root = tmp_path / "seed_documents"
    body_paragraph = "Diversification across asset classes reduces idiosyncratic portfolio risk substantially."
    source_text = _manifest_seed_source(document_id="kb-en-001", title="Diversification Basics", body_paragraph=body_paragraph)
    doc_path = seed_root / "en" / "01_diversification.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(source_text, encoding="utf-8", newline="\n")
    file_hash = compute_manifest_file_hash(canonicalize_source_text(doc_path.read_bytes()))

    manifest_path = seed_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "collection": "finquest_core_financial_education", "version": 1, "language": "en",
                "document_count": 1,
                "documents": [
                    {
                        "document_id": "kb-en-001", "filename": "en/01_diversification.md",
                        "title": "Diversification Basics", "review_status": "approved_seed",
                        "content_hash": file_hash,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = load_seed_manifest(manifest_path)

    ingestion_service = KnowledgeIngestionService(
        unit_of_work_factory=uow_factory, chunker=HeadingAwareWordChunker(), embedding_provider=embedder,
    )
    manifest_service = ManifestIngestionService(
        object_storage=_FakeObjectStorage(), knowledge_ingestion_service=ingestion_service,
        seed_documents_root=seed_root, clock=lambda: NOW,
    )

    summary = await manifest_service.ingest(manifest=manifest)
    assert summary.succeeded_count == 1
    assert summary.results[0].documents_created == 1

    retriever = HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedder)
    context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())

    _run, candidates = await retriever.retrieve(
        query="How does diversification reduce portfolio risk?", context=context, top_k=5
    )

    assert any("Diversification" in candidate.chunk.content for candidate in candidates)
    assert all(candidate.source.approval_status == KnowledgeApprovalStatus.APPROVED for candidate in candidates)
