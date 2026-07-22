"""Point-in-time safety tests for historical-scenario tutor conversations.

Before a scenario is revealed, the tutor must never leak future
information: the domain model pins `knowledge_cutoff_at` to the
scenario's `decision_at`, the guardrail refuses direct
future-information questions, and `validate_output` scans the model's
own answer text for outcome-revealing language as a second, independent
line of defense. No SQLAlchemy or PostgreSQL is used here - this
exercises only the domain/application layers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.domain.ai_tutor.enums import GroundingStatus, TutorContextType, TutorGuardrailAction
from stock_research_core.domain.ai_tutor.models import (
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
    TutorConversation,
    TutorMessage,
)
from stock_research_core.domain.ai_tutor.enums import TutorMessageRole

DECISION_AT = datetime(2024, 6, 1, tzinfo=timezone.utc)


class TestScenarioBeforeDecisionRequiresCutoff:
    def test_conversation_creation_requires_knowledge_cutoff(self) -> None:
        with pytest.raises(ValidationError):
            TutorConversation(
                learner_id=uuid4(), context_type=TutorContextType.SCENARIO_BEFORE_DECISION, scenario_id=uuid4(),
            )

    def test_conversation_creation_accepts_decision_at_as_cutoff(self) -> None:
        conversation = TutorConversation(
            learner_id=uuid4(), context_type=TutorContextType.SCENARIO_BEFORE_DECISION, scenario_id=uuid4(),
            knowledge_cutoff_at=DECISION_AT,
        )
        assert conversation.knowledge_cutoff_at == DECISION_AT


class TestScenarioLeakageGuardrail:
    def _context(self) -> TutorContext:
        return TutorContext(
            context_type=TutorContextType.SCENARIO_BEFORE_DECISION, learner_id=uuid4(), scenario_id=uuid4(),
            knowledge_cutoff_at=DECISION_AT,
        )

    @pytest.mark.parametrize(
        "question",
        [
            "What happens next?",
            "Does the stock rise?",
            "Which option is correct?",
            "What is the outcome?",
            "Did the trade work out?",
        ],
    )
    def test_direct_future_information_requests_are_refused(self, question: str) -> None:
        guardrail = RuleBasedTutorGuardrail()
        context = self._context()
        message = TutorMessage(conversation_id=uuid4(), role=TutorMessageRole.USER, content=question)
        decision = guardrail.evaluate_input(conversation_id=message.conversation_id, message=message, context=context)
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.safe_response_override == EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL

    def test_educational_questions_within_scenario_context_are_allowed(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        context = self._context()
        message = TutorMessage(
            conversation_id=uuid4(), role=TutorMessageRole.USER,
            content="What risks should I consider before making this decision?",
        )
        decision = guardrail.evaluate_input(conversation_id=message.conversation_id, message=message, context=context)
        assert decision.action == TutorGuardrailAction.ALLOW

    def test_after_reveal_context_does_not_trigger_before_decision_refusal(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        context = TutorContext(
            context_type=TutorContextType.SCENARIO_AFTER_REVEAL, learner_id=uuid4(), scenario_id=uuid4()
        )
        message = TutorMessage(conversation_id=uuid4(), role=TutorMessageRole.USER, content="What was the outcome?")
        decision = guardrail.evaluate_input(conversation_id=message.conversation_id, message=message, context=context)
        assert decision.matched_rule_codes != ["SCENARIO_FUTURE_INFORMATION_REQUEST"]


class TestScenarioOutputLeakageValidation:
    def test_answer_text_revealing_outcome_before_reveal_is_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        context = TutorContext(
            context_type=TutorContextType.SCENARIO_BEFORE_DECISION, learner_id=uuid4(), scenario_id=uuid4(),
            knowledge_cutoff_at=DECISION_AT,
        )
        status, issues = guardrail.validate_output(
            answer_text="In hindsight, the stock rose sharply after the decision point.",
            cited_chunk_ids=[], retrieved_candidates=[], context=context,
        )
        assert "SCENARIO_FUTURE_INFORMATION_LEAK" in issues
        assert status != GroundingStatus.GROUNDED

    def test_same_answer_text_not_flagged_after_reveal(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        context = TutorContext(
            context_type=TutorContextType.SCENARIO_AFTER_REVEAL, learner_id=uuid4(), scenario_id=uuid4()
        )
        _status, issues = guardrail.validate_output(
            answer_text="In hindsight, the stock rose sharply after the decision point.",
            cited_chunk_ids=[], retrieved_candidates=[], context=context,
        )
        assert "SCENARIO_FUTURE_INFORMATION_LEAK" not in issues

    def test_safe_educational_answer_not_flagged_before_reveal(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        context = TutorContext(
            context_type=TutorContextType.SCENARIO_BEFORE_DECISION, learner_id=uuid4(), scenario_id=uuid4(),
            knowledge_cutoff_at=DECISION_AT,
        )
        _status, issues = guardrail.validate_output(
            answer_text="Diversification can reduce reliance on a single holding's performance.",
            cited_chunk_ids=[], retrieved_candidates=[], context=context,
        )
        assert "SCENARIO_FUTURE_INFORMATION_LEAK" not in issues
