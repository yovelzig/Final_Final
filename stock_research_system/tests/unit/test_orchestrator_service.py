"""Unit tests for `PersonalizedLearningOrchestratorService` - uses the
in-memory fakes from `learning_orchestrator_fakes.py` for every port
(no PostgreSQL, Redis, or LangGraph checkpointer required)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import (
    LearningActionProposalAlreadyDecidedError,
    LearningOrchestratorRunNotCancellableError,
    LearningOrchestratorRunNotFoundError,
    LearningOrchestratorRunNotWaitingError,
    LearningOrchestratorThreadClosedError,
    LearningOrchestratorThreadNotFoundError,
)
from stock_research_core.application.learning_orchestrator.models import LearningApprovalRequest
from stock_research_core.application.learning_orchestrator.service import PersonalizedLearningOrchestratorService
from stock_research_core.domain.learning_orchestrator.enums import (
    LearnerApprovalDecision,
    LearningActionType,
    LearningOrchestratorRunStatus,
    LearningOrchestratorThreadStatus,
)
from stock_research_core.domain.learning_orchestrator.models import LearningActionProposal

from tests.unit.learning_orchestrator_fakes import (
    FakeGraphRuntime,
    FakeLockPort,
    FakeMetrics,
    FakeTracing,
    FakeUnitOfWork,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _build_service(*, graph_runtime=None, uow=None, lock=None):
    uow = uow or FakeUnitOfWork()
    return (
        PersonalizedLearningOrchestratorService(
            unit_of_work_factory=lambda: uow, graph_runtime=graph_runtime or FakeGraphRuntime(),
            lock_port=lock or FakeLockPort(), metrics=FakeMetrics(), tracing=FakeTracing(), clock=lambda: NOW,
        ),
        uow,
    )


async def _make_thread(service, learner_id):
    return await service.create_thread(learner_id=learner_id, title="Thread")


# -- threads -----------------------------------------------


async def test_create_thread_persists_and_returns_the_thread() -> None:
    service, _ = _build_service()
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)
    assert thread.learner_id == learner_id
    assert thread.status == LearningOrchestratorThreadStatus.ACTIVE


async def test_get_thread_raises_not_found_for_a_different_learner() -> None:
    service, _ = _build_service()
    thread = await _make_thread(service, uuid4())
    with pytest.raises(LearningOrchestratorThreadNotFoundError):
        await service.get_thread(learner_id=uuid4(), thread_id=thread.thread_id)


async def test_close_thread_sets_closed_status() -> None:
    service, _ = _build_service()
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)
    closed = await service.close_thread(learner_id=learner_id, thread_id=thread.thread_id)
    assert closed.status == LearningOrchestratorThreadStatus.CLOSED
    assert closed.closed_at == NOW


# -- start_run -----------------------------------------------


async def test_start_run_returns_succeeded_run_on_graph_completion() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 3, "selected_route": "GROUNDED_EXPLANATION"}, False))
    service, _ = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)

    run = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="What is diversification?",
        idempotency_key="key-1",
    )
    assert run.status == LearningOrchestratorRunStatus.SUCCEEDED
    assert run.route == "GROUNDED_EXPLANATION"
    assert len(graph_runtime.start_run_calls) == 1


async def test_start_run_returns_waiting_for_learner_on_interrupt() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 6}, True))
    service, _ = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)

    run = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="start a daily practice session",
        idempotency_key="key-1",
    )
    assert run.status == LearningOrchestratorRunStatus.WAITING_FOR_LEARNER


async def test_start_run_is_idempotent_for_the_same_key() -> None:
    graph_runtime = FakeGraphRuntime()
    service, _ = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)

    first = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="hello", idempotency_key="same-key",
    )
    second = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="hello again", idempotency_key="same-key",
    )
    assert first.run_id == second.run_id
    assert len(graph_runtime.start_run_calls) == 1


async def test_start_run_rejects_a_closed_thread() -> None:
    service, _ = _build_service()
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)
    await service.close_thread(learner_id=learner_id, thread_id=thread.thread_id)

    with pytest.raises(LearningOrchestratorThreadClosedError):
        await service.start_run(
            learner_id=learner_id, thread_id=thread.thread_id, user_input="hello", idempotency_key="key-1",
        )


async def test_start_run_marks_run_failed_on_graph_error() -> None:
    graph_runtime = FakeGraphRuntime(error=RuntimeError("boom"))
    service, _ = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)

    run = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="hello", idempotency_key="key-1",
    )
    assert run.status == LearningOrchestratorRunStatus.FAILED
    assert run.failure_code == "RuntimeError"
    # Never leaks the raw exception message/traceback to the learner-facing field.
    assert "boom" not in (run.failure_message or "")


async def test_start_run_rejects_someone_elses_thread() -> None:
    service, _ = _build_service()
    thread = await _make_thread(service, uuid4())
    with pytest.raises(LearningOrchestratorThreadNotFoundError):
        await service.start_run(
            learner_id=uuid4(), thread_id=thread.thread_id, user_input="hello", idempotency_key="key-1",
        )


# -- resume_run -----------------------------------------------


async def _run_to_waiting(service, uow, learner_id):
    thread = await _make_thread(service, learner_id)
    run = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="start practice", idempotency_key="key-1",
    )
    assert run.status == LearningOrchestratorRunStatus.WAITING_FOR_LEARNER
    proposal = LearningActionProposal(
        run_id=run.run_id, thread_id=thread.thread_id, learner_id=learner_id,
        action_type=LearningActionType.START_ADAPTIVE_SESSION, title="Start practice",
        description="Begin practice.", reason="You asked to practice.", idempotency_key=f"{run.run_id}:x",
    )
    proposal = await uow.learning_orchestrator_actions.create(proposal)
    await uow.learning_orchestrator_actions.mark_waiting_for_approval(proposal.proposal_id)
    return run, proposal


async def test_resume_run_approve_calls_graph_runtime_with_approve_decision() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 6}, True))
    service, uow = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    run, proposal = await _run_to_waiting(service, uow, learner_id)
    graph_runtime.result = ({"step_count": 10}, False)

    updated = await service.resume_run(
        learner_id=learner_id, run_id=run.run_id,
        approval=LearningApprovalRequest(proposal_id=proposal.proposal_id, decision=LearnerApprovalDecision.APPROVE.value),
    )
    assert updated.status == LearningOrchestratorRunStatus.SUCCEEDED
    assert graph_runtime.resume_run_calls[0]["resume_value"] == {"decision": "APPROVE"}


async def test_resume_run_rejects_when_run_is_not_waiting() -> None:
    """A proposal can exist and be undecided while its run has already
    moved past WAITING_FOR_LEARNER (e.g. a stale/duplicate resume
    request racing a legitimate one) - the run-status check must still
    refuse it, independent of the proposal's own status."""
    graph_runtime = FakeGraphRuntime(result=({"step_count": 3}, False))
    service, uow = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)
    run = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="what is a bond", idempotency_key="key-1",
    )
    assert run.status == LearningOrchestratorRunStatus.SUCCEEDED

    proposal = LearningActionProposal(
        run_id=run.run_id, thread_id=thread.thread_id, learner_id=learner_id,
        action_type=LearningActionType.START_ADAPTIVE_SESSION, title="Start practice",
        description="Begin practice.", reason="You asked to practice.", idempotency_key=f"{run.run_id}:x",
    )
    proposal = await uow.learning_orchestrator_actions.create(proposal)
    await uow.learning_orchestrator_actions.mark_waiting_for_approval(proposal.proposal_id)

    with pytest.raises(LearningOrchestratorRunNotWaitingError):
        await service.resume_run(
            learner_id=learner_id, run_id=run.run_id,
            approval=LearningApprovalRequest(proposal_id=proposal.proposal_id, decision="APPROVE"),
        )


