"""End-to-end PostgreSQL integration test for the grounded AI tutor
pipeline: ingest a local document, create a conversation, ask an
educational question (grounded), a buy/sell question (refused), and an
off-topic question (fallback), then close the conversation.

Uses the deterministic fake embedding adapter (384-dim, matching the
real `vector(384)` column) and the extractive tutor - no external model
or network access anywhere in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    KnowledgeApprovalStatus,
    TutorAnswerStatus,
    TutorContextType,
    TutorConversationStatus,
)
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import DeterministicExtractiveTutor

pytestmark = pytest.mark.integration


@pytest.fixture
def diversification_note(tmp_path: Path) -> Path:
    path = tmp_path / "diversification.md"
    path.write_text(
        "# Diversification\n\n"
        "Diversification is a risk-management strategy that mixes a variety of investments "
        "within a portfolio. It reduces reliance on any single asset, but it does not "
        "guarantee against losses.\n\n"
        "## Why It Matters\n\n"
        "Concentrating holdings in one security increases exposure to that security's "
        "specific risk.\n",
        encoding="utf-8",
    )
    return path


async def test_full_tutor_conversation_flow(uow_factory, diversification_note: Path) -> None:
    embedding_provider = DeterministicFakeEmbeddingAdapter()
    ingestion_service = KnowledgeIngestionService(
        unit_of_work_factory=uow_factory, chunker=HeadingAwareWordChunker(), embedding_provider=embedding_provider
    )
    summary = await ingestion_service.ingest_local_document(
        file_path=diversification_note, source_title=f"E2E Diversification Notes {uuid4()}",
        approval_status=KnowledgeApprovalStatus.APPROVED, skill_ids=[],
        available_at=datetime.now(timezone.utc),
    )
    assert summary.chunks_created >= 1
    assert summary.embeddings_created >= 1

    retriever = HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)
    tutor_service = GroundedAITutorService(
        unit_of_work_factory=uow_factory, retriever=retriever, tutor_model=DeterministicExtractiveTutor(),
        guardrail=RuleBasedTutorGuardrail(), prompt_builder=GroundedTutorPromptBuilder(),
    )

    learner = LearnerProfile(display_name="E2E Test Learner")
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        await uow.commit()

    context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=stored_learner.learner_id)
    conversation = await tutor_service.create_conversation(learner_id=stored_learner.learner_id, context=context)
    assert conversation.status == TutorConversationStatus.ACTIVE

    grounded_response = await tutor_service.ask(
        conversation_id=conversation.conversation_id, question="What is diversification?"
    )
    assert grounded_response.answer.status == TutorAnswerStatus.VALIDATED
    assert grounded_response.answer.grounding_status == GroundingStatus.GROUNDED
    assert len(grounded_response.citations) >= 1
    assert grounded_response.citations[0].excerpt in diversification_note.read_text(encoding="utf-8")

    refusal_response = await tutor_service.ask(
        conversation_id=conversation.conversation_id, question="Should I buy NVDA?"
    )
    assert refusal_response.answer.status == TutorAnswerStatus.REJECTED
    assert refusal_response.citations == []

    fallback_response = await tutor_service.ask(
        conversation_id=conversation.conversation_id,
        question="Can you recommend a good pizza restaurant near me?",
    )
    assert fallback_response.answer.status == TutorAnswerStatus.FALLBACK

    closed = await tutor_service.close_conversation(conversation.conversation_id)
    assert closed.status == TutorConversationStatus.CLOSED
    assert closed.closed_at is not None

    async with uow_factory() as uow:
        answers = await uow.tutor_answers.list_answers_for_conversation(conversation.conversation_id)
        messages = await uow.tutor_conversations.list_recent_messages(conversation.conversation_id, limit=10)
        gaps = await uow.tutor_knowledge_gaps.list_unresolved_gaps(limit=50)
    assert len(answers) == 3
    assert len(messages) == 6  # 3 user + 3 assistant, chronologically ordered
    assert any(gap.conversation_id == conversation.conversation_id for gap in gaps)


async def test_ingestion_is_idempotent_across_repeated_runs(uow_factory, diversification_note: Path) -> None:
    embedding_provider = DeterministicFakeEmbeddingAdapter()
    ingestion_service = KnowledgeIngestionService(
        unit_of_work_factory=uow_factory, chunker=HeadingAwareWordChunker(), embedding_provider=embedding_provider
    )
    source_title = f"Idempotency Test {uuid4()}"
    first = await ingestion_service.ingest_local_document(
        file_path=diversification_note, source_title=source_title, approval_status=KnowledgeApprovalStatus.APPROVED,
        skill_ids=[], available_at=datetime.now(timezone.utc),
    )
    second = await ingestion_service.ingest_local_document(
        file_path=diversification_note, source_title=source_title, approval_status=KnowledgeApprovalStatus.APPROVED,
        skill_ids=[], available_at=datetime.now(timezone.utc),
    )
    assert first.documents_created == 1
    assert second.documents_created == 0
    assert second.documents_skipped_unchanged == 1
