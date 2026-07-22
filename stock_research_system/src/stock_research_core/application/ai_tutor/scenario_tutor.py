"""`ScenarioTutorService`: point-in-time-safe tutor conversations for
historical market scenarios.

Composes `GroundedAITutorService` and reuses
`HistoricalMarketScenarioService` (`get_learner_view` /
`get_reveal`) for all scenario data - no scenario calculation or
grading is duplicated here. Before reveal, the tutor context's
`knowledge_cutoff_at` is pinned to `scenario.decision_at`, which the
retrieval layer and guardrail both enforce independently (defense in
depth): the retriever never returns chunks available after that cutoff,
and `RuleBasedTutorGuardrail.validate_output` scans the model's own
answer text for outcome-revealing language before it ever reaches the
learner.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from stock_research_core.application.ai_tutor.models import TutorContext, TutorResponse
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import (
    InvalidScenarioStateError,
    MarketScenarioNotFoundError,
    ScenarioSubmissionNotFoundError,
    TutorConversationNotFoundError,
)
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.ai_tutor.models import TutorConversation
from stock_research_core.domain.market_scenarios.enums import ScenarioRevealStatus
from stock_research_core.domain.models import utc_now

Clock = Callable[[], datetime]


class ScenarioTutorService:
    """Creates and drives lesson-adjacent tutor conversations for historical scenarios."""

    def __init__(
        self,
        *,
        tutor_service: GroundedAITutorService,
        unit_of_work_factory: Callable[[], Any],
        scenario_service: HistoricalMarketScenarioService,
        clock: Clock = utc_now,
    ) -> None:
        self._tutor_service = tutor_service
        self._unit_of_work_factory = unit_of_work_factory
        self._scenario_service = scenario_service
        self._clock = clock

    async def create_before_decision_conversation(
        self, *, learner_id: UUID, scenario_id: UUID, submission_id: UUID
    ) -> TutorConversation:
        async with self._unit_of_work_factory() as uow:
            scenario = await uow.market_scenarios.get(scenario_id)
            if scenario is None:
                raise MarketScenarioNotFoundError(f"No scenario found with id '{scenario_id}'.")
            submission = await uow.scenario_submissions.get(submission_id)
            if submission is None or submission.scenario_id != scenario_id:
                raise ScenarioSubmissionNotFoundError(
                    f"No submission '{submission_id}' found for scenario '{scenario_id}'."
                )

        context = TutorContext(
            context_type=TutorContextType.SCENARIO_BEFORE_DECISION,
            learner_id=learner_id,
            scenario_id=scenario_id,
            scenario_submission_id=submission_id,
            knowledge_cutoff_at=scenario.decision_at,
            target_skill_ids=list(dict.fromkeys([*scenario.primary_skill_ids, *scenario.secondary_skill_ids])),
        )
        return await self._tutor_service.create_conversation(learner_id=learner_id, context=context)

    async def create_after_reveal_conversation(self, *, learner_id: UUID, submission_id: UUID) -> TutorConversation:
        async with self._unit_of_work_factory() as uow:
            submission = await uow.scenario_submissions.get(submission_id)
            if submission is None:
                raise ScenarioSubmissionNotFoundError(f"No submission found with id '{submission_id}'.")
            if submission.reveal_status != ScenarioRevealStatus.REVEALED:
                raise InvalidScenarioStateError(
                    f"Submission '{submission_id}' has not been revealed yet; the after-reveal tutor "
                    "requires a REVEALED submission."
                )
            scenario = await uow.market_scenarios.get(submission.scenario_id)
            if scenario is None:
                raise MarketScenarioNotFoundError(f"No scenario found with id '{submission.scenario_id}'.")

        context = TutorContext(
            context_type=TutorContextType.SCENARIO_AFTER_REVEAL,
            learner_id=learner_id,
            scenario_id=scenario.scenario_id,
            scenario_submission_id=submission_id,
            target_skill_ids=list(dict.fromkeys([*scenario.primary_skill_ids, *scenario.secondary_skill_ids])),
        )
        return await self._tutor_service.create_conversation(learner_id=learner_id, context=context)

    async def ask(self, *, conversation_id: UUID, question: str, top_k: int = 8) -> TutorResponse:
        async with self._unit_of_work_factory() as uow:
            conversation = await uow.tutor_conversations.get_conversation(conversation_id)
        if conversation is None:
            raise TutorConversationNotFoundError(f"No tutor conversation found with id '{conversation_id}'.")

        if conversation.context_type == TutorContextType.SCENARIO_AFTER_REVEAL:
            structured_context, cutoff = await self._after_reveal_structured_context(conversation)
        else:
            structured_context, cutoff = await self._before_decision_structured_context(conversation)

        context = TutorContext(
            context_type=conversation.context_type,
            learner_id=conversation.learner_id,
            scenario_id=conversation.scenario_id,
            knowledge_cutoff_at=cutoff,
            structured_context=structured_context,
        )
        return await self._tutor_service.ask(conversation_id=conversation_id, question=question, top_k=top_k, context=context)

    async def _before_decision_structured_context(
        self, conversation: TutorConversation
    ) -> tuple[dict[str, Any], datetime]:
        assert conversation.scenario_id is not None
        view = await self._scenario_service.get_learner_view(
            learner_id=conversation.learner_id, scenario_id=conversation.scenario_id
        )
        structured_context = {
            "scenario_title": view.title,
            "scenario_type": view.scenario_type.value,
            "observation_start_at": view.observation_start_at.isoformat(),
            "decision_at": view.decision_at.isoformat(),
            "prompt": view.prompt,
            "learner_instructions": view.learner_instructions,
        }
        return structured_context, view.decision_at

    async def _after_reveal_structured_context(
        self, conversation: TutorConversation
    ) -> tuple[dict[str, Any], datetime | None]:
        assert conversation.scenario_id is not None
        async with self._unit_of_work_factory() as uow:
            submissions = await uow.scenario_submissions.list_for_learner(conversation.learner_id)
        revealed = [
            submission
            for submission in submissions
            if submission.scenario_id == conversation.scenario_id
            and submission.reveal_status == ScenarioRevealStatus.REVEALED
            and submission.revealed_at is not None
        ]
        if not revealed:
            raise InvalidScenarioStateError(
                f"No revealed submission found for scenario '{conversation.scenario_id}' and learner "
                f"'{conversation.learner_id}'."
            )
        latest = max(revealed, key=lambda submission: submission.revealed_at)
        reveal = await self._scenario_service.get_reveal(submission_id=latest.submission_id)
        structured_context = {
            "decision_quality": (
                reveal.submission.decision_quality.value if reveal.submission.decision_quality else None
            ),
            "decision_feedback": reveal.decision_feedback,
            "outcome_feedback": reveal.outcome_feedback,
            "combined_learning_summary": reveal.combined_learning_summary,
        }
        return structured_context, None
