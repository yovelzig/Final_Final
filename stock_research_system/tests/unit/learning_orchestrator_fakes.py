"""Shared in-memory fakes for Phase 12 learning-orchestrator unit tests
(no PostgreSQL, Redis, LangGraph checkpointer, or model provider
required). Not collected by pytest (no `test_` prefix) - imported by the
`test_orchestrator_*.py` modules.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from stock_research_core.domain.ai_tutor.enums import GroundingStatus
from stock_research_core.domain.learning_orchestrator.enums import LearningActionProposalStatus
from stock_research_core.domain.learning_orchestrator.models import (
    LearningActionProposal,
    LearningOrchestratorEvent,
    LearningOrchestratorRun,
    LearningOrchestratorThread,
)


class FakeThreadRepo:
    def __init__(self) -> None:
        self.threads: dict[UUID, LearningOrchestratorThread] = {}

    async def create(self, thread: LearningOrchestratorThread) -> LearningOrchestratorThread:
        self.threads[thread.thread_id] = thread
        return thread

    async def get_by_id(self, thread_id: UUID) -> LearningOrchestratorThread | None:
        return self.threads.get(thread_id)

    async def list_for_learner(self, learner_id, *, status=None, limit=50, offset=0):
        matches = [
            t for t in self.threads.values()
            if t.learner_id == learner_id and (status is None or t.status == status)
        ]
        return matches[offset : offset + limit]

    async def count_for_learner(self, learner_id, *, status=None) -> int:
        return len(
            [t for t in self.threads.values() if t.learner_id == learner_id and (status is None or t.status == status)]
        )

    async def close(self, thread_id: UUID, *, closed_at):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorThreadStatus

        updated = self.threads[thread_id].model_copy(
            update={"status": LearningOrchestratorThreadStatus.CLOSED, "closed_at": closed_at}
        )
        self.threads[thread_id] = updated
        return updated

    async def touch(self, thread_id: UUID, *, updated_at):
        updated = self.threads[thread_id].model_copy(update={"updated_at": updated_at})
        self.threads[thread_id] = updated
        return updated


class FakeRunRepo:
    def __init__(self) -> None:
        self.runs: dict[UUID, LearningOrchestratorRun] = {}

    async def create(self, run: LearningOrchestratorRun) -> LearningOrchestratorRun:
        self.runs[run.run_id] = run
        return run

    async def get_by_id(self, run_id: UUID) -> LearningOrchestratorRun | None:
        return self.runs.get(run_id)

    async def get_for_update(self, run_id: UUID) -> LearningOrchestratorRun | None:
        return self.runs.get(run_id)

    async def get_by_idempotency_key(self, *, thread_id: UUID, idempotency_key: str):
        for run in self.runs.values():
            if run.thread_id == thread_id and run.idempotency_key == idempotency_key:
                return run
        return None

    def _update(self, run_id: UUID, **updates: Any) -> LearningOrchestratorRun:
        updated = self.runs[run_id].model_copy(update=updates)
        self.runs[run_id] = updated
        return updated

    async def mark_running(self, run_id: UUID, *, started_at):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        return self._update(run_id, status=LearningOrchestratorRunStatus.RUNNING, started_at=started_at)

    async def mark_waiting_for_learner(self, run_id: UUID, *, waiting_at):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        return self._update(run_id, status=LearningOrchestratorRunStatus.WAITING_FOR_LEARNER, waiting_at=waiting_at)

    async def mark_waiting_for_research(self, run_id: UUID, *, waiting_at, research_job_id, research_deadline_at):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        return self._update(
            run_id, status=LearningOrchestratorRunStatus.WAITING_FOR_RESEARCH, waiting_at=waiting_at,
            research_job_id=research_job_id, research_deadline_at=research_deadline_at,
        )

    async def set_research_outcome(
        self, run_id: UUID, *, research_request_id, research_run_id, research_failure_category, evidence_count,
    ):
        return self._update(
            run_id, research_request_id=research_request_id, research_run_id=research_run_id,
            research_failure_category=research_failure_category, evidence_count=evidence_count,
        )

    async def get_by_research_job_id(self, research_job_id: UUID):
        for run in self.runs.values():
            if run.research_job_id == research_job_id:
                return run
        return None

    async def list_waiting_for_research(self, *, limit: int = 100):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        matches = [run for run in self.runs.values() if run.status == LearningOrchestratorRunStatus.WAITING_FOR_RESEARCH]
        return matches[:limit]

    async def list_waiting_for_research_past_deadline(self, *, now, limit: int = 100):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        matches = [
            run for run in self.runs.values()
            if run.status == LearningOrchestratorRunStatus.WAITING_FOR_RESEARCH
            and run.research_deadline_at is not None
            and run.research_deadline_at < now
        ]
        return matches[:limit]

    async def mark_expired(self, run_id: UUID, *, completed_at):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        return self._update(run_id, status=LearningOrchestratorRunStatus.EXPIRED, completed_at=completed_at)

    async def update_progress(self, run_id: UUID, *, step_count, intent=None, route=None):
        updates: dict[str, Any] = {"step_count": step_count}
        if intent is not None:
            updates["intent"] = intent
        if route is not None:
            updates["route"] = route
        return self._update(run_id, **updates)

    async def mark_succeeded(self, run_id: UUID, *, completed_at, output_tutor_answer_id):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        return self._update(
            run_id, status=LearningOrchestratorRunStatus.SUCCEEDED, completed_at=completed_at,
            output_tutor_answer_id=output_tutor_answer_id,
        )

    async def mark_failed(self, run_id: UUID, *, completed_at, failure_code, failure_message):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        return self._update(
            run_id, status=LearningOrchestratorRunStatus.FAILED, completed_at=completed_at,
            failure_code=failure_code, failure_message=failure_message,
        )

    async def mark_cancelled(self, run_id: UUID, *, cancelled_at):
        from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus

        return self._update(run_id, status=LearningOrchestratorRunStatus.CANCELLED, cancelled_at=cancelled_at)

    async def list_for_thread(self, thread_id: UUID, *, limit=50, offset=0):
        matches = [r for r in self.runs.values() if r.thread_id == thread_id]
        return matches[offset : offset + limit]


class FakeEventRepo:
    def __init__(self) -> None:
        self.events: list[LearningOrchestratorEvent] = []

    async def append(self, event: LearningOrchestratorEvent) -> LearningOrchestratorEvent:
        self.events.append(event)
        return event

    async def list_for_run(self, run_id: UUID) -> list[LearningOrchestratorEvent]:
        return [e for e in self.events if e.run_id == run_id]

    async def next_sequence_number(self, run_id: UUID) -> int:
        return len([e for e in self.events if e.run_id == run_id]) + 1


class FakeActionRepo:
    def __init__(self) -> None:
        self.proposals: dict[UUID, LearningActionProposal] = {}

    async def create(self, proposal: LearningActionProposal) -> LearningActionProposal:
        self.proposals[proposal.proposal_id] = proposal
        return proposal

    async def get_by_id(self, proposal_id: UUID) -> LearningActionProposal | None:
        return self.proposals.get(proposal_id)

    async def get_for_update(self, proposal_id: UUID) -> LearningActionProposal | None:
        return self.proposals.get(proposal_id)

    async def get_by_idempotency_key(self, *, run_id: UUID, idempotency_key: str):
        for proposal in self.proposals.values():
            if proposal.run_id == run_id and proposal.idempotency_key == idempotency_key:
                return proposal
        return None

    def _update(self, proposal_id: UUID, **updates: Any) -> LearningActionProposal:
        updated = self.proposals[proposal_id].model_copy(update=updates)
        self.proposals[proposal_id] = updated
        return updated

    async def mark_waiting_for_approval(self, proposal_id: UUID) -> LearningActionProposal:
        return self._update(proposal_id, status=LearningActionProposalStatus.WAITING_FOR_APPROVAL)

    async def mark_approved(self, proposal_id: UUID, *, approved_at, approval_payload):
        return self._update(
            proposal_id, status=LearningActionProposalStatus.APPROVED, approved_at=approved_at,
            approval_payload=approval_payload,
        )

    async def mark_rejected(self, proposal_id: UUID, *, rejected_at):
        return self._update(proposal_id, status=LearningActionProposalStatus.REJECTED, rejected_at=rejected_at)

    async def mark_edited(self, proposal_id: UUID, *, parameters, approval_payload):
        return self._update(
            proposal_id, status=LearningActionProposalStatus.EDITED, parameters=parameters,
            approval_payload=approval_payload,
        )

    async def mark_executing(self, proposal_id: UUID, *, executed_at):
        return self._update(proposal_id, status=LearningActionProposalStatus.EXECUTING, executed_at=executed_at)

    async def mark_succeeded(self, proposal_id: UUID, *, completed_at, result_reference):
        return self._update(
            proposal_id, status=LearningActionProposalStatus.SUCCEEDED, completed_at=completed_at,
            result_reference=result_reference,
        )

    async def mark_failed(self, proposal_id: UUID, *, completed_at):
        return self._update(proposal_id, status=LearningActionProposalStatus.FAILED, completed_at=completed_at)

    async def list_for_run(self, run_id: UUID) -> list[LearningActionProposal]:
        return [p for p in self.proposals.values() if p.run_id == run_id]


class FakeEvidenceItemRepo:
    """Spec G2D2 section 17: `synthesize_research_response` reloads
    evidence from PostgreSQL rather than trusting the resume payload -
    this fake stands in for `uow.evidence_items` in those tests."""

    def __init__(self, *, items_by_run: dict[UUID, list[Any]] | None = None) -> None:
        self.items_by_run = items_by_run or {}

    async def list_for_run(self, run_id: UUID) -> list[Any]:
        return self.items_by_run.get(run_id, [])


class FakeUnitOfWork:
    """A minimal `UnitOfWorkPort` stand-in exposing the Phase 12
    repositories plus (spec G2D2) `evidence_items` - sufficient for every
    orchestrator unit test, since none of them touch any other repository."""

    def __init__(
        self, *, threads: FakeThreadRepo | None = None, runs: FakeRunRepo | None = None,
        events: FakeEventRepo | None = None, actions: FakeActionRepo | None = None,
        evidence_items: FakeEvidenceItemRepo | None = None,
    ) -> None:
        self.learning_orchestrator_threads = threads or FakeThreadRepo()
        self.learning_orchestrator_runs = runs or FakeRunRepo()
        self.learning_orchestrator_events = events or FakeEventRepo()
        self.learning_orchestrator_actions = actions or FakeActionRepo()
        self.evidence_items = evidence_items or FakeEvidenceItemRepo()

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False

    async def commit(self) -> None:
        pass


class FakeLockPort:
    """Always grants the lock immediately - concurrency/contention is
    tested separately in integration tests against real Redis."""

    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.released: list[str] = []

    async def acquire(self, *, key: str, owner_id: str, ttl_seconds: int, wait_timeout_seconds: int) -> bool:
        self.acquired.append(key)
        return True

    async def extend(self, *, key: str, owner_id: str, ttl_seconds: int) -> bool:
        return True

    async def release(self, *, key: str, owner_id: str) -> bool:
        self.released.append(key)
        return True


class FakeMetrics:
    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str] | None]] = []
        self.gauges: list[tuple[str, float]] = []
        self.histograms: list[tuple[str, float]] = []

    def increment_counter(self, name: str, *, value: float = 1.0, labels=None) -> None:
        self.counters.append((name, labels))

    def set_gauge(self, name: str, value: float, *, labels=None) -> None:
        self.gauges.append((name, value))

    def observe_histogram(self, name: str, value: float, *, labels=None) -> None:
        self.histograms.append((name, value))

    def time_operation(self, name: str, *, labels=None):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()


class FakeTracing:
    def start_span(self, name: str, *, attributes=None):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _cm():
            yield

        return _cm()


class FakeGraphRuntime:
    """A scripted `LearningGraphRuntimePort` - the test supplies the
    exact `(state, interrupt_reason)` result(s) `start_run`/`resume_run`
    should return (`interrupt_reason` is `"approval"`, `"research"`, or
    `None`), and optionally the exact SSE event sequence `stream_run`/
    `stream_resume` should yield, so orchestrator-service tests never
    need a real LangGraph graph or checkpointer."""

    def __init__(
        self, *, result: tuple[dict, str | None] | None = None, error: Exception | None = None,
        stream_events: list[dict] | None = None, stream_side_effect=None,
    ) -> None:
        self.result = result or ({"step_count": 1}, None)
        self.error = error
        self.stream_events = stream_events if stream_events is not None else [{"type": "run_completed"}]
        #: Optional `async def(run_id: str) -> None` invoked after the
        #: last scripted stream event, before the generator ends -
        #: simulates a graph node's own direct durable write (e.g.
        #: `request_live_research` calling `mark_waiting_for_research`)
        #: happening mid-stream, before `_stream_and_finalize` reads
        #: `get_state`/calls `_finalize_run`.
        self.stream_side_effect = stream_side_effect
        self.start_run_calls: list[dict] = []
        self.resume_run_calls: list[dict] = []
        self.cancelled_threads: list[str] = []

    async def start_run(self, *, thread_id, run_id, initial_state):
        self.start_run_calls.append({"thread_id": thread_id, "run_id": run_id, "initial_state": initial_state})
        if self.error is not None:
            raise self.error
        return self.result

    def stream_run(self, *, thread_id, run_id, initial_state):
        async def _gen():
            if self.error is not None:
                raise self.error
            for event in self.stream_events:
                yield event
            if self.stream_side_effect is not None:
                await self.stream_side_effect(run_id)

        return _gen()

    async def resume_run(self, *, thread_id, run_id, resume_value):
        self.resume_run_calls.append({"thread_id": thread_id, "run_id": run_id, "resume_value": resume_value})
        if self.error is not None:
            raise self.error
        return self.result

    def stream_resume(self, *, thread_id, run_id, resume_value):
        async def _gen():
            if self.error is not None:
                raise self.error
            for event in self.stream_events:
                yield event
            if self.stream_side_effect is not None:
                await self.stream_side_effect(run_id)

        return _gen()

    async def get_state(self, *, thread_id):
        return self.result[0]

    async def get_state_history(self, *, thread_id, limit=20):
        return []

    async def cancel_run(self, *, thread_id):
        self.cancelled_threads.append(thread_id)


class FakeTutorService:
    """Duck-types `GroundedAITutorService.create_conversation`/`.ask`
    (subgraphs.py calls these directly on a concrete `GroundedAITutorService`
    instance, not a Protocol, so a plain duck-typed fake is sufficient) -
    used by route-level graph tests that don't need real retrieval/model
    calls, only a shaped `TutorResponse`-like result."""

    def __init__(
        self, *, answer_markdown: str = "Fake grounded answer.", grounding_status: GroundingStatus = GroundingStatus.GROUNDED,
    ) -> None:
        self.answer_markdown = answer_markdown
        self.grounding_status = grounding_status
        self.asked_questions: list[str] = []

    async def create_conversation(self, *, learner_id: UUID, context: Any) -> SimpleNamespace:
        return SimpleNamespace(conversation_id=uuid4())

    async def ask(self, *, conversation_id: UUID, question: str, context: Any = None) -> SimpleNamespace:
        self.asked_questions.append(question)
        return SimpleNamespace(
            citations=[],
            answer=SimpleNamespace(answer_markdown=self.answer_markdown, grounding_status=self.grounding_status),
        )


class FakeContextLoader:
    """A `LearningContextLoaderPort` stand-in returning empty-but-shaped
    summaries - sufficient for route tests that only need
    `progress_reflection`/`adaptive_recommendation` to execute without
    a real database."""

    async def load_dashboard(self, learner_id: UUID) -> dict[str, Any]:
        return {}

    async def load_mastery_summary(self, learner_id: UUID) -> list[dict[str, Any]]:
        return []

    async def load_progress_summary(self, learner_id: UUID) -> list[dict[str, Any]]:
        return []

    async def load_active_misconceptions(self, learner_id: UUID) -> list[dict[str, Any]]:
        return []

    async def load_due_review_summary(self, learner_id: UUID) -> list[dict[str, Any]]:
        return []

    async def load_lesson_metadata(self, *, learner_id: UUID, lesson_id: UUID) -> dict[str, Any]:
        return {}
