"""SQLAlchemy repository for `BackgroundJobAttempt` persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.operations.enums import JobAttemptStatus
from stock_research_core.domain.operations.models import BackgroundJobAttempt
from stock_research_core.infrastructure.database.mappers.operations_mappers import (
    background_job_attempt_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.background_job_attempt import BackgroundJobAttemptORM


class SqlAlchemyBackgroundJobAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, attempt: BackgroundJobAttempt) -> BackgroundJobAttempt:
        row = BackgroundJobAttemptORM(
            attempt_id=attempt.attempt_id,
            job_id=attempt.job_id,
            attempt_number=attempt.attempt_number,
            status=attempt.status.value,
            worker_name=attempt.worker_name,
            celery_task_id=attempt.celery_task_id,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            error_type=attempt.error_type,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
            retry_delay_seconds=attempt.retry_delay_seconds,
        )
        self._session.add(row)
        await self._session.flush()
        return background_job_attempt_orm_to_domain(row)

    async def complete(
        self,
        attempt_id: UUID,
        *,
        status: JobAttemptStatus,
        completed_at: datetime,
        error_type: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retry_delay_seconds: int | None = None,
    ) -> BackgroundJobAttempt:
        row = await self._session.get(BackgroundJobAttemptORM, attempt_id)
        if row is None:
            raise PersistenceError(f"No background job attempt found with id '{attempt_id}'.")
        row.status = status.value
        row.completed_at = completed_at
        row.error_type = error_type
        row.error_code = error_code
        row.error_message = error_message
        row.retry_delay_seconds = retry_delay_seconds
        await self._session.flush()
        return background_job_attempt_orm_to_domain(row)

    async def list_for_job(self, job_id: UUID) -> list[BackgroundJobAttempt]:
        statement = (
            select(BackgroundJobAttemptORM)
            .where(BackgroundJobAttemptORM.job_id == job_id)
            .order_by(BackgroundJobAttemptORM.attempt_number.asc())
        )
        result = await self._session.execute(statement)
        return [background_job_attempt_orm_to_domain(row) for row in result.scalars().all()]
