"""Integration tests for the Phase 12 learning-orchestrator repositories
against the real PostgreSQL test database: `LearningOrchestratorThread`/
`Run`/`Event`/`LearningActionProposal` persistence round-trips.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.learning_orchestrator.enums import (
    LearnerApprovalDecision,
    LearningActionProposalStatus,
    LearningActionType,
    LearningOrchestratorEventType,
    LearningOrchestratorRunStatus,
    LearningOrchestratorThreadStatus,
)
from stock_research_core.domain.learning_orchestrator.models import (
    LearningActionProposal,
    LearningOrchestratorEvent,
    LearningOrchestratorRun,
    LearningOrchestratorThread,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_learner(uow_factory) -> LearnerProfile:
    learner = LearnerProfile(display_name="Coach Test Learner")
    async with uow_factory() as uow:
        stored = await uow.learners.create(learner)
        await uow.commit()
    return stored


def _thread(learner_id, **overrides) -> LearningOrchestratorThread:
    fields = dict(
        learner_id=learner_id, title="My coach thread", graph_name="finquest-learning-coach",
        graph_version="learning-coach-graph-v1",
    )
    fields.update(overrides)
    return LearningOrchestratorThread(**fields)


def _run(thread_id, learner_id, **overrides) -> LearningOrchestratorRun:
    fields = dict(
        thread_id=thread_id, learner_id=learner_id, idempotency_key=f"key-{uuid4()}", correlation_id=str(uuid4()),
        graph_version="learning-coach-graph-v1",
    )
    fields.update(overrides)
    return LearningOrchestratorRun(**fields)


class TestLearningOrchestratorThreadRepository:
    async def test_create_and_get_by_id(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        thread = _thread(learner.learner_id)
        async with uow_factory() as uow:
            created = await uow.learning_orchestrator_threads.create(thread)
            await uow.commit()
        async with uow_factory() as uow:
            fetched = await uow.learning_orchestrator_threads.get_by_id(created.thread_id)
        assert fetched is not None
        assert fetched.title == "My coach thread"
        assert fetched.status == LearningOrchestratorThreadStatus.ACTIVE

    async def test_list_for_learner_filters_by_status(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            active = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id, title="Active"))
            await uow.commit()
        async with uow_factory() as uow:
            closed = await uow.learning_orchestrator_threads.close(active.thread_id, closed_at=NOW)
            await uow.commit()

        async with uow_factory() as uow:
            active_only = await uow.learning_orchestrator_threads.list_for_learner(
                learner.learner_id, status=LearningOrchestratorThreadStatus.ACTIVE
            )
            closed_only = await uow.learning_orchestrator_threads.list_for_learner(
                learner.learner_id, status=LearningOrchestratorThreadStatus.CLOSED
            )
        assert active_only == []
        assert [t.thread_id for t in closed_only] == [closed.thread_id]

    async def test_count_for_learner(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            await uow.learning_orchestrator_threads.create(_thread(learner.learner_id, title="One"))
            await uow.learning_orchestrator_threads.create(_thread(learner.learner_id, title="Two"))
            await uow.commit()
        async with uow_factory() as uow:
            total = await uow.learning_orchestrator_threads.count_for_learner(learner.learner_id)
        assert total == 2

    async def test_close_sets_closed_at_and_status(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            created = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            await uow.commit()
        async with uow_factory() as uow:
            closed = await uow.learning_orchestrator_threads.close(created.thread_id, closed_at=NOW)
            await uow.commit()
        assert closed.status == LearningOrchestratorThreadStatus.CLOSED
        assert closed.closed_at == NOW


class TestLearningOrchestratorRunRepository:
    async def test_create_and_get_by_idempotency_key(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            await uow.commit()
        run = _run(thread.thread_id, learner.learner_id, idempotency_key="stable-key")
        async with uow_factory() as uow:
            created = await uow.learning_orchestrator_runs.create(run)
            await uow.commit()
        async with uow_factory() as uow:
            found = await uow.learning_orchestrator_runs.get_by_idempotency_key(
                thread_id=thread.thread_id, idempotency_key="stable-key"
            )
        assert found is not None
        assert found.run_id == created.run_id

    async def test_lifecycle_transitions_round_trip(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            created = await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            await uow.commit()

        async with uow_factory() as uow:
            running = await uow.learning_orchestrator_runs.mark_running(created.run_id, started_at=NOW)
            await uow.commit()
        assert running.status == LearningOrchestratorRunStatus.RUNNING

        async with uow_factory() as uow:
            progressed = await uow.learning_orchestrator_runs.update_progress(
                created.run_id, step_count=5, intent="EXPLAIN_CONCEPT", route="GROUNDED_EXPLANATION"
            )
            await uow.commit()
        assert progressed.step_count == 5
        assert progressed.intent.value == "EXPLAIN_CONCEPT"

        async with uow_factory() as uow:
            succeeded = await uow.learning_orchestrator_runs.mark_succeeded(
                created.run_id, completed_at=NOW, output_tutor_answer_id=None
            )
            await uow.commit()
        assert succeeded.status == LearningOrchestratorRunStatus.SUCCEEDED
        # `onupdate=func.now()` columns must reflect the real DB-side value
        # after the repository's own post-update refresh - never a stale,
        # client-computed timestamp (Phase 11's hard-won lesson).
        assert succeeded.updated_at >= succeeded.created_at

    async def test_mark_waiting_for_learner(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            created = await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            await uow.learning_orchestrator_runs.mark_running(created.run_id, started_at=NOW)
            await uow.commit()
        async with uow_factory() as uow:
            waiting = await uow.learning_orchestrator_runs.mark_waiting_for_learner(created.run_id, waiting_at=NOW)
            await uow.commit()
        assert waiting.status == LearningOrchestratorRunStatus.WAITING_FOR_LEARNER
        assert waiting.waiting_at == NOW

    async def test_mark_failed_requires_sanitized_failure_fields(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            created = await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            await uow.commit()
        async with uow_factory() as uow:
            failed = await uow.learning_orchestrator_runs.mark_failed(
                created.run_id, completed_at=NOW, failure_code="RunTimeoutError",
                failure_message="The run could not be completed. Please try again.",
            )
            await uow.commit()
        assert failed.status == LearningOrchestratorRunStatus.FAILED
        assert failed.failure_code == "RunTimeoutError"

    async def test_list_for_thread(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            await uow.commit()
        async with uow_factory() as uow:
            runs = await uow.learning_orchestrator_runs.list_for_thread(thread.thread_id)
        assert len(runs) == 2


class TestLearningOrchestratorEventRepository:
    async def test_append_and_list_for_run_preserves_sequence_order(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            run = await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            await uow.commit()

        async with uow_factory() as uow:
            for index in range(1, 4):
                sequence_number = await uow.learning_orchestrator_events.next_sequence_number(run.run_id)
                assert sequence_number == index
                await uow.learning_orchestrator_events.append(
                    LearningOrchestratorEvent(
                        run_id=run.run_id, thread_id=thread.thread_id,
                        event_type=LearningOrchestratorEventType.RUN_STARTED, sequence_number=sequence_number,
                        learner_message=f"Event {index}.",
                    )
                )
            await uow.commit()

        async with uow_factory() as uow:
            events = await uow.learning_orchestrator_events.list_for_run(run.run_id)
        assert [e.sequence_number for e in events] == [1, 2, 3]
        assert [e.learner_message for e in events] == ["Event 1.", "Event 2.", "Event 3."]


class TestLearningOrchestratorActionRepository:
    def _proposal(self, run_id, thread_id, learner_id, **overrides) -> LearningActionProposal:
        fields = dict(
            run_id=run_id, thread_id=thread_id, learner_id=learner_id,
            action_type=LearningActionType.START_ADAPTIVE_SESSION, title="Start a daily practice session",
            description="Begin an adaptive daily-practice session.", reason="You asked to practice.",
            idempotency_key=f"key-{uuid4()}",
        )
        fields.update(overrides)
        return LearningActionProposal(**fields)

    async def test_create_and_get_by_idempotency_key(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            run = await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            await uow.commit()
        proposal = self._proposal(run.run_id, thread.thread_id, learner.learner_id, idempotency_key="stable-key")
        async with uow_factory() as uow:
            created = await uow.learning_orchestrator_actions.create(proposal)
            await uow.commit()
        async with uow_factory() as uow:
            found = await uow.learning_orchestrator_actions.get_by_idempotency_key(
                run_id=run.run_id, idempotency_key="stable-key"
            )
        assert found is not None
        assert found.proposal_id == created.proposal_id

    async def test_approval_lifecycle_round_trips(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            run = await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            created = await uow.learning_orchestrator_actions.create(
                self._proposal(run.run_id, thread.thread_id, learner.learner_id)
            )
            await uow.commit()

        async with uow_factory() as uow:
            waiting = await uow.learning_orchestrator_actions.mark_waiting_for_approval(created.proposal_id)
            await uow.commit()
        assert waiting.status == LearningActionProposalStatus.WAITING_FOR_APPROVAL

        async with uow_factory() as uow:
            approved = await uow.learning_orchestrator_actions.mark_approved(
                created.proposal_id, approved_at=NOW, approval_payload={"decision": LearnerApprovalDecision.APPROVE.value},
            )
            await uow.commit()
        assert approved.status == LearningActionProposalStatus.APPROVED
        assert approved.approved_at == NOW

        async with uow_factory() as uow:
            executing = await uow.learning_orchestrator_actions.mark_executing(created.proposal_id, executed_at=NOW)
            await uow.commit()
        assert executing.status == LearningActionProposalStatus.EXECUTING

        async with uow_factory() as uow:
            succeeded = await uow.learning_orchestrator_actions.mark_succeeded(
                created.proposal_id, completed_at=NOW, result_reference={"navigation_target": "/practice"},
            )
            await uow.commit()
        assert succeeded.status == LearningActionProposalStatus.SUCCEEDED
        assert succeeded.result_reference == {"navigation_target": "/practice"}

    async def test_mark_rejected(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            run = await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            created = await uow.learning_orchestrator_actions.create(
                self._proposal(run.run_id, thread.thread_id, learner.learner_id)
            )
            await uow.commit()
        async with uow_factory() as uow:
            rejected = await uow.learning_orchestrator_actions.mark_rejected(created.proposal_id, rejected_at=NOW)
            await uow.commit()
        assert rejected.status == LearningActionProposalStatus.REJECTED

    async def test_list_for_run(self, uow_factory) -> None:
        learner = await _seed_learner(uow_factory)
        async with uow_factory() as uow:
            thread = await uow.learning_orchestrator_threads.create(_thread(learner.learner_id))
            run = await uow.learning_orchestrator_runs.create(_run(thread.thread_id, learner.learner_id))
            await uow.learning_orchestrator_actions.create(
                self._proposal(run.run_id, thread.thread_id, learner.learner_id)
            )
            await uow.commit()
        async with uow_factory() as uow:
            proposals = await uow.learning_orchestrator_actions.list_for_run(run.run_id)
        assert len(proposals) == 1