async def test_resume_run_replaying_the_same_decision_on_a_terminal_run_is_idempotent() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 6}, True))
    service, uow = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    run, proposal = await _run_to_waiting(service, uow, learner_id)
    graph_runtime.result = ({"step_count": 10}, False)
    approval = LearningApprovalRequest(proposal_id=proposal.proposal_id, decision="APPROVE")

    first = await service.resume_run(learner_id=learner_id, run_id=run.run_id, approval=approval)
    second = await service.resume_run(learner_id=learner_id, run_id=run.run_id, approval=approval)
    assert first.run_id == second.run_id == run.run_id
    assert len(graph_runtime.resume_run_calls) == 1  # not resumed twice


async def test_resume_run_rejects_a_different_decision_after_already_decided() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 10}, True))  # stays WAITING after resume
    service, uow = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    run, proposal = await _run_to_waiting(service, uow, learner_id)

    await service.resume_run(
        learner_id=learner_id, run_id=run.run_id,
        approval=LearningApprovalRequest(proposal_id=proposal.proposal_id, decision="APPROVE"),
    )
    with pytest.raises(LearningActionProposalAlreadyDecidedError):
        await service.resume_run(
            learner_id=learner_id, run_id=run.run_id,
            approval=LearningApprovalRequest(proposal_id=proposal.proposal_id, decision="REJECT"),
        )


async def test_resume_run_edit_validates_edited_parameters() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 6}, True))
    service, uow = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    run, proposal = await _run_to_waiting(service, uow, learner_id)
    graph_runtime.result = ({"step_count": 10}, False)

    updated = await service.resume_run(
        learner_id=learner_id, run_id=run.run_id,
        approval=LearningApprovalRequest(
            proposal_id=proposal.proposal_id, decision="EDIT", edited_parameters={"goal_minutes": 20},
        ),
    )
    assert updated.status == LearningOrchestratorRunStatus.SUCCEEDED
    resume_value = graph_runtime.resume_run_calls[0]["resume_value"]
    assert resume_value["edited_parameters"]["goal_minutes"] == 20


# -- cancel_run -----------------------------------------------


async def test_cancel_run_marks_cancelled() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 6}, True))
    service, _ = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)
    run = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="start practice", idempotency_key="key-1",
    )
    cancelled = await service.cancel_run(learner_id=learner_id, run_id=run.run_id)
    assert cancelled.status == LearningOrchestratorRunStatus.CANCELLED
    assert graph_runtime.cancelled_threads == [str(thread.thread_id)]


async def test_cancel_run_rejects_an_already_terminal_run() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 3}, False))
    service, _ = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)
    run = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="hello", idempotency_key="key-1",
    )
    assert run.status == LearningOrchestratorRunStatus.SUCCEEDED
    with pytest.raises(LearningOrchestratorRunNotCancellableError):
        await service.cancel_run(learner_id=learner_id, run_id=run.run_id)


async def test_cancel_run_rejects_a_run_owned_by_a_different_learner() -> None:
    graph_runtime = FakeGraphRuntime(result=({"step_count": 6}, True))
    service, _ = _build_service(graph_runtime=graph_runtime)
    learner_id = uuid4()
    thread = await _make_thread(service, learner_id)
    run = await service.start_run(
        learner_id=learner_id, thread_id=thread.thread_id, user_input="start practice", idempotency_key="key-1",
    )
    with pytest.raises(LearningOrchestratorRunNotFoundError):
        await service.cancel_run(learner_id=uuid4(), run_id=run.run_id)
