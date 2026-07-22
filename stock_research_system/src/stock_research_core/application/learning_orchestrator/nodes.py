"""The parent `finquest-learning-coach` graph's node functions.

Every node does exactly one bounded responsibility (per the Phase 12
topology) and returns only a partial state update - never raw ORM
objects, never a database session, never a secret. Route-specific
subgraph logic (grounded explanation, lesson/exercise/scenario/
portfolio tutoring, adaptive recommendation, practice/diagnostic
actions) lives in `subgraphs.py`; this module is the shared spine:
`initialize_run`, `load_authorized_context`, `evaluate_input_guardrail`,
`build_refusal_response`, `build_fallback_response`, `classify_intent`,
`select_route`, `approval_interrupt`, `execute_action`,
`validate_final_output`, `persist_final_result`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from langgraph.types import interrupt

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.learning_orchestrator.actions import (
    AllowlistedLearningActionExecutor,
    ForbiddenLearningActionError,
)
from stock_research_core.application.learning_orchestrator.ports import LearningContextLoaderPort, LearningIntentClassifierPort
from stock_research_core.application.learning_orchestrator.routing import select_route as pure_select_route
from stock_research_core.application.learning_orchestrator.state import (
    LearningCoachGraphState,
    bounded_list,
    bounded_text,
)
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.ai_tutor.enums import TutorContextType, TutorGuardrailAction, TutorMessageRole
from stock_research_core.domain.ai_tutor.models import TutorMessage
from stock_research_core.domain.learning_orchestrator.enums import (
    APPROVAL_REQUIRED_ACTION_TYPES,
    LearningActionProposalStatus,
    LearningActionType,
    LearningIntent,
    LearningOrchestratorEventType,
    LearningOrchestratorRoute,
)
from stock_research_core.domain.learning_orchestrator.models import LearningActionProposal, LearningOrchestratorEvent

_ROUTE_LABELS: dict[str, str] = {
    "load_authorized_context": "Loading your learning context",
    "evaluate_input_guardrail": "Checking your question",
    "classify_intent": "Understanding what you're asking",
    LearningOrchestratorRoute.GROUNDED_EXPLANATION.value: "Looking up approved FinQuest material",
    LearningOrchestratorRoute.LESSON_TUTOR.value: "Reviewing this lesson",
    LearningOrchestratorRoute.EXERCISE_TUTOR.value: "Reviewing this exercise",
    LearningOrchestratorRoute.PROGRESS_REFLECTION.value: "Reviewing your learning progress",
    LearningOrchestratorRoute.ADAPTIVE_RECOMMENDATION.value: "Finding what to study next",
    LearningOrchestratorRoute.PRACTICE_ACTION.value: "Preparing a practice session",
    LearningOrchestratorRoute.DIAGNOSTIC_ACTION.value: "Preparing a diagnostic assessment",
    LearningOrchestratorRoute.SCENARIO_BEFORE_TUTOR.value: "Reviewing the scenario so far",
    LearningOrchestratorRoute.SCENARIO_AFTER_TUTOR.value: "Reviewing the scenario outcome",
    LearningOrchestratorRoute.PORTFOLIO_TUTOR.value: "Reviewing your portfolio",
}

_ACTION_PARAMETER_BUILDERS_CONTEXT_KEY: dict[LearningActionType, str] = {
    LearningActionType.OPEN_LESSON: "lesson_id",
    LearningActionType.OPEN_SCENARIO: "scenario_id",
    LearningActionType.OPEN_PORTFOLIO: "portfolio_id",
}


class RunStepLimitExceededError(StockResearchError):
    """The run exceeded its configured `maximum_steps` - a safe, bounded
    failure, never an unbounded loop."""


class InputGuardrailRefusalError(StockResearchError):
    """Not raised in normal flow - used internally to short-circuit to
    `build_refusal_response`'s exact preserved refusal text."""


@dataclass(frozen=True)
class NodeDependencies:
    unit_of_work_factory: Callable[[], UnitOfWorkPort]
    intent_classifier: LearningIntentClassifierPort
    context_loader: LearningContextLoaderPort
    action_executor: AllowlistedLearningActionExecutor
    guardrail: RuleBasedTutorGuardrail
    clock: Callable[[], datetime]
    max_context_characters: int = 20_000
    max_state_list_items: int = 50


def stage_label(node_name: str) -> str:
    return _ROUTE_LABELS.get(node_name, node_name.replace("_", " ").title())


