"""SQLAlchemy repository for `ResearchRun` persistence.

`ResearchRunStatus` terminal statuses (COMPLETED/FAILED/CANCELLED) never
transition again - every mutator here is called only after the service
layer has already checked the run's current status (see
`ResearchRequestService`); this repository does not re-check legality,
it only persists the requested change.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError, ResearchRunNotFoundError
from stock_research_core.domain.live_research.enums import FailureCategory, ResearchRunStatus
from stock_research_core.domain.live_research.models import ResearchRun
from stock_research_core.infrastructure.database.mappers.live_research_mappers import (
    research_run_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.research_run import ResearchRunORM

_ACTIVE_STATUSES = (
    ResearchRunStatus.QUEUED.value,
    ResearchRunStatus.RUNNING.value,
)


class SqlAlchemyResearchRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: ResearchRun) -> ResearchRun:
        row = ResearchRunORM(
            run_id=run.run_id,
            request_id=run.request_id,
            attempt_number=run.attempt_number,
            status=run.status.value,
            failure_category=run.failure_category.value if run.failure_category else None,
            failure_message=run.failure_message,
            retryable=run.retryable,
            provider_metadata=run.provider_metadata,
            queued_at=run.queued_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            cancelled_at=run.cancelled_at,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(
                f"Could not create research run: request '{run.request_id}' already has a run with "
                f"attempt_number {run.attempt_number}, or already has a non-terminal run."
            ) from exc
        return research_run_orm_to_domain(row)

    async def get(self, run_id: UUID, *, for_update: bool = False) -> ResearchRun | None:
        statement = select(ResearchRunORM).where(ResearchRunORM.run_id == run_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return research_run_orm_to_domain(row) if row is not None else None

    async def get_active_run_for_request(self, request_id: UUID) -> ResearchRun | None:
        statement = select(ResearchRunORM).where(
            ResearchRunORM.request_id == request_id,
            ResearchRunORM.status.in_(_ACTIVE_STATUSES),
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return research_run_orm_to_domain(row) if row is not None else None

    async def get_max_attempt_number(self, request_id: UUID) -> int:
        statement = select(func.max(ResearchRunORM.attempt_number)).where(
            ResearchRunORM.request_id == request_id
        )
        result = await self._session.execute(statement)
        value = result.scalar_one_or_none()
        return int(value) if value is not None else 0

    async def list_for_request(self, request_id: UUID) -> list[ResearchRun]:
        statement = (
            select(ResearchRunORM)
            .where(ResearchRunORM.request_id == request_id)
            .order_by(ResearchRunORM.attempt_number.asc())
        )
        result = await self._session.execute(statement)
        return [research_run_orm_to_domain(row) for row in result.scalars().all()]

    async def mark_running(self, run_id: UUID, *, started_at: datetime) -> ResearchRun:
        row = await self._get_or_raise(run_id)
        row.status = ResearchRunStatus.RUNNING.value
        row.started_at = started_at
        await self._session.flush()
        await self._session.refresh(row)
        return research_run_orm_to_domain(row)

    async def mark_completed(self, run_id: UUID, *, completed_at: datetime) -> ResearchRun:
        row = await self._get_or_raise(run_id)
        row.status = ResearchRunStatus.COMPLETED.value
        row.completed_at = completed_at
        await self._session.flush()
        await self._session.refresh(row)
        return research_run_orm_to_domain(row)

    async def mark_failed(
        self,
        run_id: UUID,
        *,
        completed_at: datetime,
        failure_category: FailureCategory,
        failure_message: str,
        retryable: bool,
    ) -> ResearchRun:
        row = await self._get_or_raise(run_id)
        row.status = ResearchRunStatus.FAILED.value
        row.completed_at = completed_at
        row.failure_category = failure_category.value
        row.failure_message = failure_message
        row.retryable = retryable
        await self._session.flush()
        await self._session.refresh(row)
        return research_run_orm_to_domain(row)

    async def mark_cancelled(self, run_id: UUID, *, cancelled_at: datetime) -> ResearchRun:
        row = await self._get_or_raise(run_id)
        row.status = ResearchRunStatus.CANCELLED.value
        row.cancelled_at = cancelled_at
        row.completed_at = cancelled_at
        await self._session.flush()
        await self._session.refresh(row)
        return research_run_orm_to_domain(row)

    async def _get_or_raise(self, run_id: UUID) -> ResearchRunORM:
        row = await self._session.get(ResearchRunORM, run_id)
        if row is None:
            raise ResearchRunNotFoundError(f"No research run found with id '{run_id}'.")
        return row
