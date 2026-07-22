"""Unit tests for individual `GraphNodes` methods (spec section 13) -
each node exercised directly, without a compiled graph. Interrupt/
resume behavior (which requires a running graph) is covered separately
in `test_orchestrator_interrupts.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier
from stock_research_core.application.learning_orchestrator.nodes import (
    GraphNodes,
    NodeDependencies,
    RunStepLimitExceededError,
)
from stock_research_core.application.learning_orchestrator.state import new_state
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRoute

from tests.unit.learning_orchestrator_fakes import FakeActionRepo, FakeEventRepo, FakeUnitOfWork

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _uow_factory():
    uow = FakeUnitOfWork()
    return lambda: uow


def _nodes(*, uow_factory=None, context_loader=None, action_executor=None) -> GraphNodes:
    deps = NodeDependencies(
        unit_of_work_factory=uow_factory or _uow_factory(),
        intent_classifier=RuleBasedLearningIntentClassifier(),
        context_loader=context_loader,
        action_executor=action_executor,
        guardrail=RuleBasedTutorGuardrail(),
        clock=lambda: NOW,
    )
    return GraphNodes(deps)


def _state(user_input: str, **overrides):
    state = new_state(
        thread_id=str(uuid4()), run_id=str(uuid4()), learner_id=str(uuid4()), correlation_id=str(uuid4()),
        graph_version="learning-coach-graph-v1", user_input=user_input, requested_context_type="GENERAL_EDUCATION",
    )
    state.update(overrides)
    return state


async def test_initialize_run_increments_step_count() -> None:
    nodes = _nodes()
    result = await nodes.initialize_run(_state("hello"))
    assert result["step_count"] == 1


async def test_step_limit_is_enforced() -> None:
    nodes = _nodes()
    state = _state("hello", step_count=30, maximum_steps=30)
    with pytest.raises(RunStepLimitExceededError):
        await nodes.initialize_run(state)


async def test_evaluate_input_guardrail_refuses_buy_sell_requests() -> None:
    nodes = _nodes()
    state = _state("should I buy Apple stock right now?")
    result = await nodes.evaluate_input_guardrail(state)
    assert result["guardrail_result"]["action"] == "REFUSE"


async def test_evaluate_input_guardrail_allows_educational_questions() -> None:
    nodes = _nodes()
    state = _state("what is diversification and why does it matter for my portfolio")
    result = await nodes.evaluate_input_guardrail(state)
    assert result["guardrail_result"]["action"] == "ALLOW"


async def test_build_refusal_response_uses_the_guardrails_safe_override() -> None:
    nodes = _nodes()
    state = _state("should I buy Apple stock right now?")
    guardrail_result = (await nodes.evaluate_input_guardrail(state))["guardrail_result"]
    state["guardrail_result"] = guardrail_result
    result = await nodes.build_refusal_response(state)
    assert result["selected_route"] == LearningOrchestratorRoute.REFUSAL.value
    assert result["final_response"]["grounding_status"] == "REFUSED"
    assert result["final_response"]["answer_markdown"] == guardrail_result["safe_response_override"]


async def test_build_fallback_response_produces_a_learner_safe_message() -> None:
    nodes = _nodes()
    state = _state("what a nice day")
    result = await nodes.build_fallback_response(state)
    assert result["selected_route"] == LearningOrchestratorRoute.FALLBACK.value
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"


async def test_classify_intent_persists_the_rule_based_result() -> None:
    nodes = _nodes()
    state = _state("what is diversification")
    result = await nodes.classify_intent(state)
    assert result["intent_classification"]["intent"] == "EXPLAIN_CONCEPT"
    assert result["intent_classification"]["method"] == "RULE_BASED"


async def test_select_route_uses_the_pure_routing_function() -> None:
    nodes = _nodes()
    state = _state("what is diversification", intent_classification={"intent": "EXPLAIN_CONCEPT"})
    result = await nodes.select_route(state)
    assert result["selected_route"] == LearningOrchestratorRoute.GROUNDED_EXPLANATION.value


async def test_select_route_unknown_intent_falls_back() -> None:
    nodes = _nodes()
    state = _state("hmm", intent_classification={"intent": "UNKNOWN"})
    result = await nodes.select_route(state)
    assert result["selected_route"] == LearningOrchestratorRoute.FALLBACK.value


async def test_validate_final_output_strips_forbidden_keys() -> None:
    nodes = _nodes()
    state = _state(
        "hi", final_response={"answer_markdown": "x", "prompt": "leaked system prompt", "reasoning": "leaked cot"},
    )
    result = await nodes.validate_final_output(state)
    assert "prompt" not in result["final_response"]
    assert "reasoning" not in result["final_response"]


async def test_persist_final_result_appends_a_run_completed_event() -> None:
    events = FakeEventRepo()
    uow = FakeUnitOfWork(events=events)
    nodes = _nodes(uow_factory=lambda: uow)
    state = _state("hi")
    await nodes.persist_final_result(state)
    assert any(e.event_type.value == "RUN_COMPLETED" for e in events.events)


async def test_build_action_proposal_is_idempotent_for_the_same_run() -> None:
    actions = FakeActionRepo()
    uow = FakeUnitOfWork(actions=actions)
    nodes = _nodes(uow_factory=lambda: uow)
    state = _state(
        "start practice",
        proposed_action={
            "action_type": "START_ADAPTIVE_SESSION", "title": "Start a daily practice session",
            "description": "Begin an adaptive daily-practice session.", "reason": "You asked to practice.",
            "parameters": {"session_type": "DAILY_PRACTICE", "goal_minutes": None},
        },
    )
    first = await nodes.build_action_proposal(state)
    state["proposed_action"] = first["proposed_action"]
    second = await nodes.build_action_proposal(dict(state, proposed_action=dict(
        action_type="START_ADAPTIVE_SESSION", title="Start a daily practice session",
        description="Begin an adaptive daily-practice session.", reason="You asked to practice.",
        parameters={"session_type": "DAILY_PRACTICE", "goal_minutes": None},
    )))
    assert first["proposed_action"]["proposal_id"] == second["proposed_action"]["proposal_id"]
    assert len(actions.proposals) == 1
