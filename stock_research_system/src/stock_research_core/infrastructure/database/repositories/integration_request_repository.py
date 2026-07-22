"""SQLAlchemy repository for `IntegrationRequest` replay-protection records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.operations.enums import IntegrationRequestStatus
from stock_research_core.domain.operations.models import IntegrationRequest
from stock_research_core.infrastructure.database.mappers.operations_mappers import integration_request_orm_to_domain
from stock_research_core.infrastructure.database.orm.integration_request import IntegrationRequestORM


class SqlAlchemyIntegrationRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, request: IntegrationRequest) -> IntegrationRequest:
        row = IntegrationRequestORM(
            request_id=request.request_id,
            integration_id=request.integration_id,
            external_request_id=request.external_request_id,
            idempotency_key=request.idempotency_key,
            job_id=request.job_id,
            status=request.status.value,
            request_hash=request.request_hash,
            correlation_id=request.correlation_id,
            received_at=request.received_at,
            completed_at=request.completed_at,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(
                f"Could not create integration request: external_request_id "
                f"'{request.external_request_id}' was already used by this integration client."
            ) from exc
        return integration_request_orm_to_domain(row)

    async def get_by_external_request_id(
        self, *, integration_id: UUID, external_request_id: str
    ) -> IntegrationRequest | None:
        statement = select(IntegrationRequestORM).where(
            IntegrationRequestORM.integration_id == integration_id,
            IntegrationRequestORM.external_request_id == external_request_id,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return integration_request_orm_to_domain(row) if row is not None else None

    async def mark_completed(self, request_id: UUID, *, job_id: UUID, completed_at: datetime) -> IntegrationRequest:
        row = await self._get_or_raise(request_id)
        row.status = IntegrationRequestStatus.COMPLETED.value
        row.job_id = job_id
        row.completed_at = completed_at
        await self._session.flush()
        return integration_request_orm_to_domain(row)

    async def mark_failed(self, request_id: UUID, *, completed_at: datetime) -> IntegrationRequest:
        row = await self._get_or_raise(request_id)
        row.status = IntegrationRequestStatus.FAILED.value
        row.completed_at = completed_at
        await self._session.flush()
        return integration_request_orm_to_domain(row)

    async def _get_or_raise(self, request_id: UUID) -> IntegrationRequestORM:
        row = await self._session.get(IntegrationRequestORM, request_id)
        if row is None:
            raise PersistenceError(f"No integration request found with id '{request_id}'.")
        return row
