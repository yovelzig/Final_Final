"""Route-specific subgraph handlers for the `finquest-learning-coach`
graph - one per `LearningOrchestratorRoute` branch (spec section 14).

Each handler is a single bounded-responsibility, independently testable
async function reusing an *exact* existing FinQuest service - never a
reimplementation of RAG, grading, mastery, or portfolio-formula logic.
Tutor-backed handlers share `_tutor_response_to_state`, which converts a
`TutorResponse` into the graph state's learner-safe shape (citations,
grounding status, no raw chunk content beyond what the tutor already
returns as a citation excerpt).

`propose_practice_session` / `propose_diagnostic_assessment` do not call
any FinQuest service directly - they only assemble the *proposal* that
`GraphNodes.build_action_proposal` persists and
`GraphNodes.approval_interrupt` pauses on; the actual
`AdaptiveLearningService.start_session` / `.start_diagnostic` calls only
happen once a learner has approved, inside `AllowlistedLearningActionExecutor`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.ai_tutor.models import TutorContext, TutorResponse
from stock_research_core.application.ai_tutor.portfolio_tutor import PortfolioTutorService
from stock_research_core.application.ai_tutor.lesson_tutor import LessonTutorService
from stock_research_core.application.ai_tutor.scenario_tutor import ScenarioTutorService
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.learning_orchestrator.ports import LearningContextLoaderPort
from stock_research_core.application.learning_orchestrator.state import LearningCoachGraphState, bounded_list
from stock_research_core.domain.adaptive_learning.enums import LearningSessionType
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import LearningActionType

_MAX_STRUCTURED_LIST_ITEMS = 10


class MissingContextReferenceError(StockResearchError):
    """A route required a `context_references` key that was not present
    - this should never happen once `RuleBasedLearningIntentClassifier`'s
    `requires_context_key` rules run, but subgraphs check defensively
    rather than trust upstream state blindly."""


@dataclass(frozen=True)
class SubgraphDependencies:
    tutor_service: GroundedAITutorService
    lesson_tutor_service: LessonTutorService
    scenario_tutor_service: ScenarioTutorService
    portfolio_tutor_service: PortfolioTutorService
    adaptive_learning_service: AdaptiveLearningService
    context_loader: LearningContextLoaderPort


def _tutor_response_to_state(response: TutorResponse, *, conversation_id: UUID) -> dict[str, Any]:
    citations = [
        {
            "citation_number": citation.citation_number, "source_title": citation.source_title,
            "document_title": citation.document_title, "heading_path": list(citation.heading_path),
            "excerpt": citation.excerpt,
        }
        for citation in response.citations
    ]
    return {
        "tutor_conversation_id": str(conversation_id),
        "citations": citations,
        "final_response": {
            "answer_markdown": response.answer.answer_markdown, "citations": citations,
            "grounding_status": response.answer.grounding_status.value, "navigation_target": None,
        },
    }


def _require_reference(state: LearningCoachGraphState, key: str) -> UUID:
    references = state.get("context_references", {})
    if key not in references:
        raise MissingContextReferenceError(f"Route requires context reference '{key}' but it was not provided.")
    return UUID(references[key])


class Subgraphs:
    """Bound subgraph handlers sharing one set of injected tutor/adaptive
    service dependencies, constructed once alongside `GraphNodes`."""

    def __init__(self, deps: SubgraphDependencies) -> None:
        self._deps = deps

    # -- 14.1 grounded explanation / general tutor chat -----------------------------------------------

    async def grounded_explanation(self, state: LearningCoachGraphState) -> dict[str, Any]:
        learner_id = UUID(state["learner_id"])
        existing_conversation_id = state.get("tutor_conversation_id")
        if existing_conversation_id:
            conversation_id = UUID(existing_conversation_id)
        else:
            context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner_id)
            conversation = await self._deps.tutor_service.create_conversation(learner_id=learner_id, context=context)
            conversation_id = conversation.conversation_id
        response = await self._deps.tutor_service.ask(conversation_id=conversation_id, question=state["user_input"])
        return _tutor_response_to_state(response, conversation_id=conversation_id)

    # -- 14.2 lesson tutor -----------------------------------------------

    async def lesson_tutor(self, state: LearningCoachGraphState) -> dict[str, Any]:
        learner_id = UUID(state["learner_id"])
        existing_conversation_id = state.get("tutor_conversation_id")
        if existing_conversation_id:
            conversation_id = UUID(existing_conversation_id)
        else:
            lesson_id = _require_reference(state, "lesson_id")
            conversation = await self._deps.lesson_tutor_service.create_lesson_conversation(
                learner_id=learner_id, lesson_id=lesson_id
            )
            conversation_id = conversation.conversation_id
        response = await self._deps.lesson_tutor_service.ask(
            conversation_id=conversation_id, question=state["user_input"]
        )
        return _tutor_response_to_state(response, conversation_id=conversation_id)

    # -- 14.3 exercise tutor -----------------------------------------------

    async def exercise_tutor(self, state: LearningCoachGraphState) -> dict[str, Any]:
        learner_id = UUID(state["learner_id"])
        exercise_metadata = state.get("exercise_metadata") or {}
        exercise_submitted = bool(exercise_metadata.get("submitted", False))
        existing_conversation_id = state.get("tutor_conversation_id")
        if existing_conversation_id:
            conversation_id = UUID(existing_conversation_id)
        else:
            exercise_id = _require_reference(state, "exercise_id")
            conversation = await self._deps.lesson_tutor_service.create_exercise_help_conversation(
                learner_id=learner_id, exercise_id=exercise_id
            )
            conversation_id = conversation.conversation_id
        response = await self._deps.lesson_tutor_service.ask(
            conversation_id=conversation_id, question=state["user_input"], exercise_submitted=exercise_submitted
        )
        return _tutor_response_to_state(response, conversation_id=conversation_id)

    # -- 14.4 progress reflection -----------------------------------------------

    async def progress_reflection(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Loads a bounded, sanitized snapshot of the learner's own
        dashboard/mastery/progress/misconceptions/due-reviews, then uses
        the grounded tutor purely for the *prose* explanation of that
        already-computed data - it never invents a number, and it never
        recommends a specific security, allocation, or trade."""
        learner_id = UUID(state["learner_id"])
        loader = self._deps.context_loader
        dashboard = await loader.load_dashboard(learner_id)
        mastery_summary = bounded_list(await loader.load_mastery_summary(learner_id), max_items=_MAX_STRUCTURED_LIST_ITEMS)
        progress_summary = bounded_list(await loader.load_progress_summary(learner_id), max_items=_MAX_STRUCTURED_LIST_ITEMS)
        active_misconceptions = bounded_list(
            await loader.load_active_misconceptions(learner_id), max_items=_MAX_STRUCTURED_LIST_ITEMS
        )
        due_review_summary = bounded_list(
            await loader.load_due_review_summary(learner_id), max_items=_MAX_STRUCTURED_LIST_ITEMS
        )

        structured_context = {
            "dashboard": dashboard, "mastery_summary": mastery_summary, "progress_summary": progress_summary,
            "active_misconceptions": active_misconceptions, "due_review_summary": due_review_summary,
        }

        existing_conversation_id = state.get("tutor_conversation_id")
        if existing_conversation_id:
            conversation_id = UUID(existing_conversation_id)
        else:
            context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner_id)
            conversation = await self._deps.tutor_service.create_conversation(learner_id=learner_id, context=context)
            conversation_id = conversation.conversation_id

        response = await self._deps.tutor_service.ask(
            conversation_id=conversation_id, question=state["user_input"],
            context=TutorContext(
                context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner_id,
                structured_context=structured_context,
            ),
        )
        result = _tutor_response_to_state(response, conversation_id=conversation_id)
        result.update(
            {
                "learner_dashboard": dashboard, "mastery_summary": mastery_summary,
                "progress_summary": progress_summary, "active_misconceptions": active_misconceptions,
                "due_review_summary": due_review_summary,
            }
        )
        return result

    # -- 14.5 adaptive recommendation (explanatory only - starting a session is a separate, approved action) --------

    async def adaptive_recommendation(self, state: LearningCoachGraphState) -> dict[str, Any]:
        learner_id = UUID(state["learner_id"])
        dashboard = await self._deps.context_loader.load_dashboard(learner_id)
        due_review_summary = bounded_list(
            await self._deps.context_loader.load_due_review_summary(learner_id), max_items=_MAX_STRUCTURED_LIST_ITEMS
        )
        structured_context = {"dashboard": dashboard, "due_review_summary": due_review_summary}

        existing_conversation_id = state.get("tutor_conversation_id")
        if existing_conversation_id:
            conversation_id = UUID(existing_conversation_id)
        else:
            context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner_id)
            conversation = await self._deps.tutor_service.create_conversation(learner_id=learner_id, context=context)
            conversation_id = conversation.conversation_id

        response = await self._deps.tutor_service.ask(
            conversation_id=conversation_id, question=state["user_input"],
            context=TutorContext(
                context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner_id,
                structured_context=structured_context,
            ),
        )
        result = _tutor_response_to_state(response, conversation_id=conversation_id)
        result["learner_dashboard"] = dashboard
        result["due_review_summary"] = due_review_summary
        return result

    # -- 14.6 practice action (proposal only - execution happens after approval) -----------------------------------

    async def propose_practice_session(self, state: LearningCoachGraphState) -> dict[str, Any]:
        return {
            "proposed_action": {
                "action_type": LearningActionType.START_ADAPTIVE_SESSION.value,
                "title": "Start a daily practice session",
                "description": "Begin an adaptive daily-practice session tailored to your current mastery.",
                "reason": "You asked to start practicing.",
                "parameters": {"session_type": LearningSessionType.DAILY_PRACTICE.value, "goal_minutes": None},
            }
        }

    # -- 14.6b diagnostic action (proposal only) -----------------------------------------------

    async def propose_diagnostic_assessment(self, state: LearningCoachGraphState) -> dict[str, Any]:
        return {
            "proposed_action": {
                "action_type": LearningActionType.START_DIAGNOSTIC_ASSESSMENT.value,
                "title": "Start a diagnostic assessment",
                "description": "Begin a short diagnostic assessment to measure your current skill levels.",
                "reason": "You asked to take a diagnostic assessment.",
                "parameters": {"skill_ids": [], "maximum_items": 10},
            }
        }

    # -- 14.7 scenario tutor (before decision) -----------------------------------------------

    async def scenario_before_tutor(self, state: LearningCoachGraphState) -> dict[str, Any]:
        learner_id = UUID(state["learner_id"])
        existing_conversation_id = state.get("tutor_conversation_id")
        if existing_conversation_id:
            conversation_id = UUID(existing_conversation_id)
        else:
            scenario_id = _require_reference(state, "scenario_id")
            submission_id = _require_reference(state, "scenario_submission_id")
            conversation = await self._deps.scenario_tutor_service.create_before_decision_conversation(
                learner_id=learner_id, scenario_id=scenario_id, submission_id=submission_id
            )
            conversation_id = conversation.conversation_id
        response = await self._deps.scenario_tutor_service.ask(
            conversation_id=conversation_id, question=state["user_input"]
        )
        return _tutor_response_to_state(response, conversation_id=conversation_id)

    # -- 14.8 scenario tutor (after reveal) -----------------------------------------------

    async def scenario_after_tutor(self, state: LearningCoachGraphState) -> dict[str, Any]:
        learner_id = UUID(state["learner_id"])
        existing_conversation_id = state.get("tutor_conversation_id")
        if existing_conversation_id:
            conversation_id = UUID(existing_conversation_id)
        else:
            submission_id = _require_reference(state, "scenario_submission_id")
            conversation = await self._deps.scenario_tutor_service.create_after_reveal_conversation(
                learner_id=learner_id, submission_id=submission_id
            )
            conversation_id = conversation.conversation_id
        response = await self._deps.scenario_tutor_service.ask(
            conversation_id=conversation_id, question=state["user_input"]
        )
        return _tutor_response_to_state(response, conversation_id=conversation_id)

    # -- 14.9 portfolio tutor -----------------------------------------------

    async def portfolio_tutor(self, state: LearningCoachGraphState) -> dict[str, Any]:
        learner_id = UUID(state["learner_id"])
        existing_conversation_id = state.get("tutor_conversation_id")
        if existing_conversation_id:
            conversation_id = UUID(existing_conversation_id)
        else:
            portfolio_id = _require_reference(state, "portfolio_id")
            conversation = await self._deps.portfolio_tutor_service.create_portfolio_conversation(
                learner_id=learner_id, portfolio_id=portfolio_id
            )
            conversation_id = conversation.conversation_id
        response = await self._deps.portfolio_tutor_service.ask(
            conversation_id=conversation_id, question=state["user_input"]
        )
        return _tutor_response_to_state(response, conversation_id=conversation_id)
