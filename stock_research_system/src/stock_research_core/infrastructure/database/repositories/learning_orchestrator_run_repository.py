"""SQLAlchemy repository for `LearningOrchestratorRun` persistence.

PostgreSQL is the sole source of truth for run state - the LangGraph
checkpointer is orchestration runtime state only (see
`infrastructure.learning_orchestrator.postgres_checkpointer`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus
from stock_research_core.domain.learning_orchestrator.models import LearningOrchestratorRun
from stock_research_core.infrastructure.database.mappers.learning_orchestrator_mappers import (
    learning_orchestrator_run_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.learning_orchestrator_run import LearningOrchestratorRunORM


class SqlAlchemyLearningOrchestratorRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: LearningOrchestratorRun) -> LearningOrchestratorRun:
        row = LearningOrchestratorRunORM(
            run_id=run.run_id, thread_id=run.thread_id, learner_id=run.learner_id,
            input_message_id=run.input_message_id, output_tutor_answer_id=run.output_tutor_answer_id,
            status=run.status.value, intent=run.intent.value if run.intent else None,
            route=run.route.value if run.route else None, idempotency_key=run.idempotency_key,
            correlation_id=run.correlation_id, step_count=run.step_count, maximum_steps=run.maximum_steps,
            started_at=run.started_at, waiting_at=run.waiting_at, completed_at=run.completed_at,
            cancelled_at=run.cancelled_at, failure_code=run.failure_code, failure_message=run.failure_message,
            graph_version=run.graph_version,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(
                f"Could not create run: idempotency key '{run.idempotency_key}' already used on this thread."
            ) from exc
        return learning_orchestrator_run_orm_to_domain(row)

    async def get_by_id(self, run_id: UUID) -> LearningOrchestratorRun | None:
        row = await self._session.get(LearningOrchestratorRunORM, run_id)
        return learning_orchestrator_run_orm_to_domain(row) if row is not None else None

    async def get_for_update(self, run_id: UUID) -> LearningOrchestratorRun | None:
        statement = select(LearningOrchestratorRunORM).where(LearningOrchestratorRunORM.run_id == run_id).with_for_update()
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return learning_orchestrator_run_orm_to_domain(row) if row is not None else None

    async def get_by_idempotency_key(self, *, thread_id: UUID, idempotency_key: str) -> LearningOrchestratorRun | None:
        statement = select(LearningOrchestratorRunORM).where(
            LearningOrchestratorRunORM.thread_id == thread_id,
            LearningOrchestratorRunORM.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return learning_orchestrator_run_orm_to_domain(row) if row is not None else None

    def _update(self, row: LearningOrchestratorRunORM, **updates: object) -> None:
        for key, value in updates.items():
            setattr(row, key, value)

    async def mark_running(self, run_id: UUID, *, started_at: datetime) -> LearningOrchestratorRun:
        row = await self._get_or_raise(run_id)
        self._update(row, status=LearningOrchestratorRunStatus.RUNNING.value, started_at=started_at)
        await self._session.flush()
        await self._session.refresh(row)
        return learning_orchestrator_run_orm_to_domain(row)

    async def mark_waiting_for_learner(self, run_id: UUID, *, waiting_at: datetime) -> LearningOrchestratorRun:
        row = await self._get_or_raise(run_id)
        self._update(row, status=LearningOrchestratorRunStatus.WAITING_FOR_LEARNER.value, waiting_at=waiting_at)
        await self._session.flush()
        await self._session.refresh(row)
        return learning_orchestrator_run_orm_to_domain(row)

    async def update_progress(
        self, run_id: UUID, *, step_count: int, intent: str | None = None, route: str | None = None
    ) -> LearningOrchestratorRun:
        row = await self._get_or_raise(run_id)
        row.step_count = step_count
        if intent is not None:
            row.intent = intent
        if route is not None:
            row.route = route
        await self._session.flush()
        await self._session.refresh(row)
        return learning_orchestrator_run_orm_to_domain(row)

    async def mark_succeeded(
        self, run_id: UUID, *, completed_at: datetime, output_tutor_answer_id: UUID | None
    ) -> LearningOrchestratorRun:
        row = await self._get_or_raise(run_id)
        self._update(
            row, status=LearningOrchestratorRunStatus.SUCCEEDED.value, completed_at=completed_at,
            output_tutor_answer_id=output_tutor_answer_id,
        )
        await self._session.flush()
        await self._session.refresh(row)
        return learning_orchestrator_run_orm_to_domain(row)

    async def mark_failed(
        self, run_id: UUID, *, completed_at: datetime, failure_code: str, failure_message: str
    ) -> LearningOrchestratorRun:
        row = await self._get_or_raise(run_id)
        self._update(
            row, status=LearningOrchestratorRunStatus.FAILED.value, completed_at=completed_at,
            failure_code=failure_code[:100], failure_message=failure_message[:1000],
        )
        await self._session.flush()
        await self._session.refresh(row)
        return learning_orchestrator_run_orm_to_domain(row)

    async def mark_cancelled(self, run_id: UUID, *, cancelled_at: datetime) -> LearningOrchestratorRun:
        row = await self._get_or_raise(run_id)
        self._update(row, status=LearningOrchestratorRunStatus.CANCELLED.value, cancelled_at=cancelled_at)
        await self._session.flush()
        await self._session.refresh(row)
        return learning_orchestrator_run_orm_to_domain(row)

    async def list_for_thread(self, thread_id: UUID, *, limit: int = 50, offset: int = 0) -> list[LearningOrchestratorRun]:
        statement = (
            select(LearningOrchestratorRunORM)
            .where(LearningOrchestratorRunORM.thread_id == thread_id)
            .order_by(LearningOrchestratorRunORM.created_at.desc())
            .limit(limit).offset(offset)
        )
        result = await self._session.execute(statement)
        return [learning_orchestrator_run_orm_to_domain(row) for row in result.scalars().all()]

    async def _get_or_raise(self, run_id: UUID) -> LearningOrchestratorRunORM:
        row = await self._session.get(LearningOrchestratorRunORM, run_id)
        if row is None:
            raise PersistenceError(f"No learning-orchestrator run found with id '{run_id}'.")
        return row
