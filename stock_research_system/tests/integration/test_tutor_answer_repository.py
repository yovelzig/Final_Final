"""PostgreSQL integration tests for `SqlAlchemyTutorAnswerRepository`."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorAnswerStatus,
    TutorContextType,
    TutorGuardrailAction,
    TutorMessageRole,
    TutorProviderType,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    TutorAnswer,
    TutorCitation,
    TutorConversation,
    TutorGuardrailDecision,
    TutorMessage,
)
from stock_research_core.domain.learning.models import LearnerProfile

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_fixture(uow_factory):
    """A conversation, message, guardrail decision, and one knowledge chunk to cite."""
    learner = LearnerProfile(display_name="Answer Test Learner")
    content = "Diversification reduces reliance on a single asset."
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        conversation = await uow.tutor_conversations.create_conversation(
            TutorConversation(learner_id=stored_learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
        )
        message = await uow.tutor_conversations.add_message(
            TutorMessage(conversation_id=conversation.conversation_id, role=TutorMessageRole.USER, content="What is diversification?")
        )
        decision = await uow.tutor_guardrails.save_decision(
            TutorGuardrailDecision(
                conversation_id=conversation.conversation_id, message_id=message.message_id,
                request_category=TutorRequestCategory.ALLOWED_EDUCATION, action=TutorGuardrailAction.ALLOW,
                policy_version="tutor-guardrail-v1",
            )
        )
        source = await uow.knowledge.upsert_source(
            KnowledgeSource(
                source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Source",
                approval_status=KnowledgeApprovalStatus.APPROVED,
            )
        )
        document = await uow.knowledge.upsert_document(
            KnowledgeDocument(
                source_id=source.source_id, title="Doc", content_text=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(), status=KnowledgeDocumentStatus.PROCESSED,
                approval_status=KnowledgeApprovalStatus.APPROVED, available_at=NOW, parser_version="v1",
            )
        )
        [chunk] = await uow.knowledge.upsert_chunks(
            [
                KnowledgeChunk(
                    document_id=document.document_id, chunk_index=0, content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(), word_count=7,
                    estimated_token_count=9, available_at=NOW, chunking_version="heading-word-chunker-v1",
                )
            ]
        )
        await uow.commit()
    return conversation, message, decision, chunk


async def test_save_answer_and_citations(uow_factory) -> None:
    conversation, message, decision, chunk = await _seed_fixture(uow_factory)
    answer = TutorAnswer(
        conversation_id=conversation.conversation_id, request_message_id=message.message_id,
        status=TutorAnswerStatus.VALIDATED, provider_type=TutorProviderType.EXTRACTIVE,
        answer_markdown="Diversification reduces reliance on a single asset [1].",
        request_category=TutorRequestCategory.ALLOWED_EDUCATION, grounding_status=GroundingStatus.PARTIALLY_GROUNDED,
        guardrail_decision_id=decision.decision_id, tutor_policy_version="v1", prompt_version="v1",
        model_name="extractive-tutor-v1", validated_at=NOW,
    )
    async with uow_factory() as uow:
        saved_answer = await uow.tutor_answers.save_answer(answer)
        # `retrieval_run_id` requires a real row via a FK; leave it unset here
        # since this test focuses on the answer/citation relationship only.
        citation = TutorCitation(
            answer_id=saved_answer.answer_id, chunk_id=chunk.chunk_id, citation_number=1,
            quoted_excerpt="Diversification reduces reliance on a single asset.", source_title="Source",
            document_title="Doc", heading_path=[],
        )
        saved_citations = await uow.tutor_answers.save_citations([citation])
        await uow.commit()

    assert len(saved_citations) == 1

    async with uow_factory() as uow:
        fetched_answer = await uow.tutor_answers.get_answer(saved_answer.answer_id)
        fetched_citations = await uow.tutor_answers.list_citations_for_answer(saved_answer.answer_id)
    assert fetched_answer.grounding_status == GroundingStatus.PARTIALLY_GROUNDED
    assert len(fetched_citations) == 1
    assert fetched_citations[0].source_title == "Source"


async def test_update_validation_status(uow_factory) -> None:
    conversation, message, decision, _chunk = await _seed_fixture(uow_factory)
    answer = TutorAnswer(
        conversation_id=conversation.conversation_id, request_message_id=message.message_id,
        status=TutorAnswerStatus.GENERATED, provider_type=TutorProviderType.EXTRACTIVE,
        answer_markdown="Draft answer.", request_category=TutorRequestCategory.ALLOWED_EDUCATION,
        grounding_status=GroundingStatus.PARTIALLY_GROUNDED, guardrail_decision_id=decision.decision_id,
        tutor_policy_version="v1", prompt_version="v1", model_name="extractive-tutor-v1",
    )
    async with uow_factory() as uow:
        saved = await uow.tutor_answers.save_answer(answer)
        await uow.commit()

    async with uow_factory() as uow:
        updated = await uow.tutor_answers.update_validation_status(
            saved.answer_id, status=TutorAnswerStatus.VALIDATED,
            grounding_status=GroundingStatus.PARTIALLY_GROUNDED, validated_at=NOW,
        )
        await uow.commit()
    assert updated.status == TutorAnswerStatus.VALIDATED
    assert updated.validated_at == NOW


async def test_list_answers_for_conversation(uow_factory) -> None:
    conversation, message, decision, _chunk = await _seed_fixture(uow_factory)
    answer = TutorAnswer(
        conversation_id=conversation.conversation_id, request_message_id=message.message_id,
        status=TutorAnswerStatus.GENERATED, provider_type=TutorProviderType.EXTRACTIVE,
        answer_markdown="Answer.", request_category=TutorRequestCategory.ALLOWED_EDUCATION,
        grounding_status=GroundingStatus.PARTIALLY_GROUNDED, guardrail_decision_id=decision.decision_id,
        tutor_policy_version="v1", prompt_version="v1", model_name="extractive-tutor-v1",
    )
    async with uow_factory() as uow:
        await uow.tutor_answers.save_answer(answer)
        await uow.commit()

    async with uow_factory() as uow:
        answers = await uow.tutor_answers.list_answers_for_conversation(conversation.conversation_id)
    assert len(answers) == 1
