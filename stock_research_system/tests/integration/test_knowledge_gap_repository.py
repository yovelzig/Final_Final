"""PostgreSQL integration tests for `SqlAlchemyKnowledgeGapRepository`."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.ai_tutor.enums import TutorContextType, TutorMessageRole
from stock_research_core.domain.ai_tutor.models import TutorConversation, TutorKnowledgeGap, TutorMessage
from stock_research_core.domain.learning.enums import DifficultyLevel, FinancialSkillCategory
from stock_research_core.domain.learning.models import LearnerProfile, Skill

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_conversation_and_message(uow_factory):
    learner = LearnerProfile(display_name="Gap Test Learner")
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        conversation = await uow.tutor_conversations.create_conversation(
            TutorConversation(learner_id=stored_learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
        )
        message = await uow.tutor_conversations.add_message(
            TutorMessage(conversation_id=conversation.conversation_id, role=TutorMessageRole.USER, content="q")
        )
        await uow.commit()
    return stored_learner, conversation, message


async def test_upsert_and_get_by_question_and_context(uow_factory) -> None:
    learner, conversation, message = await _seed_conversation_and_message(uow_factory)
    gap = TutorKnowledgeGap(
        learner_id=learner.learner_id, conversation_id=conversation.conversation_id, message_id=message.message_id,
        normalized_question="what is a pizza recommendation", context_type=TutorContextType.GENERAL_EDUCATION,
        first_seen_at=NOW, last_seen_at=NOW,
    )
    async with uow_factory() as uow:
        saved = await uow.tutor_knowledge_gaps.upsert_gap(gap)
        await uow.commit()
    assert saved.occurrence_count == 1

    async with uow_factory() as uow:
        found = await uow.tutor_knowledge_gaps.get_by_question_and_context(
            "what is a pizza recommendation", TutorContextType.GENERAL_EDUCATION.value
        )
    assert found is not None
    assert found.gap_id == gap.gap_id


async def test_upsert_gap_increments_occurrence_count(uow_factory) -> None:
    learner, conversation, message = await _seed_conversation_and_message(uow_factory)
    gap = TutorKnowledgeGap(
        learner_id=learner.learner_id, conversation_id=conversation.conversation_id, message_id=message.message_id,
        normalized_question="repeated unanswerable question", context_type=TutorContextType.GENERAL_EDUCATION,
        first_seen_at=NOW, last_seen_at=NOW,
    )
    async with uow_factory() as uow:
        await uow.tutor_knowledge_gaps.upsert_gap(gap)
        await uow.commit()

    updated_gap = gap.model_copy(update={"occurrence_count": 2, "last_seen_at": NOW})
    async with uow_factory() as uow:
        saved = await uow.tutor_knowledge_gaps.upsert_gap(updated_gap)
        await uow.commit()
    assert saved.occurrence_count == 2


async def test_gap_with_skill_ids(uow_factory) -> None:
    learner, conversation, message = await _seed_conversation_and_message(uow_factory)
    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(
                code="GAP_TEST_SKILL", name="Skill", category=FinancialSkillCategory.MONEY_BASICS,
                description="d", difficulty=DifficultyLevel.BEGINNER,
            )
        )
        await uow.commit()

    gap = TutorKnowledgeGap(
        learner_id=learner.learner_id, conversation_id=conversation.conversation_id, message_id=message.message_id,
        normalized_question="skill-linked question", context_type=TutorContextType.GENERAL_EDUCATION,
        target_skill_ids=[skill.skill_id], first_seen_at=NOW, last_seen_at=NOW,
    )
    async with uow_factory() as uow:
        await uow.tutor_knowledge_gaps.upsert_gap(gap)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.tutor_knowledge_gaps.get_by_question_and_context(
            "skill-linked question", TutorContextType.GENERAL_EDUCATION.value
        )
    assert found.target_skill_ids == [skill.skill_id]


async def test_list_unresolved_and_resolve_gap(uow_factory) -> None:
    learner, conversation, message = await _seed_conversation_and_message(uow_factory)
    gap = TutorKnowledgeGap(
        learner_id=learner.learner_id, conversation_id=conversation.conversation_id, message_id=message.message_id,
        normalized_question="an unresolved gap", context_type=TutorContextType.GENERAL_EDUCATION,
        first_seen_at=NOW, last_seen_at=NOW,
    )
    async with uow_factory() as uow:
        await uow.tutor_knowledge_gaps.upsert_gap(gap)
        await uow.commit()

    async with uow_factory() as uow:
        unresolved = await uow.tutor_knowledge_gaps.list_unresolved_gaps(limit=50)
    assert gap.gap_id in {g.gap_id for g in unresolved}

    async with uow_factory() as uow:
        resolved = await uow.tutor_knowledge_gaps.resolve_gap(gap.gap_id, resolved_at=NOW, resolution_document_id=None)
        await uow.commit()
    assert resolved.resolved is True

    async with uow_factory() as uow:
        unresolved_after = await uow.tutor_knowledge_gaps.list_unresolved_gaps(limit=50)
    assert gap.gap_id not in {g.gap_id for g in unresolved_after}


async def test_count_repeated_gaps(uow_factory) -> None:
    learner, conversation, message = await _seed_conversation_and_message(uow_factory)
    gap = TutorKnowledgeGap(
        learner_id=learner.learner_id, conversation_id=conversation.conversation_id, message_id=message.message_id,
        normalized_question="a frequently repeated question", context_type=TutorContextType.GENERAL_EDUCATION,
        occurrence_count=3, first_seen_at=NOW, last_seen_at=NOW,
    )
    async with uow_factory() as uow:
        before = await uow.tutor_knowledge_gaps.count_repeated_gaps(minimum_occurrences=2)
        await uow.tutor_knowledge_gaps.upsert_gap(gap)
        await uow.commit()

    async with uow_factory() as uow:
        after = await uow.tutor_knowledge_gaps.count_repeated_gaps(minimum_occurrences=2)
    assert after == before + 1
