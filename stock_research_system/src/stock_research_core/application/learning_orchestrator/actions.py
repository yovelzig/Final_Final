"""The explicit, closed action-execution allowlist -
`AllowlistedLearningActionExecutor`, satisfying `LearningActionExecutorPort`.

There is deliberately no code path here - not a branch, not a helper,
not a TODO - for a trade, a trade preview, a portfolio rebalance, market
ingestion, an operations job, an n8n workflow, or an admin action. The
six handlers below are the *entire* action surface; `execute()` raises
`ForbiddenLearningActionError` for anything else, including a
hypothetical future `LearningActionType` member that was added to the
enum but never wired to a handler here.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.ai_tutor.lesson_tutor import LessonTutorService
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.ai_tutor.portfolio_tutor import PortfolioTutorService
from stock_research_core.application.ai_tutor.scenario_tutor import ScenarioTutorService
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.learning_orchestrator.models import (
    CreateTutorConversationAction,
    OpenLessonAction,
    OpenPortfolioAction,
    OpenScenarioAction,
    StartAdaptiveSessionAction,
    StartDiagnosticAction,
)
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import LearningActionType
from stock_research_core.domain.learning_orchestrator.models import LearningActionProposal


class ForbiddenLearningActionError(StockResearchError):
    """An action type outside the closed learning-action allow-list was
    requested. This is a defensive, should-never-happen guard - proposal
    creation already validates `action_type` against the same enum."""


class LearningActionNotFoundError(StockResearchError):
    """A navigation action referenced a resource that does not exist or
    is not owned by the requesting learner."""


_NAVIGATION_TARGETS = {
    LearningActionType.START_ADAPTIVE_SESSION: "/practice",
    LearningActionType.START_DIAGNOSTIC_ASSESSMENT: "/diagnostic",
}


class AllowlistedLearningActionExecutor:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        adaptive_learning_service: AdaptiveLearningService,
        tutor_service: GroundedAITutorService,
        lesson_tutor_service: LessonTutorService,
        scenario_tutor_service: ScenarioTutorService,
        portfolio_tutor_service: PortfolioTutorService,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._adaptive_learning_service = adaptive_learning_service
        self._tutor_service = tutor_service
        self._lesson_tutor_service = lesson_tutor_service
        self._scenario_tutor_service = scenario_tutor_service
        self._portfolio_tutor_service = portfolio_tutor_service

        self._handlers: dict[
            LearningActionType, Callable[[UUID, LearningActionProposal], Coroutine[Any, Any, dict[str, Any]]]
        ] = {
            LearningActionType.START_ADAPTIVE_SESSION: self._start_adaptive_session,
            LearningActionType.START_DIAGNOSTIC_ASSESSMENT: self._start_diagnostic,
            LearningActionType.OPEN_LESSON: self._open_lesson,
            LearningActionType.OPEN_SCENARIO: self._open_scenario,
            LearningActionType.OPEN_PORTFOLIO: self._open_portfolio,
            LearningActionType.CREATE_TUTOR_CONVERSATION: self._create_tutor_conversation,
        }

    async def execute(self, *, learner_id: UUID, proposal: LearningActionProposal) -> dict[str, Any]:
        handler = self._handlers.get(proposal.action_type)
        if handler is None:
            raise ForbiddenLearningActionError(
                f"Action type {proposal.action_type.value} has no registered handler and cannot execute."
            )
        return await handler(learner_id, proposal)

    async def _start_adaptive_session(self, learner_id: UUID, proposal: LearningActionProposal) -> dict[str, Any]:
        params = StartAdaptiveSessionAction.model_validate(proposal.parameters)
        session = await self._adaptive_learning_service.start_session(
            learner_id=learner_id, session_type=params.session_type, goal_minutes=params.goal_minutes,
        )
        return {
            "session_id": str(session.session_id), "session_type": session.session_type.value,
            "goal_minutes": session.goal_minutes, "navigation_target": _NAVIGATION_TARGETS[proposal.action_type],
        }

    async def _start_diagnostic(self, learner_id: UUID, proposal: LearningActionProposal) -> dict[str, Any]:
        params = StartDiagnosticAction.model_validate(proposal.parameters)
        summary = await self._adaptive_learning_service.start_diagnostic(
            learner_id=learner_id, skill_ids=params.skill_ids, maximum_items=params.maximum_items,
        )
        return {
            "assessment_id": str(summary.assessment.assessment_id), "item_count": len(summary.items),
            "navigation_target": _NAVIGATION_TARGETS[proposal.action_type],
        }

    async def _open_lesson(self, learner_id: UUID, proposal: LearningActionProposal) -> dict[str, Any]:
        params = OpenLessonAction.model_validate(proposal.parameters)
        async with self._unit_of_work_factory() as uow:
            lesson = await uow.curriculum.get_lesson(params.lesson_id)
        if lesson is None:
            raise LearningActionNotFoundError(f"No lesson found with id '{params.lesson_id}'.")
        return {"lesson_id": str(lesson.lesson_id), "navigation_target": f"/lessons/{lesson.lesson_id}"}

    async def _open_scenario(self, learner_id: UUID, proposal: LearningActionProposal) -> dict[str, Any]:
        params = OpenScenarioAction.model_validate(proposal.parameters)
        async with self._unit_of_work_factory() as uow:
            scenario = await uow.market_scenarios.get(params.scenario_id)
        if scenario is None:
            raise LearningActionNotFoundError(f"No scenario found with id '{params.scenario_id}'.")
        return {"scenario_id": str(scenario.scenario_id), "navigation_target": f"/scenarios/{scenario.scenario_id}"}

    async def _open_portfolio(self, learner_id: UUID, proposal: LearningActionProposal) -> dict[str, Any]:
        params = OpenPortfolioAction.model_validate(proposal.parameters)
        async with self._unit_of_work_factory() as uow:
            portfolio = await uow.virtual_portfolios.get(params.portfolio_id)
        if portfolio is None or portfolio.learner_id != learner_id:
            raise LearningActionNotFoundError(f"No portfolio found with id '{params.portfolio_id}'.")
        return {"portfolio_id": str(portfolio.portfolio_id), "navigation_target": f"/portfolios/{portfolio.portfolio_id}"}

    async def _create_tutor_conversation(self, learner_id: UUID, proposal: LearningActionProposal) -> dict[str, Any]:
        params = CreateTutorConversationAction.model_validate(proposal.parameters)

        if params.context_type == TutorContextType.LESSON_HELP and params.lesson_id is not None:
            conversation = await self._lesson_tutor_service.create_lesson_conversation(
                learner_id=learner_id, lesson_id=params.lesson_id
            )
            navigation_target = f"/lessons/{params.lesson_id}"
        elif params.context_type == TutorContextType.EXERCISE_HELP and params.exercise_id is not None:
            conversation = await self._lesson_tutor_service.create_exercise_help_conversation(
                learner_id=learner_id, exercise_id=params.exercise_id
            )
            navigation_target = f"/tutor/{conversation.conversation_id}"
        elif params.context_type == TutorContextType.SCENARIO_BEFORE_DECISION and params.scenario_id is not None:
            submission_id = params.scenario_submission_id
            if submission_id is None:
                raise ForbiddenLearningActionError("SCENARIO_BEFORE_DECISION requires scenario_submission_id.")
            conversation = await self._scenario_tutor_service.create_before_decision_conversation(
                learner_id=learner_id, scenario_id=params.scenario_id, submission_id=submission_id,
            )
            navigation_target = f"/scenarios/{params.scenario_id}"
        elif params.context_type == TutorContextType.SCENARIO_AFTER_REVEAL and params.scenario_submission_id is not None:
            conversation = await self._scenario_tutor_service.create_after_reveal_conversation(
                learner_id=learner_id, submission_id=params.scenario_submission_id,
            )
            navigation_target = f"/scenarios/{params.scenario_id}" if params.scenario_id else "/scenarios"
        elif params.context_type == TutorContextType.PORTFOLIO_EXPLANATION and params.portfolio_id is not None:
            conversation = await self._portfolio_tutor_service.create_portfolio_conversation(
                learner_id=learner_id, portfolio_id=params.portfolio_id,
            )
            navigation_target = f"/portfolios/{params.portfolio_id}"
        else:
            conversation = await self._tutor_service.create_conversation(
                learner_id=learner_id, context=TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner_id),
            )
            navigation_target = f"/tutor/{conversation.conversation_id}"

        return {
            "conversation_id": str(conversation.conversation_id), "context_type": params.context_type.value,
            "navigation_target": navigation_target,
        }
