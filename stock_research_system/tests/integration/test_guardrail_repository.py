"""PostgreSQL integration tests for `SqlAlchemyGuardrailRepository`."""

from __future__ import annotations

import pytest

from stock_research_core.domain.ai_tutor.enums import (
    TutorContextType,
    TutorGuardrailAction,
    TutorMessageRole,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import EXACT_ADVICE_REFUSAL, TutorConversation, TutorGuardrailDecision, TutorMessage
from stock_research_core.domain.learning.models import LearnerProfile

pytestmark = pytest.mark.integration


async def _seed_conversation_and_message(uow_factory):
    learner = LearnerProfile(display_name="Guardrail Test Learner")
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        conversation = await uow.tutor_conversations.create_conversation(
            TutorConversation(learner_id=stored_learner.learner_id, context_type=TutorContextType.GENERAL_EDUCATION)
        )
        message = await uow.tutor_conversations.add_message(
            TutorMessage(conversation_id=conversation.conversation_id, role=TutorMessageRole.USER, content="Should I buy NVDA?")
        )
        await uow.commit()
    return conversation, message


async def test_save_and_get_decision(uow_factory) -> None:
    conversation, message = await _seed_conversation_and_message(uow_factory)
    decision = TutorGuardrailDecision(
        conversation_id=conversation.conversation_id, message_id=message.message_id,
        request_category=TutorRequestCategory.BUY_SELL_REQUEST, action=TutorGuardrailAction.REFUSE,
        matched_rule_codes=["BUY_SELL_INSTRUCTION"], safe_response_override=EXACT_ADVICE_REFUSAL,
        policy_version="tutor-guardrail-v1",
    )
    async with uow_factory() as uow:
        saved = await uow.tutor_guardrails.save_decision(decision)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.tutor_guardrails.get_decision(saved.decision_id)
    assert fetched is not None
    assert fetched.matched_rule_codes == ["BUY_SELL_INSTRUCTION"]
    assert fetched.action == TutorGuardrailAction.REFUSE


async def test_list_decisions_for_conversation(uow_factory) -> None:
    conversation, message = await _seed_conversation_and_message(uow_factory)
    decision = TutorGuardrailDecision(
        conversation_id=conversation.conversation_id, message_id=message.message_id,
        request_category=TutorRequestCategory.ALLOWED_EDUCATION, action=TutorGuardrailAction.ALLOW,
        policy_version="tutor-guardrail-v1",
    )
    async with uow_factory() as uow:
        await uow.tutor_guardrails.save_decision(decision)
        await uow.commit()

    async with uow_factory() as uow:
        decisions = await uow.tutor_guardrails.list_decisions_for_conversation(conversation.conversation_id)
    assert len(decisions) == 1
    assert decisions[0].request_category == TutorRequestCategory.ALLOWED_EDUCATION
