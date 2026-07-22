"""PostgreSQL integration tests for `SqlAlchemyConversationRepository`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stock_research_core.domain.ai_tutor.enums import TutorContextType, TutorConversationStatus, TutorMessageRole
from stock_research_core.domain.ai_tutor.models import TutorConversation, TutorMessage
from stock_research_core.domain.learning.models import LearnerProfile

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_learner(uow_factory) -> LearnerProfile:
    learner = LearnerProfile(display_name="Tutor Test Learner")
    async with uow_factory() as uow:
        stored = await uow.learners.create(learner)
        await uow.commit()
    return stored


async def test_create_and_get_conversation(uow_factory) -> None:
    learner = await _seed_learner(uow_factory)
    conversation = TutorConversation(learner_id=learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
    async with uow_factory() as uow:
        created = await uow.tutor_conversations.create_conversation(conversation)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.tutor_conversations.get_conversation(created.conversation_id)
    assert fetched is not None
    assert fetched.status == TutorConversationStatus.ACTIVE


async def test_list_active_conversations_for_learner(uow_factory) -> None:
    learner = await _seed_learner(uow_factory)
    active = TutorConversation(learner_id=learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
    async with uow_factory() as uow:
        await uow.tutor_conversations.create_conversation(active)
        await uow.commit()

    async with uow_factory() as uow:
        closed = await uow.tutor_conversations.close_conversation(active.conversation_id, closed_at=NOW)
        await uow.commit()
    assert closed.status == TutorConversationStatus.CLOSED

    another_active = TutorConversation(learner_id=learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
    async with uow_factory() as uow:
        await uow.tutor_conversations.create_conversation(another_active)
        await uow.commit()

    async with uow_factory() as uow:
        active_conversations = await uow.tutor_conversations.list_active_conversations_for_learner(learner.learner_id)
    assert {c.conversation_id for c in active_conversations} == {another_active.conversation_id}


async def test_messages_are_immutable_and_ordered(uow_factory) -> None:
    learner = await _seed_learner(uow_factory)
    conversation = TutorConversation(learner_id=learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
    async with uow_factory() as uow:
        await uow.tutor_conversations.create_conversation(conversation)
        await uow.tutor_conversations.add_message(
            TutorMessage(conversation_id=conversation.conversation_id, role=TutorMessageRole.USER, content="first")
        )
        await uow.tutor_conversations.add_message(
            TutorMessage(conversation_id=conversation.conversation_id, role=TutorMessageRole.ASSISTANT, content="second")
        )
        await uow.commit()

    async with uow_factory() as uow:
        messages = await uow.tutor_conversations.list_recent_messages(conversation.conversation_id, limit=10)
    assert [m.content for m in messages] == ["first", "second"]


async def test_list_recent_messages_respects_limit(uow_factory) -> None:
    learner = await _seed_learner(uow_factory)
    conversation = TutorConversation(learner_id=learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
    async with uow_factory() as uow:
        await uow.tutor_conversations.create_conversation(conversation)
        for i in range(5):
            await uow.tutor_conversations.add_message(
                TutorMessage(
                    conversation_id=conversation.conversation_id, role=TutorMessageRole.USER, content=f"msg-{i}"
                )
            )
        await uow.commit()

    async with uow_factory() as uow:
        messages = await uow.tutor_conversations.list_recent_messages(conversation.conversation_id, limit=2)
    assert [m.content for m in messages] == ["msg-3", "msg-4"]
