"""SQLAlchemy repository for immutable `LearningOrchestratorEvent` records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.learning_orchestrator.models import LearningOrchestratorEvent
from stock_research_core.infrastructure.database.mappers.learning_orchestrator_mappers import (
    learning_orchestrator_event_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.learning_orchestrator_event import LearningOrchestratorEventORM


class SqlAlchemyLearningOrchestratorEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: LearningOrchestratorEvent) -> LearningOrchestratorEvent:
        row = LearningOrchestratorEventORM(
            event_id=event.event_id, run_id=event.run_id, thread_id=event.thread_id,
            event_type=event.event_type.value, sequence_number=event.sequence_number,
            learner_message=event.learner_message, event_metadata=event.metadata,
        )
        self._session.add(row)
        await self._session.flush()
        return learning_orchestrator_event_orm_to_domain(row)

    async def list_for_run(self, run_id: UUID) -> list[LearningOrchestratorEvent]:
        statement = (
            select(LearningOrchestratorEventORM)
            .where(LearningOrchestratorEventORM.run_id == run_id)
            .order_by(LearningOrchestratorEventORM.sequence_number.asc())
        )
        result = await self._session.execute(statement)
        return [learning_orchestrator_event_orm_to_domain(row) for row in result.scalars().all()]

    async def next_sequence_number(self, run_id: UUID) -> int:
        statement = select(func.max(LearningOrchestratorEventORM.sequence_number)).where(
            LearningOrchestratorEventORM.run_id == run_id
        )
        result = await self._session.execute(statement)
        current_max = result.scalar_one_or_none()
        return (current_max or 0) + 1
