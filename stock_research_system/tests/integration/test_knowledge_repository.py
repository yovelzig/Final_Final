"""PostgreSQL integration tests for `SqlAlchemyKnowledgeRepository`."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeIngestionRunStatus,
    KnowledgeSourceType,
)
from stock_research_core.domain.ai_tutor.models import (
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeDocument,
    KnowledgeSource,
)
from stock_research_core.domain.learning.enums import DifficultyLevel, FinancialSkillCategory
from stock_research_core.domain.learning.models import Skill

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _source(**overrides) -> KnowledgeSource:
    defaults = dict(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Test Source",
        approval_status=KnowledgeApprovalStatus.APPROVED, trusted=False,
    )
    defaults.update(overrides)
    return KnowledgeSource(**defaults)


def _document(source_id, content: str = "Approved content.", **overrides) -> KnowledgeDocument:
    defaults = dict(
        source_id=source_id, title="Doc", content_text=content, content_hash=_hash(content),
        status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW, parser_version="v1",
    )
    defaults.update(overrides)
    return KnowledgeDocument(**defaults)


def _chunk(document_id, content: str = "Chunk content.", index: int = 0, **overrides) -> KnowledgeChunk:
    defaults = dict(
        document_id=document_id, chunk_index=index, content=content, content_hash=_hash(content),
        word_count=len(content.split()), estimated_token_count=len(content.split()) + 2,
        available_at=NOW, chunking_version="heading-word-chunker-v1",
    )
    defaults.update(overrides)
    return KnowledgeChunk(**defaults)


async def test_upsert_and_get_source(uow_factory) -> None:
    source = _source()
    async with uow_factory() as uow:
        created = await uow.knowledge.upsert_source(source)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.knowledge.get_source(created.source_id)
    assert fetched is not None
    assert fetched.title == "Test Source"


async def test_upsert_source_is_idempotent_on_conflict(uow_factory) -> None:
    source_id = uuid4()
    async with uow_factory() as uow:
        await uow.knowledge.upsert_source(_source(source_id=source_id, title="First"))
        await uow.commit()

    async with uow_factory() as uow:
        updated = await uow.knowledge.upsert_source(_source(source_id=source_id, title="Second"))
        await uow.commit()

    assert updated.title == "Second"
    async with uow_factory() as uow:
        fetched = await uow.knowledge.get_source(source_id)
    assert fetched.title == "Second"


async def test_upsert_document_with_skill_ids(uow_factory) -> None:
    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(_source())
        skill = await uow.curriculum.upsert_skill(
            Skill(
                code="TEST_SKILL", name="Test Skill", category=FinancialSkillCategory.MONEY_BASICS,
                description="d", difficulty=DifficultyLevel.BEGINNER,
            )
        )
        await uow.commit()

    document = _document(source.source_id, skill_ids=[skill.skill_id])
    async with uow_factory() as uow:
        saved = await uow.knowledge.upsert_document(document)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.knowledge.get_document(saved.document_id)
    assert fetched.skill_ids == [skill.skill_id]


async def test_get_document_by_hash(uow_factory) -> None:
    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(_source())
        await uow.commit()

    document = _document(source.source_id, content="Unique content for hash lookup.")
    async with uow_factory() as uow:
        await uow.knowledge.upsert_document(document)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.knowledge.get_document_by_hash(source_id=source.source_id, content_hash=document.content_hash)
    assert found is not None
    assert found.document_id == document.document_id


async def test_archive_document_excludes_from_approved_list(uow_factory) -> None:
    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(_source())
        document = await uow.knowledge.upsert_document(_document(source.source_id, content="Archive me."))
        await uow.commit()

    async with uow_factory() as uow:
        archived = await uow.knowledge.archive_document(document.document_id)
        await uow.commit()
    assert archived.status == KnowledgeDocumentStatus.ARCHIVED
    assert archived.approval_status == KnowledgeApprovalStatus.ARCHIVED

    async with uow_factory() as uow:
        approved = await uow.knowledge.list_approved_documents(source_id=source.source_id)
    assert document.document_id not in {d.document_id for d in approved}


async def test_upsert_chunks_and_list_for_document(uow_factory) -> None:
    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(_source())
        document = await uow.knowledge.upsert_document(_document(source.source_id))
        await uow.commit()

    chunks = [_chunk(document.document_id, content=f"Chunk {i}.", index=i) for i in range(3)]
    async with uow_factory() as uow:
        saved = await uow.knowledge.upsert_chunks(chunks)
        await uow.commit()
    assert len(saved) == 3

    async with uow_factory() as uow:
        fetched = await uow.knowledge.list_chunks_for_document(document.document_id)
    assert [c.chunk_index for c in fetched] == [0, 1, 2]


async def test_upsert_chunks_is_idempotent_on_conflict(uow_factory) -> None:
    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(_source())
        document = await uow.knowledge.upsert_document(_document(source.source_id))
        await uow.commit()

    chunk = _chunk(document.document_id, content="Original.")
    async with uow_factory() as uow:
        await uow.knowledge.upsert_chunks([chunk])
        await uow.commit()

    updated_chunk = _chunk(document.document_id, content="Updated words for the same slot.")
    updated_chunk = updated_chunk.model_copy(update={"chunk_id": chunk.chunk_id})
    async with uow_factory() as uow:
        [result] = await uow.knowledge.upsert_chunks([updated_chunk])
        await uow.commit()
    assert result.content == "Updated words for the same slot."

    async with uow_factory() as uow:
        fetched = await uow.knowledge.list_chunks_for_document(document.document_id)
    assert len(fetched) == 1


async def test_upsert_embeddings_never_exposes_vector(uow_factory) -> None:
    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(_source())
        document = await uow.knowledge.upsert_document(_document(source.source_id))
        [chunk] = await uow.knowledge.upsert_chunks([_chunk(document.document_id)])
        await uow.commit()

    embedding = KnowledgeChunkEmbedding(
        chunk_id=chunk.chunk_id, embedding_model="test-model", embedding_version="v1", embedding_dimension=384,
    )
    vector = [0.01] * 384
    async with uow_factory() as uow:
        [saved] = await uow.knowledge.upsert_embeddings([embedding], [vector])
        await uow.commit()

    assert not hasattr(saved, "embedding")
    assert saved.embedding_dimension == 384


async def test_counts_reflect_stored_rows(uow_factory) -> None:
    async with uow_factory() as uow:
        before_sources = await uow.knowledge.count_sources()
        source = await uow.knowledge.upsert_source(_source())
        document = await uow.knowledge.upsert_document(_document(source.source_id))
        [chunk] = await uow.knowledge.upsert_chunks([_chunk(document.document_id)])
        await uow.knowledge.upsert_embeddings(
            [KnowledgeChunkEmbedding(chunk_id=chunk.chunk_id, embedding_model="m", embedding_version="v1", embedding_dimension=384)],
            [[0.01] * 384],
        )
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.knowledge.count_sources() == before_sources + 1
        assert await uow.knowledge.count_approved_documents() >= 1
        assert await uow.knowledge.count_chunks() >= 1
        assert await uow.knowledge.count_embeddings() >= 1


async def test_ingestion_run_lifecycle(uow_factory) -> None:
    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(_source())
        run = await uow.knowledge.start_ingestion_run(
            source_id=source.source_id, document_id=None, chunking_version="heading-word-chunker-v1",
            embedding_model="m", embedding_version="v1",
        )
        assert run.status == KnowledgeIngestionRunStatus.STARTED

        completed = await uow.knowledge.complete_ingestion_run(
            run.run_id, status=KnowledgeIngestionRunStatus.COMPLETED, documents_processed=1,
            chunks_created=2, embeddings_created=2,
        )
        await uow.commit()
    assert completed.status == KnowledgeIngestionRunStatus.COMPLETED
    assert completed.completed_at is not None

    async with uow_factory() as uow:
        recent = await uow.knowledge.list_recent_ingestion_runs(limit=5)
    assert any(r.run_id == run.run_id for r in recent)