class GraphNodes:
    """Bound node methods sharing one set of injected dependencies -
    constructed once per worker/API process by `graph_builder.build_graph`,
    exactly like every other FinQuest application service."""

    def __init__(self, deps: NodeDependencies) -> None:
        self._deps = deps

    # -- shared helpers -----------------------------------------------

    async def _append_event(
        self, state: LearningCoachGraphState, *, event_type: LearningOrchestratorEventType, message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        run_id = UUID(state["run_id"])
        async with self._deps.unit_of_work_factory() as uow:
            sequence_number = await uow.learning_orchestrator_events.next_sequence_number(run_id)
            await uow.learning_orchestrator_events.append(
                LearningOrchestratorEvent(
                    run_id=run_id, thread_id=UUID(state["thread_id"]), event_type=event_type,
                    sequence_number=sequence_number, learner_message=message, metadata=metadata or {},
                )
            )
            await uow.commit()

    def _next_step(self, state: LearningCoachGraphState) -> int:
        step_count = state.get("step_count", 0) + 1
        maximum_steps = state.get("maximum_steps", 30)
        if step_count > maximum_steps:
            raise RunStepLimitExceededError(f"Run exceeded its maximum step limit of {maximum_steps}.")
        return step_count

    def _build_tutor_context(self, state: LearningCoachGraphState) -> TutorContext:
        context_type_value = state.get("requested_context_type") or TutorContextType.GENERAL_EDUCATION.value
        references = state.get("context_references", {})
        return TutorContext(
            context_type=TutorContextType(context_type_value), learner_id=UUID(state["learner_id"]),
            lesson_id=UUID(references["lesson_id"]) if "lesson_id" in references else None,
            exercise_id=UUID(references["exercise_id"]) if "exercise_id" in references else None,
            scenario_id=UUID(references["scenario_id"]) if "scenario_id" in references else None,
            scenario_submission_id=(
                UUID(references["scenario_submission_id"]) if "scenario_submission_id" in references else None
            ),
            portfolio_id=UUID(references["portfolio_id"]) if "portfolio_id" in references else None,
        )

    # -- spine nodes -----------------------------------------------

    async def initialize_run(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RUN_STARTED, message="Run started.",
        )
        return {"step_count": step_count}

    async def load_authorized_context(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        learner_id = UUID(state["learner_id"])
        references = state.get("context_references", {})
        loader = self._deps.context_loader
        result: dict[str, Any] = {"step_count": step_count}

        if "lesson_id" in references:
            result["lesson_metadata"] = await loader.load_lesson_metadata(
                learner_id=learner_id, lesson_id=UUID(references["lesson_id"])
            )
        if "exercise_id" in references:
            result["exercise_metadata"] = await loader.load_exercise_metadata(
                learner_id=learner_id, exercise_id=UUID(references["exercise_id"])
            )
        if "scenario_id" in references:
            submission_id = UUID(references["scenario_submission_id"]) if "scenario_submission_id" in references else None
            result["scenario_metadata"] = await loader.load_scenario_metadata(
                learner_id=learner_id, scenario_id=UUID(references["scenario_id"]), submission_id=submission_id,
            )
        if "portfolio_id" in references:
            result["portfolio_overview"] = await loader.load_portfolio_overview(
                learner_id=learner_id, portfolio_id=UUID(references["portfolio_id"])
            )

        await self._append_event(state, event_type=LearningOrchestratorEventType.CONTEXT_LOADING, message="Context loaded.")
        return result

    async def evaluate_input_guardrail(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        context = self._build_tutor_context(state)
        message = TutorMessage(
            conversation_id=uuid4(), role=TutorMessageRole.USER,
            content=bounded_text(state["user_input"], max_characters=self._deps.max_context_characters),
        )
        decision = self._deps.guardrail.evaluate_input(conversation_id=message.conversation_id, message=message, context=context)
        guardrail_result = {
            "action": decision.action.value, "request_category": decision.request_category.value,
            "matched_rule_codes": decision.matched_rule_codes, "safe_response_override": decision.safe_response_override,
        }
        return {"step_count": step_count, "guardrail_result": guardrail_result}

    async def build_refusal_response(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        guardrail_result = state.get("guardrail_result", {})
        message = guardrail_result.get("safe_response_override") or (
            "I can explain the concepts, risks, and educational examples, but I can’t tell you what to buy, "
            "sell, or personally invest in."
        )
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RUN_COMPLETED, message="Request refused (guardrail).",
        )
        return {
            "step_count": step_count, "selected_route": LearningOrchestratorRoute.REFUSAL.value,
            "final_response": {"answer_markdown": message, "citations": [], "grounding_status": "REFUSED"},
        }

    async def build_fallback_response(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        message = (
            "I don’t have enough approved FinQuest material to answer that reliably. Try asking about a "
            "specific financial-education concept, your progress, a lesson, an exercise, a scenario, or your "
            "portfolio."
        )
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RUN_COMPLETED, message="Request could not be classified.",
        )
        return {
            "step_count": step_count, "selected_route": LearningOrchestratorRoute.FALLBACK.value,
            "final_response": {"answer_markdown": message, "citations": [], "grounding_status": "INSUFFICIENT_EVIDENCE"},
        }

    async def classify_intent(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        references = {key: UUID(value) for key, value in state.get("context_references", {}).items()}
        classification = await self._deps.intent_classifier.classify(
            learner_id=UUID(state["learner_id"]), user_input=state["user_input"],
            context_type=TutorContextType(state.get("requested_context_type") or TutorContextType.GENERAL_EDUCATION.value),
            context_references=references,
        )
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.INTENT_CLASSIFIED,
            message=f"Classified as {classification.intent.value}.",
            metadata={"method": classification.method.value, "confidence": classification.confidence},
        )
        return {
            "step_count": step_count,
            "intent_classification": {
                "intent": classification.intent.value, "confidence": classification.confidence,
                "method": classification.method.value, "matched_rule_codes": classification.matched_rule_codes,
                "requires_grounded_tutor": classification.requires_grounded_tutor,
                "requires_action_approval": classification.requires_action_approval,
                "classifier_version": classification.classifier_version,
            },
        }

    async def select_route(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        intent_value = state.get("intent_classification", {}).get("intent", LearningIntent.UNKNOWN.value)
        scenario_metadata = state.get("scenario_metadata") or {}
        route = pure_select_route(
            intent=LearningIntent(intent_value), scenario_reveal_status=scenario_metadata.get("reveal_status"),
        )
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.ROUTE_SELECTED, message=f"Routed to {route.value}.",
        )
        return {"step_count": step_count, "selected_route": route.value}

    # -- action proposal / approval / execution -----------------------------------------------

    async def build_action_proposal(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Persists the durable `LearningActionProposal` a subgraph
        assembled (action type, title, description, reason, safe
        parameters) into `state["proposed_action"]`. Nothing here has
        executed the action yet - this only records that it was
        *proposed*, per spec ss15's `build_action_proposal -> persist ->
        approval_interrupt` sequence."""
        step_count = self._next_step(state)
        draft = state.get("proposed_action")
        if not draft:
            return {"step_count": step_count, "safe_errors": state.get("safe_errors", []) + ["No action was proposed."]}

        action_type = LearningActionType(draft["action_type"])
        idempotency_key = f"{state['run_id']}:{action_type.value}"
        async with self._deps.unit_of_work_factory() as uow:
            existing = await uow.learning_orchestrator_actions.get_by_idempotency_key(
                run_id=UUID(state["run_id"]), idempotency_key=idempotency_key
            )
            if existing is None:
                proposal = LearningActionProposal(
                    run_id=UUID(state["run_id"]), thread_id=UUID(state["thread_id"]),
                    learner_id=UUID(state["learner_id"]), action_type=action_type, title=draft["title"],
                    description=draft["description"], reason=draft["reason"], parameters=draft.get("parameters", {}),
                    idempotency_key=idempotency_key, expires_at=None,
                )
                existing = await uow.learning_orchestrator_actions.create(proposal)
                await uow.commit()

        await self._append_event(
            state, event_type=LearningOrchestratorEventType.ACTION_PROPOSED,
            message=f"Proposed action: {draft['title']}.",
        )
        return {
            "step_count": step_count,
            "proposed_action": {
                "proposal_id": str(existing.proposal_id), "action_type": action_type.value, "title": existing.title,
                "description": existing.description, "reason": existing.reason,
                "safe_parameters": existing.parameters, "expires_at": None,
            },
        }

    async def approval_interrupt(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Calls `interrupt()` *before* any mutating side effect - the
        proposal record itself is a durable *proposal*, not yet an
        executed action; nothing in `LearningActionType`'s allow-list has
        run yet when this pauses."""
        step_count = self._next_step(state)
        proposed_action = state.get("proposed_action")
        if not proposed_action:
            return {"step_count": step_count, "safe_errors": state.get("safe_errors", []) + ["No action was proposed."]}

        async with self._deps.unit_of_work_factory() as uow:
            proposal_id = UUID(proposed_action["proposal_id"])
            await uow.learning_orchestrator_actions.mark_waiting_for_approval(proposal_id)
            await uow.commit()
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.APPROVAL_REQUIRED,
            message="Waiting for learner approval.",
        )

        approval_request = {
            "proposal_id": proposed_action["proposal_id"], "title": proposed_action["title"],
            "description": proposed_action["description"], "reason": proposed_action["reason"],
            "safe_parameters": proposed_action.get("safe_parameters", {}), "expires_at": proposed_action.get("expires_at"),
        }
        resume_value = interrupt(approval_request)
        return {"step_count": step_count, "approval_result": resume_value}

    async def execute_action(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        approval_result = state.get("approval_result") or {}
        proposed_action = state.get("proposed_action") or {}
        decision = approval_result.get("decision")

        if decision != "APPROVE" and decision != "EDIT":
            await self._append_event(
                state, event_type=LearningOrchestratorEventType.ACTION_REJECTED, message="Action not approved.",
            )
            return {
                "step_count": step_count,
                "final_response": {
                    "answer_markdown": "No problem - I won't take that action. Let me know if you'd like something else.",
                    "citations": [], "grounding_status": "GROUNDED", "navigation_target": None,
                },
            }

        proposal_id = UUID(proposed_action["proposal_id"])
        async with self._deps.unit_of_work_factory() as uow:
            proposal = await uow.learning_orchestrator_actions.get_by_id(proposal_id)
            if proposal is None:
                raise ForbiddenLearningActionError(f"Proposal '{proposal_id}' no longer exists.")
            now = self._deps.clock()
            executing = await uow.learning_orchestrator_actions.mark_executing(proposal_id, executed_at=now)
            await uow.commit()

        await self._append_event(state, event_type=LearningOrchestratorEventType.ACTION_EXECUTING, message="Executing action.")
        try:
            result = await self._deps.action_executor.execute(learner_id=UUID(state["learner_id"]), proposal=executing)
        except Exception as exc:  # noqa: BLE001 - an action-execution failure must degrade gracefully, never crash the run
            async with self._deps.unit_of_work_factory() as uow:
                await uow.learning_orchestrator_actions.mark_failed(proposal_id, completed_at=self._deps.clock())
                await uow.commit()
            return {
                "step_count": step_count,
                "safe_errors": state.get("safe_errors", []) + [f"The action could not be completed: {type(exc).__name__}."],
                "final_response": {
                    "answer_markdown": "I couldn't complete that action. Please try again from the relevant page.",
                    "citations": [], "grounding_status": "GROUNDED", "navigation_target": None,
                },
            }

        async with self._deps.unit_of_work_factory() as uow:
            await uow.learning_orchestrator_actions.mark_succeeded(
                proposal_id, completed_at=self._deps.clock(), result_reference=result,
            )
            await uow.commit()
        await self._append_event(state, event_type=LearningOrchestratorEventType.ACTION_COMPLETED, message="Action completed.")

        return {
            "step_count": step_count, "action_result": result,
            "navigation_target": result.get("navigation_target"),
            "final_response": {
                "answer_markdown": f"Done - {proposed_action.get('title', 'the action')} is ready.",
                "citations": [], "grounding_status": "GROUNDED", "navigation_target": result.get("navigation_target"),
            },
        }

    # -- output validation and persistence -----------------------------------------------

    async def validate_final_output(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        final_response = dict(state.get("final_response") or {})
        citations = bounded_list(state.get("citations", []), max_items=self._deps.max_state_list_items)
        final_response.setdefault("citations", citations)
        final_response.setdefault("navigation_target", state.get("navigation_target"))

        for forbidden_key in ("prompt", "chain_of_thought", "reasoning", "raw_state"):
            final_response.pop(forbidden_key, None)

        return {"step_count": step_count, "final_response": final_response}

    async def persist_final_result(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RUN_COMPLETED, message="Run completed.",
        )
        return {"step_count": step_count}
