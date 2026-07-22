"""SQLAlchemy repository for `BackgroundJob` persistence.

PostgreSQL is the sole source of truth for job state - every state
transition method here does exactly one thing (mark queued / running /
succeeded / failed / retry-scheduled / cancelled) and returns the freshly
mapped domain object, so callers never have to guess what changed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import BackgroundJobNotFoundError, PersistenceError
from stock_research_core.domain.operations.enums import BackgroundJobStatus, BackgroundJobType
from stock_research_core.domain.operations.models import BackgroundJob
from stock_research_core.domain.operations.sanitization import contains_traceback, find_sensitive_keys
from stock_research_core.infrastructure.database.mappers.operations_mappers import background_job_orm_to_domain
from stock_research_core.infrastructure.database.orm.background_job import BackgroundJobORM


def _requester_key(*, account_id: UUID | None, integration_id: UUID | None, trigger_source: str) -> str:
    if account_id is not None:
        return f"account:{account_id}"
    if integration_id is not None:
        return f"integration:{integration_id}"
    return f"source:{trigger_source}"


def _ensure_safe_summary(result_summary: dict[str, Any] | None) -> None:
    if result_summary is None:
        return
    sensitive = find_sensitive_keys(result_summary)
    if sensitive:
        raise PersistenceError(f"Refusing to persist a job result summary containing sensitive fields: {sensitive}")
    if contains_traceback(result_summary):
        raise PersistenceError("Refusing to persist a job result summary containing a raw traceback.")


class SqlAlchemyBackgroundJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job: BackgroundJob) -> BackgroundJob:
        requester_key = _requester_key(
            account_id=job.requested_by_account_id,
            integration_id=job.requested_by_integration_id,
            trigger_source=job.trigger_source.value,
        )
        row = BackgroundJobORM(
            job_id=job.job_id,
            job_type=job.job_type.value,
            status=job.status.value,
            priority=job.priority.value,
            trigger_source=job.trigger_source.value,
            requested_by_account_id=job.requested_by_account_id,
            requested_by_integration_id=job.requested_by_integration_id,
            requester_key=requester_key,
            idempotency_key=job.idempotency_key,
            resource_key=job.resource_key,
            parameters=job.parameters,
            result_summary=job.result_summary,
            progress_current=job.progress_current,
            progress_total=job.progress_total,
            progress_message=job.progress_message,
            attempt_count=job.attempt_count,
            maximum_attempts=job.maximum_attempts,
            queue_name=job.queue_name,
            task_name=job.task_name,
            task_id=job.task_id,
            available_at=job.available_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            cancelled_at=job.cancelled_at,
            job_version=job.job_version,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(
                f"Could not create background job: an identical job (same type, trigger source, "
                f"requester, and idempotency key '{job.idempotency_key}') already exists."
            ) from exc
        return background_job_orm_to_domain(row)

    async def get_by_id(self, job_id: UUID) -> BackgroundJob | None:
        row = await self._session.get(BackgroundJobORM, job_id)
        return background_job_orm_to_domain(row) if row is not None else None

    async def get_for_update(self, job_id: UUID) -> BackgroundJob | None:
        statement = select(BackgroundJobORM).where(BackgroundJobORM.job_id == job_id).with_for_update()
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return background_job_orm_to_domain(row) if row is not None else None

    async def get_by_idempotency_key(
        self,
        *,
        job_type: BackgroundJobType,
        trigger_source: str,
        requested_by_account_id: UUID | None,
        requested_by_integration_id: UUID | None,
        idempotency_key: str,
    ) -> BackgroundJob | None:
        requester_key = _requester_key(
            account_id=requested_by_account_id, integration_id=requested_by_integration_id, trigger_source=trigger_source
        )
        statement = select(BackgroundJobORM).where(
            BackgroundJobORM.job_type == job_type.value,
            BackgroundJobORM.trigger_source == trigger_source,
            BackgroundJobORM.requester_key == requester_key,
            BackgroundJobORM.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return background_job_orm_to_domain(row) if row is not None else None

    async def mark_queued(self, job_id: UUID, *, task_id: str) -> BackgroundJob:
        row = await self._get_or_raise(job_id)
        row.status = BackgroundJobStatus.QUEUED.value
        row.task_id = task_id
        await self._session.flush()
        await self._session.refresh(row)
        return background_job_orm_to_domain(row)

    async def mark_running(self, job_id: UUID, *, started_at: datetime) -> BackgroundJob:
        row = await self._get_or_raise(job_id)
        row.status = BackgroundJobStatus.RUNNING.value
        row.started_at = started_at
        row.attempt_count = row.attempt_count + 1
        await self._session.flush()
        await self._session.refresh(row)
        return background_job_orm_to_domain(row)

    async def update_progress(
        self, job_id: UUID, *, current: int, total: int | None, message: str | None
    ) -> BackgroundJob:
        row = await self._get_or_raise(job_id)
        row.progress_current = current
        if total is not None:
            row.progress_total = total
        if message is not None:
            row.progress_message = message
        await self._session.flush()
        await self._session.refresh(row)
        return background_job_orm_to_domain(row)

    async def mark_succeeded(
        self, job_id: UUID, *, completed_at: datetime, result_summary: dict[str, Any]
    ) -> BackgroundJob:
        _ensure_safe_summary(result_summary)
        row = await self._get_or_raise(job_id)
        row.status = BackgroundJobStatus.SUCCEEDED.value
        row.completed_at = completed_at
        row.result_summary = result_summary
        await self._session.flush()
        await self._session.refresh(row)
        return background_job_orm_to_domain(row)

    async def mark_failed(
        self, job_id: UUID, *, completed_at: datetime, result_summary: dict[str, Any] | None
    ) -> BackgroundJob:
        _ensure_safe_summary(result_summary)
        row = await self._get_or_raise(job_id)
        row.status = BackgroundJobStatus.FAILED.value
        row.completed_at = completed_at
        if result_summary is not None:
            row.result_summary = result_summary
        await self._session.flush()
        await self._session.refresh(row)
        return background_job_orm_to_domain(row)

    async def mark_retry_scheduled(
        self, job_id: UUID, *, available_at: datetime, result_summary: dict[str, Any] | None
    ) -> BackgroundJob:
        _ensure_safe_summary(result_summary)
        row = await self._get_or_raise(job_id)
        row.status = BackgroundJobStatus.RETRY_SCHEDULED.value
        row.available_at = available_at
        if result_summary is not None:
            row.result_summary = result_summary
        await self._session.flush()
        await self._session.refresh(row)
        return background_job_orm_to_domain(row)

    async def mark_cancelled(self, job_id: UUID, *, cancelled_at: datetime) -> BackgroundJob:
        row = await self._get_or_raise(job_id)
        row.status = BackgroundJobStatus.CANCELLED.value
        row.cancelled_at = cancelled_at
        row.completed_at = cancelled_at
        await self._session.flush()
        await self._session.refresh(row)
        return background_job_orm_to_domain(row)

    async def list_jobs(
        self,
        *,
        job_type: BackgroundJobType | None = None,
        status: BackgroundJobStatus | None = None,
        trigger_source: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        requested_by_integration_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BackgroundJob]:
        statement = self._filtered_statement(
            job_type=job_type, status=status, trigger_source=trigger_source, created_after=created_after,
            created_before=created_before, requested_by_integration_id=requested_by_integration_id,
        )
        statement = statement.order_by(BackgroundJobORM.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(statement)
        return [background_job_orm_to_domain(row) for row in result.scalars().all()]

    async def count_jobs(
        self,
        *,
        job_type: BackgroundJobType | None = None,
        status: BackgroundJobStatus | None = None,
        trigger_source: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        requested_by_integration_id: UUID | None = None,
    ) -> int:
        statement = self._filtered_statement(
            job_type=job_type, status=status, trigger_source=trigger_source, created_after=created_after,
            created_before=created_before, requested_by_integration_id=requested_by_integration_id,
        )
        count_statement = select(func.count()).select_from(statement.subquery())
        result = await self._session.execute(count_statement)
        return int(result.scalar_one())

    async def list_stale_running_job_ids(self, *, older_than: datetime, limit: int = 1000) -> list[UUID]:
        statement = (
            select(BackgroundJobORM.job_id)
            .where(BackgroundJobORM.status == BackgroundJobStatus.RUNNING.value, BackgroundJobORM.started_at < older_than)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    def _filtered_statement(
        self,
        *,
        job_type: BackgroundJobType | None,
        status: BackgroundJobStatus | None,
        trigger_source: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
        requested_by_integration_id: UUID | None,
    ):
        statement = select(BackgroundJobORM)
        if job_type is not None:
            statement = statement.where(BackgroundJobORM.job_type == job_type.value)
        if status is not None:
            statement = statement.where(BackgroundJobORM.status == status.value)
        if trigger_source is not None:
            statement = statement.where(BackgroundJobORM.trigger_source == trigger_source)
        if created_after is not None:
            statement = statement.where(BackgroundJobORM.created_at >= created_after)
        if created_before is not None:
            statement = statement.where(BackgroundJobORM.created_at <= created_before)
        if requested_by_integration_id is not None:
            statement = statement.where(BackgroundJobORM.requested_by_integration_id == requested_by_integration_id)
        return statement

    async def _get_or_raise(self, job_id: UUID) -> BackgroundJobORM:
        row = await self._session.get(BackgroundJobORM, job_id)
        if row is None:
            raise BackgroundJobNotFoundError(f"No background job found with id '{job_id}'.")
        return row
