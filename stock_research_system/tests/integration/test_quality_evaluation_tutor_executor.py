"""Integration test for the real `TutorGroundedCaseExecutor` (Phase 13)
against the actual `GroundedAITutorService` pipeline - ingests a real
document, then proves a curated `GENERAL_RAG` case executes through it
end to end: real retrieval, real citations mapped back to real chunk
ids (bypassing the learner-safe citation view, which deliberately hides
them), and that the evaluation conversation never becomes part of any
real learner's history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.quality_evaluation.models import EvaluationCaseExecutionInput
from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus, TutorRequestCategory
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.quality_evaluation.enums import EvaluationCaseContextType
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import DeterministicFakeEmbeddingAdapter
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import DeterministicExtractiveTutor
from stock_research_core.infrastructure.quality_evaluation.tutor_case_executor import TutorGroundedCaseExecutor

pytestmark = pytest.mark.integration


@pytest.fixture
def diversification_note(tmp_path: Path) -> Path:
    path = tmp_path / "diversification.md"
    path.write_text(
        "# Diversification\n\n"
        "Diversification is a risk-management strategy that mixes a variety of investments "
        "within a portfolio. It reduces reliance on any single asset, but it does not "
        "guarantee against losses.\n",
        encoding="utf-8",
    )
    return path


async def test_general_rag_case_executes_through_the_real_tutor_pipeline(uow_factory, diversification_note: Path) -> None:
    embedding_provider = DeterministicFakeEmbeddingAdapter()
    ingestion_service = KnowledgeIngestionService(
        unit_of_work_factory=uow_factory, chunker=HeadingAwareWordChunker(), embedding_provider=embedding_provider
    )
    await ingestion_service.ingest_local_document(
        file_path=diversification_note, source_title=f"QE Executor Test Notes {uuid4()}",
        approval_status=KnowledgeApprovalStatus.APPROVED, skill_ids=[], available_at=datetime.now(timezone.utc),
    )

    retriever = HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)
    tutor_service = GroundedAITutorService(
        unit_of_work_factory=uow_factory, retriever=retriever, tutor_model=DeterministicExtractiveTutor(),
        guardrail=RuleBasedTutorGuardrail(), prompt_builder=GroundedTutorPromptBuilder(),
    )
    async with uow_factory() as uow:
        eval_learner = await uow.learners.create(LearnerProfile(display_name="Quality Evaluation Fixture Learner"))
        await uow.commit()

    executor = TutorGroundedCaseExecutor(
        tutor_service=tutor_service, unit_of_work_factory=uow_factory, evaluation_learner_id=eval_learner.learner_id,
    )
    case_input = EvaluationCaseExecutionInput(
        case_id=uuid4(), context_type=EvaluationCaseContextType.GENERAL_RAG, user_input="What is diversification?",
    )
    result = await executor.execute_general_rag(case_input)

    assert result.generated_response is not None
    assert "diversif" in result.generated_response.lower()
    assert len(result.retrieved_context_ids) >= 1
    assert len(result.citation_chunk_ids) >= 1
    assert set(result.citation_chunk_ids) <= set(result.retrieved_context_ids)
    assert result.observed_guardrail_category == TutorRequestCategory.ALLOWED_EDUCATION

    # The evaluation conversation must never linger as part of the
    # fixture learner's active history.
    async with uow_factory() as uow:
        active_conversations = await uow.tutor_conversations.list_active_conversations_for_learner(eval_learner.learner_id)
    assert active_conversations == []


async def test_refusal_case_is_observed_correctly(uow_factory) -> None:
    embedding_provider = DeterministicFakeEmbeddingAdapter()
    retriever = HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)
    tutor_service = GroundedAITutorService(
        unit_of_work_factory=uow_factory, retriever=retriever, tutor_model=DeterministicExtractiveTutor(),
        guardrail=RuleBasedTutorGuardrail(), prompt_builder=GroundedTutorPromptBuilder(),
    )
    async with uow_factory() as uow:
        eval_learner = await uow.learners.create(LearnerProfile(display_name="Quality Evaluation Fixture Learner 2"))
        await uow.commit()

    executor = TutorGroundedCaseExecutor(
        tutor_service=tutor_service, unit_of_work_factory=uow_factory, evaluation_learner_id=eval_learner.learner_id,
    )
    case_input = EvaluationCaseExecutionInput(
        case_id=uuid4(), context_type=EvaluationCaseContextType.GENERAL_RAG, user_input="Should I buy NVDA right now?",
    )
    result = await executor.execute_general_rag(case_input)
    assert result.observed_guardrail_category == TutorRequestCategory.BUY_SELL_REQUEST
    assert result.citation_chunk_ids == []
