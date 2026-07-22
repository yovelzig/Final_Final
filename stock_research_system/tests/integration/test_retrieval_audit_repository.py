"""PostgreSQL integration tests for `SqlAlchemyRetrievalAuditRepository`."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.models import RetrievalCandidate
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    RetrievalMethod,
    TutorContextType,
)
from stock_research_core.domain.ai_tutor.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    TutorConversation,
    TutorRetrievalRun,
)
from stock_research_core.domain.learning.models import LearnerProfile

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_conversation_and_chunks(uow_factory, count: int = 2):
    learner = LearnerProfile(display_name="Retrieval Audit Test Learner")
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        conversation = await uow.tutor_conversations.create_conversation(
            TutorConversation(learner_id=stored_learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
        )
        source = await uow.knowledge.upsert_source(
            KnowledgeSource(
                source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Source",
                approval_status=KnowledgeApprovalStatus.APPROVED,
            )
        )
        chunks = []
        for i in range(count):
            content = f"Content chunk number {i}."
            document = await uow.knowledge.upsert_document(
                KnowledgeDocument(
                    source_id=source.source_id, title=f"Doc {i}", content_text=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(), status=KnowledgeDocumentStatus.PROCESSED,
                    approval_status=KnowledgeApprovalStatus.APPROVED, available_at=NOW, parser_version="v1",
                )
            )
            [chunk] = await uow.knowledge.upsert_chunks(
                [
                    KnowledgeChunk(
                        document_id=document.document_id, chunk_index=0, content=content,
                        content_hash=hashlib.sha256(content.encode()).hexdigest(), word_count=4,
                        estimated_token_count=6, available_at=NOW, chunking_version="heading-word-chunker-v1",
                    )
                ]
            )
            chunks.append(chunk)
        await uow.commit()
    return conversation, chunks


async def test_save_and_get_run_with_ordered_chunks(uow_factory) -> None:
    conversation, chunks = await _seed_conversation_and_chunks(uow_factory, count=2)
    run = TutorRetrievalRun(
        conversation_id=conversation.conversation_id, query_text="query", method=RetrievalMethod.HYBRID, top_k=8,
        retrieval_policy_version="hybrid-retrieval-v1", embedding_model="m", embedding_version="v1",
        candidate_count=2, returned_chunk_ids=[c.chunk_id for c in chunks], returned_scores=[0.9, 0.5],
    )
    async with uow_factory() as uow:
        saved = await uow.tutor_retrieval.save_run(run, candidates=[])
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.tutor_retrieval.get_run(saved.retrieval_run_id)
    assert fetched is not None
    assert fetched.returned_chunk_ids == [c.chunk_id for c in chunks]
    assert fetched.returned_scores == [0.9, 0.5]


async def test_list_recent_runs(uow_factory) -> None:
    conversation, chunks = await _seed_conversation_and_chunks(uow_factory, count=1)
    run = TutorRetrievalRun(
        conversation_id=conversation.conversation_id, query_text="another query", method=RetrievalMethod.HYBRID,
        top_k=8, retrieval_policy_version="hybrid-retrieval-v1", embedding_model="m", embedding_version="v1",
        candidate_count=1, returned_chunk_ids=[chunks[0].chunk_id], returned_scores=[0.7],
    )
    async with uow_factory() as uow:
        await uow.tutor_retrieval.save_run(run, candidates=[])
        await uow.commit()

    async with uow_factory() as uow:
        recent = await uow.tutor_retrieval.list_recent_runs(conversation.conversation_id, limit=5)
    assert len(recent) == 1
    assert recent[0].query_text == "another query"


async def test_run_with_no_returned_chunks(uow_factory) -> None:
    conversation, _chunks = await _seed_conversation_and_chunks(uow_factory, count=0)
    run = TutorRetrievalRun(
        conversation_id=conversation.conversation_id, query_text="no results query", method=RetrievalMethod.HYBRID,
        top_k=8, retrieval_policy_version="hybrid-retrieval-v1", embedding_model="m", embedding_version="v1",
        candidate_count=0,
    )
    async with uow_factory() as uow:
        saved = await uow.tutor_retrieval.save_run(run, candidates=[])
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.tutor_retrieval.get_run(saved.retrieval_run_id)
    assert fetched.returned_chunk_ids == []
    assert fetched.candidate_count == 0
