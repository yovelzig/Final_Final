"""Application-level Protocol contracts for the Phase 12 personalized
learning orchestrator.

Pure `Protocol` definitions describing what the orchestrator's
persistence, context-loading, action-execution, and graph-runtime
layers do, not how. No LangGraph, SQLAlchemy, or psycopg import is
allowed here; concrete implementations live under
`stock_research_core.infrastructure.learning_orchestrator` and
`stock_research_core.infrastructure.database`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator, Protocol
from uuid import UUID

from stock_research_core.application.learning_orchestrator.state import LearningCoachGraphState
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorThreadStatus
from stock_research_core.domain.learning_orchestrator.models import (
    IntentClassification,
    LearningActionProposal,
    LearningOrchestratorEvent,
    LearningOrchestratorRun,
    LearningOrchestratorThread,
)


class LearningIntentClassifierPort(Protocol):
    async def classify(
        self,
        *,
        learner_id: UUID,
        user_input: str,
        context_type: Any,
        context_references: dict[str, UUID],
    ) -> IntentClassification: ...


class LearningContextLoaderPort(Protocol):
    """Loads sanitized, ownership-checked, bounded summaries from
    existing FinQuest application services - never a direct SQLAlchemy
    query in the application layer."""

    async def load_dashboard(self, learner_id: UUID) -> dict[str, Any]: ...

    async def load_mastery_summary(self, learner_id: UUID) -> list[dict[str, Any]]: ...

    async def load_progress_summary(self, learner_id: UUID) -> list[dict[str, Any]]: ...

    async def load_active_misconceptions(self, learner_id: UUID) -> list[dict[str, Any]]: ...

    async def load_due_review_summary(self, learner_id: UUID) -> list[dict[str, Any]]: ...

    async def load_lesson_metadata(self, *, learner_id: UUID, lesson_id: UUID) -> dict[str, Any]: ...

    async def load_exercise_metadata(self, *, learner_id: UUID, exercise_id: UUID) -> dict[str, Any]: ...

    async def load_scenario_metadata(
        self, *, learner_id: UUID, scenario_id: UUID, submission_id: UUID | None
    ) -> dict[str, Any]: ...

    async def load_portfolio_overview(self, *, learner_id: UUID, portfolio_id: UUID) -> dict[str, Any]: ...


class LearningActionExecutorPort(Protocol):
    """Executes exactly one proposal from the closed `LearningActionType`
    allow-list. There is no code path here for a trade, a market-data
    job, an operational job, an n8n workflow, or an admin action."""

    async def execute(self, *, learner_id: UUID, proposal: LearningActionProposal) -> dict[str, Any]: ...


class LearningGraphRuntimePort(Protocol):
    """The application layer's only window into LangGraph - it never
    imports `AsyncPostgresSaver` or any LangGraph type directly."""

    async def start_run(
        self, *, thread_id: str, run_id: str, initial_state: LearningCoachGraphState
    ) -> tuple[LearningCoachGraphState, bool]:
        """Run the graph to completion or to its first interrupt.
        Returns `(state, is_waiting_for_learner)`."""
        ...

    def stream_run(
        self, *, thread_id: str, run_id: str, initial_state: LearningCoachGraphState
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield learner-safe streaming events as the graph executes."""
        ...

    async def resume_run(
        self, *, thread_id: str, run_id: str, resume_value: dict[str, Any]
    ) -> tuple[LearningCoachGraphState, bool]:
        ...

    def stream_resume(
        self, *, thread_id: str, run_id: str, resume_value: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def get_state(self, *, thread_id: str) -> LearningCoachGraphState | None: ...

    async def get_state_history(self, *, thread_id: str, limit: int = 20) -> list[dict[str, Any]]: ...

    async def cancel_run(self, *, thread_id: str) -> None: ...


# -- repositories -----------------------------------------------


class LearningOrchestratorThreadRepositoryPort(Protocol):
    async def create(self, thread: LearningOrchestratorThread) -> LearningOrchestratorThread: ...

    async def get_by_id(self, thread_id: UUID) -> LearningOrchestratorThread | None: ...

    async def list_for_learner(
        self, learner_id: UUID, *, status: LearningOrchestratorThreadStatus | None = None, limit: int = 50, offset: int = 0
    ) -> list[LearningOrchestratorThread]: ...

    async def count_for_learner(
        self, learner_id: UUID, *, status: LearningOrchestratorThreadStatus | None = None
    ) -> int: ...

    async def close(self, thread_id: UUID, *, closed_at: datetime) -> LearningOrchestratorThread: ...

    async def touch(self, thread_id: UUID, *, updated_at: datetime) -> LearningOrchestratorThread: ...


class LearningOrchestratorRunRepositoryPort(Protocol):
    async def create(self, run: LearningOrchestratorRun) -> LearningOrchestratorRun: ...

    async def get_by_id(self, run_id: UUID) -> LearningOrchestratorRun | None: ...

    async def get_for_update(self, run_id: UUID) -> LearningOrchestratorRun | None: ...

    async def get_by_idempotency_key(self, *, thread_id: UUID, idempotency_key: str) -> LearningOrchestratorRun | None: ...

    async def mark_running(self, run_id: UUID, *, started_at: datetime) -> LearningOrchestratorRun: ...

    async def mark_waiting_for_learner(self, run_id: UUID, *, waiting_at: datetime) -> LearningOrchestratorRun: ...

    async def update_progress(
        self, run_id: UUID, *, step_count: int, intent: str | None = None, route: str | None = None
    ) -> LearningOrchestratorRun: ...

    async def mark_succeeded(
        self, run_id: UUID, *, completed_at: datetime, output_tutor_answer_id: UUID | None
    ) -> LearningOrchestratorRun: ...

    async def mark_failed(
        self, run_id: UUID, *, completed_at: datetime, failure_code: str, failure_message: str
    ) -> LearningOrchestratorRun: ...

    async def mark_cancelled(self, run_id: UUID, *, cancelled_at: datetime) -> LearningOrchestratorRun: ...

    async def list_for_thread(self, thread_id: UUID, *, limit: int = 50, offset: int = 0) -> list[LearningOrchestratorRun]: ...


class LearningOrchestratorEventRepositoryPort(Protocol):
    async def append(self, event: LearningOrchestratorEvent) -> LearningOrchestratorEvent: ...

    async def list_for_run(self, run_id: UUID) -> list[LearningOrchestratorEvent]: ...

    async def next_sequence_number(self, run_id: UUID) -> int: ...


class LearningOrchestratorActionRepositoryPort(Protocol):
    async def create(self, proposal: LearningActionProposal) -> LearningActionProposal: ...

    async def get_by_id(self, proposal_id: UUID) -> LearningActionProposal | None: ...

    async def get_for_update(self, proposal_id: UUID) -> LearningActionProposal | None: ...

    async def get_by_idempotency_key(self, *, run_id: UUID, idempotency_key: str) -> LearningActionProposal | None: ...

    async def mark_waiting_for_approval(self, proposal_id: UUID) -> LearningActionProposal: ...

    async def mark_approved(
        self, proposal_id: UUID, *, approved_at: datetime, approval_payload: dict[str, Any] | None
    ) -> LearningActionProposal: ...

    async def mark_rejected(self, proposal_id: UUID, *, rejected_at: datetime) -> LearningActionProposal: ...

    async def mark_edited(
        self, proposal_id: UUID, *, parameters: dict[str, Any], approval_payload: dict[str, Any] | None
    ) -> LearningActionProposal: ...

    async def mark_executing(self, proposal_id: UUID, *, executed_at: datetime) -> LearningActionProposal: ...

    async def mark_succeeded(
        self, proposal_id: UUID, *, completed_at: datetime, result_reference: dict[str, Any]
    ) -> LearningActionProposal: ...

    async def mark_failed(self, proposal_id: UUID, *, completed_at: datetime) -> LearningActionProposal: ...

    async def list_for_run(self, run_id: UUID) -> list[LearningActionProposal]: ...
