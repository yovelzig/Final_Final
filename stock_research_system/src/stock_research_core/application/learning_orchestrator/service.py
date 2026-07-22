"""`PersonalizedLearningOrchestratorService`: the single application-layer
entry point for the Phase 12 learning coach (spec section 23).

Owns the parts of the workflow the graph itself must never own: thread/
run lifecycle and ownership checks, the per-thread distributed lock
(spec section 18 - "one active graph run per thread"), idempotency-key
deduplication, and translating `LearningGraphRuntimePort` results into
durable `LearningOrchestratorRun`/`Event` rows. The graph
(`graph_builder`/`nodes`/`subgraphs`) owns everything *inside* one run;
this service owns everything *around* it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Callable
from uuid import UUID, uuid4

from stock_research_core.application.exceptions import (
    LearningActionProposalAlreadyDecidedError,
    LearningActionProposalExpiredError,
    LearningActionProposalNotFoundError,
    LearningOrchestratorRunNotCancellableError,
    LearningOrchestratorRunNotFoundError,
    LearningOrchestratorRunNotWaitingError,
    LearningOrchestratorThreadClosedError,
    LearningOrchestratorThreadNotFoundError,
    LockAcquisitionError,
)
from stock_research_core.application.learning_orchestrator.event_stream import error_event
from stock_research_core.application.learning_orchestrator.models import (
    ACTION_PARAMETER_MODELS,
    LearningApprovalRequest,
)
from stock_research_core.application.learning_orchestrator.ports import LearningGraphRuntimePort
from stock_research_core.application.learning_orchestrator.state import new_state
from stock_research_core.application.operations.locking import held_lock
from stock_research_core.application.operations.ports import DistributedLockPort, MetricsPort, TracingPort
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import (
    TERMINAL_ACTION_PROPOSAL_STATUSES,
    TERMINAL_RUN_STATUSES,
    LearnerApprovalDecision,
    LearningActionProposalStatus,
    LearningOrchestratorEventType,
    LearningOrchestratorRunStatus,
    LearningOrchestratorThreadStatus,
)
from stock_research_core.domain.learning_orchestrator.models import (
    LearningOrchestratorEvent,
    LearningOrchestratorRun,
    LearningOrchestratorThread,
)
from stock_research_core.domain.models import utc_now

Clock = Callable[[], datetime]

DEFAULT_GRAPH_NAME = "finquest-learning-coach"
DEFAULT_GRAPH_VERSION = "learning-coach-graph-v1"
DEFAULT_MAX_STEPS = 30
DEFAULT_THREAD_LOCK_TTL_SECONDS = 120
DEFAULT_THREAD_LOCK_WAIT_SECONDS = 2

#: `LearningActionProposalStatus` values that mean "not yet decided" -
#: anything else means a resume for this proposal is either a replay or
#: a genuine conflict (spec section 15's approval rules).
_UNDECIDED_PROPOSAL_STATUSES = frozenset(
    {LearningActionProposalStatus.PROPOSED, LearningActionProposalStatus.WAITING_FOR_APPROVAL}
)


def learning_orchestrator_thread_resource_key(thread_id: UUID) -> str:
    return f"learning-orchestrator-thread:{thread_id}"


class PersonalizedLearningOrchestratorService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        graph_runtime: LearningGraphRuntimePort,
        lock_port: DistributedLockPort,
        metrics: MetricsPort,
        tracing: TracingPort,
        clock: Clock = utc_now,
        graph_name: str = DEFAULT_GRAPH_NAME,
        graph_version: str = DEFAULT_GRAPH_VERSION,
        max_steps: int = DEFAULT_MAX_STEPS,
        thread_lock_ttl_seconds: int = DEFAULT_THREAD_LOCK_TTL_SECONDS,
        thread_lock_wait_seconds: int = DEFAULT_THREAD_LOCK_WAIT_SECONDS,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._graph_runtime = graph_runtime
        self._lock_port = lock_port
        self._metrics = metrics
        self._tracing = tracing
        self._clock = clock
        self._graph_name = graph_name
        self._graph_version = graph_version
        self._max_steps = max_steps
        self._thread_lock_ttl_seconds = thread_lock_ttl_seconds
        self._thread_lock_wait_seconds = thread_lock_wait_seconds

    # -- threads -----------------------------------------------

    async def create_thread(
        self, *, learner_id: UUID, title: str = "New conversation",
        initial_context_type: TutorContextType = TutorContextType.GENERAL_EDUCATION,
    ) -> LearningOrchestratorThread:
        thread = LearningOrchestratorThread(
            learner_id=learner_id, title=title[:200] or "New conversation", current_context_type=initial_context_type,
            graph_name=self._graph_name, graph_version=self._graph_version,
        )
        async with self._unit_of_work_factory() as uow:
            created = await uow.learning_orchestrator_threads.create(thread)
            await uow.commit()
        return created

    async def get_thread(self, *, learner_id: UUID, thread_id: UUID) -> LearningOrchestratorThread:
        async with self._unit_of_work_factory() as uow:
            thread = await uow.learning_orchestrator_threads.get_by_id(thread_id)
        return self._owned_thread_or_raise(thread, learner_id=learner_id)

    async def list_threads(
        self, *, learner_id: UUID, status: LearningOrchestratorThreadStatus | None = None,
        limit: int = 50, offset: int = 0,
    ) -> tuple[list[LearningOrchestratorThread], int]:
        async with self._unit_of_work_factory() as uow:
            threads = await uow.learning_orchestrator_threads.list_for_learner(
                learner_id, status=status, limit=limit, offset=offset
            )
            total = await uow.learning_orchestrator_threads.count_for_learner(learner_id, status=status)
        return threads, total

    async def close_thread(self, *, learner_id: UUID, thread_id: UUID) -> LearningOrchestratorThread:
        async with self._unit_of_work_factory() as uow:
            thread = await uow.learning_orchestrator_threads.get_by_id(thread_id)
            self._owned_thread_or_raise(thread, learner_id=learner_id)
            closed = await uow.learning_orchestrator_threads.close(thread_id, closed_at=self._clock())
            await uow.commit()
        return closed

    @staticmethod
    def _owned_thread_or_raise(
        thread: LearningOrchestratorThread | None, *, learner_id: UUID
    ) -> LearningOrchestratorThread:
        if thread is None or thread.learner_id != learner_id:
            raise LearningOrchestratorThreadNotFoundError(f"No learning-coach thread found with id '{thread}'.")
        return thread

    # -- runs -----------------------------------------------

    async def get_run(self, *, learner_id: UUID, run_id: UUID) -> LearningOrchestratorRun:
        async with self._unit_of_work_factory() as uow:
            run = await uow.learning_orchestrator_runs.get_by_id(run_id)
        return self._owned_run_or_raise(run, learner_id=learner_id)

    async def list_events(self, *, learner_id: UUID, run_id: UUID) -> list[LearningOrchestratorEvent]:
        async with self._unit_of_work_factory() as uow:
            run = await uow.learning_orchestrator_runs.get_by_id(run_id)
            self._owned_run_or_raise(run, learner_id=learner_id)
            return await uow.learning_orchestrator_events.list_for_run(run_id)

    @staticmethod
    def _owned_run_or_raise(run: LearningOrchestratorRun | None, *, learner_id: UUID) -> LearningOrchestratorRun:
        if run is None or run.learner_id != learner_id:
            raise LearningOrchestratorRunNotFoundError(f"No learning-coach run found with id '{run}'.")
        return run

    async def _create_run_row(
        self, *, learner_id: UUID, thread_id: UUID, idempotency_key: str,
    ) -> tuple[LearningOrchestratorRun, bool]:
        """Returns `(run, created)` - `created=False` means an existing run
        for this idempotency key was returned instead of a new one."""
        async with self._unit_of_work_factory() as uow:
            thread = await uow.learning_orchestrator_threads.get_by_id(thread_id)
            self._owned_thread_or_raise(thread, learner_id=learner_id)
            if thread.status != LearningOrchestratorThreadStatus.ACTIVE:
                raise LearningOrchestratorThreadClosedError(f"Thread '{thread_id}' is not ACTIVE.")

            existing = await uow.learning_orchestrator_runs.get_by_idempotency_key(
                thread_id=thread_id, idempotency_key=idempotency_key
            )
            if existing is not None:
                return existing, False

            run = LearningOrchestratorRun(
                thread_id=thread_id, learner_id=learner_id, idempotency_key=idempotency_key,
                correlation_id=str(uuid4()), graph_version=self._graph_version, maximum_steps=self._max_steps,
            )
            created_run = await uow.learning_orchestrator_runs.create(run)
            await uow.learning_orchestrator_events.append(
                LearningOrchestratorEvent(
                    run_id=created_run.run_id, thread_id=thread_id, event_type=LearningOrchestratorEventType.RUN_CREATED,
                    sequence_number=1, learner_message="Run created.",
                )
            )
            await uow.commit()
            return created_run, True

    async def start_run(
        self, *, learner_id: UUID, thread_id: UUID, user_input: str, idempotency_key: str,
        context_references: dict[str, str] | None = None,
    ) -> LearningOrchestratorRun:
        run, created = await self._create_run_row(
            learner_id=learner_id, thread_id=thread_id, idempotency_key=idempotency_key
        )
        if not created:
            return run

        async with self._unit_of_work_factory() as uow:
            thread = await uow.learning_orchestrator_threads.get_by_id(thread_id)

        initial_state = new_state(
            thread_id=str(thread_id), run_id=str(run.run_id), learner_id=str(learner_id),
            correlation_id=run.correlation_id, graph_version=self._graph_version, user_input=user_input,
            requested_context_type=thread.current_context_type.value, context_references=context_references,
            maximum_steps=self._max_steps,
        )

        async with self._run_lock(thread_id=thread_id, run_id=run.run_id):
            await self._mark_running(run.run_id)
            self._metrics.set_gauge("finquest_learning_coach_runs_in_progress", 1)
            try:
                with self._metrics.time_operation("finquest_learning_coach_run_duration_seconds"):
                    async with self._tracing.start_span(
                        "learning_coach.run", attributes={"thread_id": str(thread_id), "run_id": str(run.run_id)}
                    ):
                        final_state, is_waiting = await self._graph_runtime.start_run(
                            thread_id=str(thread_id), run_id=str(run.run_id), initial_state=initial_state
                        )
            except Exception as exc:  # noqa: BLE001 - converted into a durable, sanitized FAILED run
                return await self._mark_failed(run.run_id, exc)
            return await self._finalize_run(run.run_id, final_state, is_waiting=is_waiting)

    async def stream_start_run(
        self, *, learner_id: UUID, thread_id: UUID, user_input: str, idempotency_key: str,
        context_references: dict[str, str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        run, created = await self._create_run_row(
            learner_id=learner_id, thread_id=thread_id, idempotency_key=idempotency_key
        )
        if not created:
            yield {"type": "run_completed", "run_id": str(run.run_id), "status": run.status.value}
            return

        async with self._unit_of_work_factory() as uow:
            thread = await uow.learning_orchestrator_threads.get_by_id(thread_id)

        initial_state = new_state(
            thread_id=str(thread_id), run_id=str(run.run_id), learner_id=str(learner_id),
            correlation_id=run.correlation_id, graph_version=self._graph_version, user_input=user_input,
            requested_context_type=thread.current_context_type.value, context_references=context_references,
            maximum_steps=self._max_steps,
        )

        # A client needs `run_id` to later call `/runs/{run_id}/resume` if
        # the stream ends in `approval_required` - the graph's own
        # `run_started` event (from `event_stream.py`) carries no id, so
        # this is emitted once, up front, before any graph event.
        yield {"type": "run_started", "run_id": str(run.run_id)}

        async for event in self._stream_and_finalize(
            thread_id=thread_id, run_id=run.run_id,
            stream_factory=lambda: self._graph_runtime.stream_run(
                thread_id=str(thread_id), run_id=str(run.run_id), initial_state=initial_state
            ),
        ):
            yield event

    async def resume_run(self, *, learner_id: UUID, run_id: UUID, approval: LearningApprovalRequest) -> LearningOrchestratorRun:
        run, resume_value = await self._validate_and_record_approval(learner_id=learner_id, run_id=run_id, approval=approval)
        if resume_value is None:
            return run  # idempotent replay of an already-finalized decision

        async with self._run_lock(thread_id=run.thread_id, run_id=run.run_id):
            self._metrics.increment_counter(
                "finquest_learning_coach_resumes_total", labels={"decision": approval.decision}
            )
            try:
                with self._metrics.time_operation("finquest_learning_coach_run_duration_seconds"):
                    async with self._tracing.start_span(
                        "learning_coach.resume", attributes={"thread_id": str(run.thread_id), "run_id": str(run_id)}
                    ):
                        final_state, is_waiting = await self._graph_runtime.resume_run(
                            thread_id=str(run.thread_id), run_id=str(run_id), resume_value=resume_value
                        )
            except Exception as exc:  # noqa: BLE001
                return await self._mark_failed(run_id, exc)
            return await self._finalize_run(run_id, final_state, is_waiting=is_waiting)

    async def stream_resume_run(
        self, *, learner_id: UUID, run_id: UUID, approval: LearningApprovalRequest
    ) -> AsyncIterator[dict[str, Any]]:
        run, resume_value = await self._validate_and_record_approval(learner_id=learner_id, run_id=run_id, approval=approval)
        if resume_value is None:
            yield {"type": "run_completed", "run_id": str(run.run_id), "status": run.status.value}
            return

        async for event in self._stream_and_finalize(
            thread_id=run.thread_id, run_id=run_id,
            stream_factory=lambda: self._graph_runtime.stream_resume(
                thread_id=str(run.thread_id), run_id=str(run_id), resume_value=resume_value
            ),
        ):
            yield event

    async def _validate_and_record_approval(
        self, *, learner_id: UUID, run_id: UUID, approval: LearningApprovalRequest,
    ) -> tuple[LearningOrchestratorRun, dict[str, Any] | None]:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            run = await uow.learning_orchestrator_runs.get_by_id(run_id)
            self._owned_run_or_raise(run, learner_id=learner_id)

            proposal = await uow.learning_orchestrator_actions.get_by_id(approval.proposal_id)
            if proposal is None or proposal.run_id != run_id:
                raise LearningActionProposalNotFoundError(f"No action proposal found with id '{approval.proposal_id}'.")

            if proposal.status not in _UNDECIDED_PROPOSAL_STATUSES:
                if run.status in TERMINAL_RUN_STATUSES:
                    return run, None
                raise LearningActionProposalAlreadyDecidedError(
                    f"Proposal '{proposal.proposal_id}' already has a recorded decision."
                )

            if run.status != LearningOrchestratorRunStatus.WAITING_FOR_LEARNER:
                raise LearningOrchestratorRunNotWaitingError(f"Run '{run_id}' is not waiting for learner approval.")

            if proposal.expires_at is not None and proposal.expires_at < now:
                raise LearningActionProposalExpiredError(f"Proposal '{proposal.proposal_id}' has expired.")

            resume_value: dict[str, Any] = {"decision": approval.decision}
            if approval.decision == LearnerApprovalDecision.APPROVE:
                await uow.learning_orchestrator_actions.mark_approved(
                    proposal.proposal_id, approved_at=now, approval_payload=resume_value
                )
            elif approval.decision == LearnerApprovalDecision.REJECT:
                await uow.learning_orchestrator_actions.mark_rejected(proposal.proposal_id, rejected_at=now)
            elif approval.decision == LearnerApprovalDecision.EDIT:
                model_cls = ACTION_PARAMETER_MODELS[proposal.action_type.value]
                validated = model_cls.model_validate(approval.edited_parameters or {})
                validated_parameters = validated.model_dump(mode="json")
                resume_value["edited_parameters"] = validated_parameters
                await uow.learning_orchestrator_actions.mark_edited(
                    proposal.proposal_id, parameters=validated_parameters, approval_payload=resume_value
                )
            await uow.commit()
        return run, resume_value

    async def cancel_run(self, *, learner_id: UUID, run_id: UUID) -> LearningOrchestratorRun:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            run = await uow.learning_orchestrator_runs.get_by_id(run_id)
            self._owned_run_or_raise(run, learner_id=learner_id)
            if run.status in TERMINAL_RUN_STATUSES:
                raise LearningOrchestratorRunNotCancellableError(f"Run '{run_id}' is already '{run.status.value}'.")
            cancelled = await uow.learning_orchestrator_runs.mark_cancelled(run_id, cancelled_at=now)
            sequence_number = await uow.learning_orchestrator_events.next_sequence_number(run_id)
            await uow.learning_orchestrator_events.append(
                LearningOrchestratorEvent(
                    run_id=run_id, thread_id=run.thread_id, event_type=LearningOrchestratorEventType.RUN_CANCELLED,
                    sequence_number=sequence_number, learner_message="Run cancelled.",
                )
            )
            await uow.commit()
        await self._graph_runtime.cancel_run(thread_id=str(run.thread_id))
        self._metrics.increment_counter("finquest_learning_coach_runs_total", labels={"status": "CANCELLED"})
        self._metrics.set_gauge("finquest_learning_coach_runs_in_progress", 0)
        return cancelled

    # -- shared finalization -----------------------------------------------

    def _run_lock(self, *, thread_id: UUID, run_id: UUID):
        return held_lock(
            self._lock_port, key=learning_orchestrator_thread_resource_key(thread_id), owner_id=str(run_id),
            ttl_seconds=self._thread_lock_ttl_seconds, wait_timeout_seconds=self._thread_lock_wait_seconds,
            metrics=self._metrics,
        )

    async def _mark_running(self, run_id: UUID) -> None:
        async with self._unit_of_work_factory() as uow:
            await uow.learning_orchestrator_runs.mark_running(run_id, started_at=self._clock())
            await uow.commit()

    async def _finalize_run(
        self, run_id: UUID, final_state: dict[str, Any], *, is_waiting: bool
    ) -> LearningOrchestratorRun:
        step_count = final_state.get("step_count", 0)
        intent = (final_state.get("intent_classification") or {}).get("intent")
        route = final_state.get("selected_route")

        async with self._unit_of_work_factory() as uow:
            await uow.learning_orchestrator_runs.update_progress(run_id, step_count=step_count, intent=intent, route=route)
            if is_waiting:
                updated = await uow.learning_orchestrator_runs.mark_waiting_for_learner(run_id, waiting_at=self._clock())
                self._metrics.increment_counter("finquest_learning_coach_interrupts_total")
            else:
                proposed_action = final_state.get("proposed_action")
                updated = await uow.learning_orchestrator_runs.mark_succeeded(
                    run_id, completed_at=self._clock(), output_tutor_answer_id=None
                )
                self._metrics.increment_counter("finquest_learning_coach_runs_total", labels={"status": "SUCCEEDED"})
                if proposed_action and proposed_action.get("action_type"):
                    self._metrics.increment_counter(
                        "finquest_learning_coach_actions_total", labels={"action_type": proposed_action["action_type"]}
                    )
            await uow.commit()

        if intent:
            self._metrics.increment_counter("finquest_learning_coach_intents_total", labels={"intent": intent})
        if route:
            self._metrics.increment_counter("finquest_learning_coach_routes_total", labels={"route": route})
        self._metrics.observe_histogram("finquest_learning_coach_step_count", step_count)
        self._metrics.set_gauge("finquest_learning_coach_runs_in_progress", 0)
        return updated

    async def _mark_failed(self, run_id: UUID, exc: Exception) -> LearningOrchestratorRun:
        failure_code = type(exc).__name__
        if isinstance(exc, LockAcquisitionError):
            failure_code = "LOCK_UNAVAILABLE"
        async with self._unit_of_work_factory() as uow:
            failed = await uow.learning_orchestrator_runs.mark_failed(
                run_id, completed_at=self._clock(), failure_code=failure_code[:100],
                failure_message="The run could not be completed. Please try again.",
            )
            sequence_number = await uow.learning_orchestrator_events.next_sequence_number(run_id)
            await uow.learning_orchestrator_events.append(
                LearningOrchestratorEvent(
                    run_id=run_id, thread_id=failed.thread_id, event_type=LearningOrchestratorEventType.RUN_FAILED,
                    sequence_number=sequence_number, learner_message="Run failed.",
                )
            )
            await uow.commit()
        self._metrics.increment_counter("finquest_learning_coach_failures_total", labels={"failure_code": failure_code[:100]})
        self._metrics.increment_counter("finquest_learning_coach_runs_total", labels={"status": "FAILED"})
        self._metrics.set_gauge("finquest_learning_coach_runs_in_progress", 0)
        return failed

    async def _stream_and_finalize(
        self, *, thread_id: UUID, run_id: UUID, stream_factory: Callable[[], AsyncIterator[dict[str, Any]]],
    ) -> AsyncIterator[dict[str, Any]]:
        is_waiting = False
        final_state: dict[str, Any] = {}
        try:
            async with self._run_lock(thread_id=thread_id, run_id=run_id):
                await self._mark_running(run_id)
                self._metrics.set_gauge("finquest_learning_coach_runs_in_progress", 1)
                stream = stream_factory()
                try:
                    async for event in stream:
                        if event.get("type") == "approval_required":
                            is_waiting = True
                        if event.get("type") == "intent":
                            final_state["intent_classification"] = {"intent": event.get("intent")}
                        if event.get("type") == "route":
                            final_state["selected_route"] = event.get("route")
                        yield event
                finally:
                    # Deterministically close the LangGraph `astream` iterator
                    # on the way out - including on client-disconnect
                    # cancellation - rather than relying on GC/refcounting
                    # timing to eventually call `aclose()` for us.
                    await stream.aclose()
        except Exception as exc:  # noqa: BLE001
            await self._mark_failed(run_id, exc)
            yield error_event("The run could not be completed.")
            return

        state_snapshot = await self._graph_runtime.get_state(thread_id=str(thread_id))
        if state_snapshot is not None:
            final_state = state_snapshot
        await self._finalize_run(run_id, final_state, is_waiting=is_waiting)
