"""SQLAlchemy repository for `LearningOrchestratorThread` persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorThreadStatus
from stock_research_core.domain.learning_orchestrator.models import LearningOrchestratorThread
from stock_research_core.infrastructure.database.mappers.learning_orchestrator_mappers import (
    learning_orchestrator_thread_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.learning_orchestrator_thread import (
    LearningOrchestratorThreadORM,
)


class SqlAlchemyLearningOrchestratorThreadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, thread: LearningOrchestratorThread) -> LearningOrchestratorThread:
        row = LearningOrchestratorThreadORM(
            thread_id=thread.thread_id, learner_id=thread.learner_id, status=thread.status.value,
            title=thread.title, current_context_type=thread.current_context_type.value,
            linked_tutor_conversation_id=thread.linked_tutor_conversation_id, graph_name=thread.graph_name,
            graph_version=thread.graph_version,
        )
        self._session.add(row)
        await self._session.flush()
        return learning_orchestrator_thread_orm_to_domain(row)

    async def get_by_id(self, thread_id: UUID) -> LearningOrchestratorThread | None:
        row = await self._session.get(LearningOrchestratorThreadORM, thread_id)
        return learning_orchestrator_thread_orm_to_domain(row) if row is not None else None

    async def list_for_learner(
        self, learner_id: UUID, *, status: LearningOrchestratorThreadStatus | None = None, limit: int = 50, offset: int = 0
    ) -> list[LearningOrchestratorThread]:
        statement = select(LearningOrchestratorThreadORM).where(LearningOrchestratorThreadORM.learner_id == learner_id)
        if status is not None:
            statement = statement.where(LearningOrchestratorThreadORM.status == status.value)
        statement = statement.order_by(LearningOrchestratorThreadORM.updated_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(statement)
        return [learning_orchestrator_thread_orm_to_domain(row) for row in result.scalars().all()]

    async def count_for_learner(
        self, learner_id: UUID, *, status: LearningOrchestratorThreadStatus | None = None
    ) -> int:
        statement = select(func.count()).select_from(LearningOrchestratorThreadORM).where(
            LearningOrchestratorThreadORM.learner_id == learner_id
        )
        if status is not None:
            statement = statement.where(LearningOrchestratorThreadORM.status == status.value)
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def close(self, thread_id: UUID, *, closed_at: datetime) -> LearningOrchestratorThread:
        row = await self._get_or_raise(thread_id)
        row.status = LearningOrchestratorThreadStatus.CLOSED.value
        row.closed_at = closed_at
        await self._session.flush()
        await self._session.refresh(row)
        return learning_orchestrator_thread_orm_to_domain(row)

    async def touch(self, thread_id: UUID, *, updated_at: datetime) -> LearningOrchestratorThread:
        row = await self._get_or_raise(thread_id)
        row.updated_at = updated_at
        await self._session.flush()
        await self._session.refresh(row)
        return learning_orchestrator_thread_orm_to_domain(row)

    async def _get_or_raise(self, thread_id: UUID) -> LearningOrchestratorThreadORM:
        row = await self._session.get(LearningOrchestratorThreadORM, thread_id)
        if row is None:
            raise PersistenceError(f"No learning-orchestrator thread found with id '{thread_id}'.")
        return row
