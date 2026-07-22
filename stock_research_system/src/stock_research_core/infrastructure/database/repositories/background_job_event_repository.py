"""SQLAlchemy repository for immutable `BackgroundJobEvent` records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.operations.models import BackgroundJobEvent
from stock_research_core.infrastructure.database.mappers.operations_mappers import background_job_event_orm_to_domain
from stock_research_core.infrastructure.database.orm.background_job_event import BackgroundJobEventORM


class SqlAlchemyBackgroundJobEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: BackgroundJobEvent) -> BackgroundJobEvent:
        row = BackgroundJobEventORM(
            event_id=event.event_id,
            job_id=event.job_id,
            attempt_id=event.attempt_id,
            event_type=event.event_type.value,
            message=event.message,
            event_metadata=event.metadata,
            correlation_id=event.correlation_id,
        )
        self._session.add(row)
        await self._session.flush()
        return background_job_event_orm_to_domain(row)

    async def list_for_job(self, job_id: UUID) -> list[BackgroundJobEvent]:
        #: Deterministic order per spec: creation time, then event ID.
        statement = (
            select(BackgroundJobEventORM)
            .where(BackgroundJobEventORM.job_id == job_id)
            .order_by(BackgroundJobEventORM.created_at.asc(), BackgroundJobEventORM.event_id.asc())
        )
        result = await self._session.execute(statement)
        return [background_job_event_orm_to_domain(row) for row in result.scalars().all()]
