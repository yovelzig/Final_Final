"""Unit tests for the human-approval interrupt/resume flow (spec
section 15), exercised against the real compiled graph with LangGraph's
`InMemorySaver` - no PostgreSQL, Redis, or model provider required, but
this is the one place graph *execution* (not just node functions in
isolation) is tested at the unit level, since `interrupt()`/`Command`
only behave correctly inside a running graph.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.learning_orchestrator.graph_builder import build_graph
from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier
from stock_research_core.application.learning_orchestrator.nodes import GraphNodes, NodeDependencies
from stock_research_core.application.learning_orchestrator.state import new_state
from stock_research_core.application.learning_orchestrator.subgraphs import Subgraphs, SubgraphDependencies

from tests.unit.learning_orchestrator_fakes import (
    FakeActionRepo,
    FakeContextLoader,
    FakeEventRepo,
    FakeTutorService,
    FakeUnitOfWork,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

_PRACTICE_INPUT = "I'd like to start my daily practice session to build my financial skills."

#: Exact production-evidence phrase from spec section 1: the guardrail
#: classifies this as OFF_TOPIC/FALLBACK (it has no finance vocabulary),
#: while `RuleBasedLearningIntentClassifier` correctly recognizes it as
#: `START_DAILY_PRACTICE` with `requires_action_approval=True`. Before
#: the routing fix, `_route_after_guardrail` sent FALLBACK straight to
#: `build_fallback_response`, so intent classification never ran.
_GUARDRAIL_FALLBACK_PRACTICE_INPUT = "start a practice session for me"
_DIAGNOSTIC_INPUT = "start a diagnostic assessment"
_PROGRESS_INPUT = "how am I doing"
_OFF_TOPIC_UNKNOWN_INPUT = "what's the weather like today"
_BUY_SELL_INPUT = "should I buy Apple stock right now?"


class FakeActionExecutor:
    def __init__(self, *, result=None, error=None):
        self.result = result or {"navigation_target": "/practice"}
        self.error = error
        self.executed_proposals = []

    async def execute(self, *, learner_id, proposal):
        self.executed_proposals.append(proposal)
        if self.error is not None:
            raise self.error
        return self.result


def _build_compiled_graph(*, uow, action_executor=None, tutor_service=None, context_loader=None):
    node_deps = NodeDependencies(
        unit_of_work_factory=lambda: uow, intent_classifier=RuleBasedLearningIntentClassifier(),
        context_loader=None, action_executor=action_executor or FakeActionExecutor(),
        guardrail=RuleBasedTutorGuardrail(), clock=lambda: NOW,
    )
    subgraph_deps = SubgraphDependencies(
        tutor_service=tutor_service, lesson_tutor_service=None, scenario_tutor_service=None,
        portfolio_tutor_service=None, adaptive_learning_service=None, context_loader=context_loader,
    )
    return build_graph(
        graph_nodes=GraphNodes(node_deps), subgraphs=Subgraphs(subgraph_deps), checkpointer=InMemorySaver()
    )


def _initial_state(user_input: str, *, maximum_steps: int = 30) -> tuple[dict, dict]:
    thread_id = str(uuid4())
    run_id = str(uuid4())
    state = new_state(
        thread_id=thread_id, run_id=run_id, learner_id=str(uuid4()), trusted_account_id=str(uuid4()),
        correlation_id=str(uuid4()),
        graph_version="learning-coach-graph-v1", user_input=user_input, requested_context_type="GENERAL_EDUCATION",
        maximum_steps=maximum_steps,
    )
    config = {"configurable": {"thread_id": thread_id}}
    return state, config


async def test_starting_a_practice_session_interrupts_before_executing() -> None:
    uow = FakeUnitOfWork()
    action_executor = FakeActionExecutor()
    graph = _build_compiled_graph(uow=uow, action_executor=action_executor)
    state, config = _initial_state(_PRACTICE_INPUT)

    result = await graph.ainvoke(state, config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["title"] == "Start a daily practice session"
    assert set(payload.keys()) == {"proposal_id", "title", "description", "reason", "safe_parameters", "expires_at"}
    # Nothing has executed yet - the interrupt happens before any side effect.
    assert action_executor.executed_proposals == []


async def test_approving_resumes_and_executes_exactly_once() -> None:
    uow = FakeUnitOfWork()
    action_executor = FakeActionExecutor()
    graph = _build_compiled_graph(uow=uow, action_executor=action_executor)
    state, config = _initial_state(_PRACTICE_INPUT)

    await graph.ainvoke(state, config=config)
    result = await graph.ainvoke(Command(resume={"decision": "APPROVE"}), config=config)

    assert "__interrupt__" not in result
    assert result["final_response"]["navigation_target"] == "/practice"
    assert len(action_executor.executed_proposals) == 1


async def test_rejecting_ends_the_branch_without_executing() -> None:
    uow = FakeUnitOfWork()
    action_executor = FakeActionExecutor()
    graph = _build_compiled_graph(uow=uow, action_executor=action_executor)
    state, config = _initial_state(_PRACTICE_INPUT)

    await graph.ainvoke(state, config=config)
    result = await graph.ainvoke(Command(resume={"decision": "REJECT"}), config=config)

    assert "__interrupt__" not in result
    assert action_executor.executed_proposals == []
    assert "won't take that action" in result["final_response"]["answer_markdown"]


async def test_resuming_twice_does_not_execute_the_action_twice() -> None:
    """A duplicate resume call against an already-terminal thread must
    not re-run `execute_action` - LangGraph itself won't re-invoke a
    completed run's graph without a fresh interrupt to resume from, but
    this asserts that guarantee holds for our specific graph shape."""
    uow = FakeUnitOfWork()
    action_executor = FakeActionExecutor()
    graph = _build_compiled_graph(uow=uow, action_executor=action_executor)
    state, config = _initial_state(_PRACTICE_INPUT)

    await graph.ainvoke(state, config=config)
    await graph.ainvoke(Command(resume={"decision": "APPROVE"}), config=config)
    assert len(action_executor.executed_proposals) == 1

    # A second resume on the same (now-terminal) thread config replays
    # the completed run's final state rather than re-executing anything.
    second = await graph.ainvoke(Command(resume={"decision": "APPROVE"}), config=config)
    assert len(action_executor.executed_proposals) == 1
    assert second["final_response"]["navigation_target"] == "/practice"


async def test_action_execution_failure_does_not_crash_the_run() -> None:
    uow = FakeUnitOfWork()
    action_executor = FakeActionExecutor(error=RuntimeError("boom"))
    graph = _build_compiled_graph(uow=uow, action_executor=action_executor)
    state, config = _initial_state(_PRACTICE_INPUT)

    await graph.ainvoke(state, config=config)
    result = await graph.ainvoke(Command(resume={"decision": "APPROVE"}), config=config)

    assert "__interrupt__" not in result
    assert "couldn't complete" in result["final_response"]["answer_markdown"]
    assert len(result.get("safe_errors", [])) == 1
    # No raw exception text ever reaches the learner-safe response.
    assert "boom" not in result["final_response"]["answer_markdown"]
    assert "RuntimeError" not in result["final_response"]["answer_markdown"]


async def test_step_count_is_durable_across_the_interrupt() -> None:
    uow = FakeUnitOfWork()
    graph = _build_compiled_graph(uow=uow)
    state, config = _initial_state(_PRACTICE_INPUT)

    interrupted = await graph.ainvoke(state, config=config)
    step_count_at_interrupt = interrupted["step_count"]
    assert step_count_at_interrupt > 0

    resumed = await graph.ainvoke(Command(resume={"decision": "APPROVE"}), config=config)
    assert resumed["step_count"] > step_count_at_interrupt


async def test_recursion_limit_is_bounded_and_enforced() -> None:
    """`maximum_steps` on the state is enforced inside `GraphNodes`
    (`RunStepLimitExceededError`) independent of LangGraph's own
    `recursion_limit` - a run can never silently loop forever."""
    from stock_research_core.application.learning_orchestrator.nodes import RunStepLimitExceededError

    uow = FakeUnitOfWork()
    graph = _build_compiled_graph(uow=uow)
    state, config = _initial_state(_PRACTICE_INPUT, maximum_steps=1)

    with pytest.raises(RunStepLimitExceededError):
        await graph.ainvoke(state, config=config)


# -- Phase G2D2 section 1: guardrail FALLBACK must still reach intent classification --------------------


async def test_guardrail_fallback_phrasing_still_reaches_intent_classification() -> None:
    """The guardrail alone would classify this input OFF_TOPIC/FALLBACK
    (no finance vocabulary token matches `_is_off_topic`), but the fixed
    `_route_after_guardrail` must still route it to `classify_intent`,
    where `RuleBasedLearningIntentClassifier` recognizes the
    DAILY_PRACTICE_PHRASE rule and produces a practice proposal."""
    uow = FakeUnitOfWork()
    action_executor = FakeActionExecutor()
    graph = _build_compiled_graph(uow=uow, action_executor=action_executor)
    state, config = _initial_state(_GUARDRAIL_FALLBACK_PRACTICE_INPUT)

    result = await graph.ainvoke(state, config=config)

    assert result["intent_classification"]["intent"] == "START_DAILY_PRACTICE"
    assert result["intent_classification"]["requires_action_approval"] is True
    assert result["selected_route"] == "PRACTICE_ACTION"
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["title"] == "Start a daily practice session"
    assert action_executor.executed_proposals == []


async def test_guardrail_fallback_practice_proposal_can_be_approved() -> None:
    uow = FakeUnitOfWork()
    action_executor = FakeActionExecutor()
    graph = _build_compiled_graph(uow=uow, action_executor=action_executor)
    state, config = _initial_state(_GUARDRAIL_FALLBACK_PRACTICE_INPUT)

    await graph.ainvoke(state, config=config)
    result = await graph.ainvoke(Command(resume={"decision": "APPROVE"}), config=config)

    assert "__interrupt__" not in result
    assert len(action_executor.executed_proposals) == 1


async def test_start_diagnostic_assessment_reaches_diagnostic_action() -> None:
    uow = FakeUnitOfWork()
    graph = _build_compiled_graph(uow=uow)
    state, config = _initial_state(_DIAGNOSTIC_INPUT)

    result = await graph.ainvoke(state, config=config)

    assert result["intent_classification"]["intent"] == "START_DIAGNOSTIC"
    assert result["selected_route"] == "DIAGNOSTIC_ACTION"
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["title"] == "Start a diagnostic assessment"


async def test_progress_question_reaches_progress_reflection_route() -> None:
    """Regression: an ALLOW-guardrail input unrelated to the guardrail
    fix must still classify and route exactly as before."""
    uow = FakeUnitOfWork()
    tutor_service = FakeTutorService(answer_markdown="You're making steady progress.")
    graph = _build_compiled_graph(uow=uow, tutor_service=tutor_service, context_loader=FakeContextLoader())
    state, config = _initial_state(_PROGRESS_INPUT)

    result = await graph.ainvoke(state, config=config)

    assert result["intent_classification"]["intent"] == "REVIEW_PROGRESS"
    assert result["selected_route"] == "PROGRESS_REFLECTION"
    assert "__interrupt__" not in result
    assert result["final_response"]["answer_markdown"] == "You're making steady progress."
    assert tutor_service.asked_questions == [_PROGRESS_INPUT]


async def test_unrelated_question_becomes_unknown_and_reaches_fallback_via_classification() -> None:
    """An off-topic question the intent classifier also cannot place
    must still pass *through* `classify_intent` (unlike before the fix,
    where the guardrail's own FALLBACK action skipped classification
    entirely) before landing on `build_fallback_response`."""
    uow = FakeUnitOfWork()
    graph = _build_compiled_graph(uow=uow)
    state, config = _initial_state(_OFF_TOPIC_UNKNOWN_INPUT)

    result = await graph.ainvoke(state, config=config)

    assert result["intent_classification"]["intent"] == "UNKNOWN"
    assert result["selected_route"] == "FALLBACK"
    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"


async def test_resume_payload_cannot_override_the_trusted_account_id() -> None:
    """`trusted_account_id` is set once, server-side, by `new_state()` at
    run creation - no node ever copies resume-payload content into it, so
    a resume `Command` carrying a spoofed `trusted_account_id`/`account_id`
    key must have zero effect on the run's actual trusted identity."""
    uow = FakeUnitOfWork()
    graph = _build_compiled_graph(uow=uow)
    state, config = _initial_state(_PRACTICE_INPUT)
    original_account_id = state["trusted_account_id"]

    await graph.ainvoke(state, config=config)
    result = await graph.ainvoke(
        Command(resume={"decision": "APPROVE", "trusted_account_id": "attacker-controlled", "account_id": "attacker-controlled"}),
        config=config,
    )

    assert result["trusted_account_id"] == original_account_id


async def test_buy_sell_request_is_refused_before_intent_classification() -> None:
    """REFUSE must not weaken: a buy/sell instruction never reaches
    intent classification at all - it goes straight to
    `build_refusal_response`."""
    uow = FakeUnitOfWork()
    graph = _build_compiled_graph(uow=uow)
    state, config = _initial_state(_BUY_SELL_INPUT)

    result = await graph.ainvoke(state, config=config)

    assert "intent_classification" not in result
    assert result["selected_route"] == "REFUSAL"
    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "REFUSED"
