"""SQLAlchemy repository for `IntegrationClient` persistence (n8n API-key clients)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.operations.enums import IntegrationClientStatus
from stock_research_core.domain.operations.models import IntegrationClient
from stock_research_core.infrastructure.database.mappers.operations_mappers import integration_client_orm_to_domain
from stock_research_core.infrastructure.database.orm.integration_client import (
    IntegrationClientAllowedJobTypeORM,
    IntegrationClientORM,
)


class SqlAlchemyIntegrationClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, client: IntegrationClient) -> IntegrationClient:
        row = IntegrationClientORM(
            integration_id=client.integration_id,
            name=client.name,
            key_id=client.key_id,
            api_key_hash=client.api_key_hash,
            status=client.status.value,
            last_used_at=client.last_used_at,
        )
        self._session.add(row)
        try:
            # Flushed separately from the allowed-job-type rows below: with
            # no ORM `relationship()` linking the two tables (deliberately -
            # this repository only needs plain FK columns), SQLAlchemy's
            # dependency sort cannot infer that the parent must be inserted
            # first, so an unordered single flush can emit the child insert
            # before the parent and fail its foreign key constraint.
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(f"Could not create integration client: key ID '{client.key_id}' already exists.") from exc

        for job_type in client.allowed_job_types:
            self._session.add(
                IntegrationClientAllowedJobTypeORM(integration_id=client.integration_id, job_type=job_type.value)
            )
        await self._session.flush()
        return await self._load(row)

    async def get_by_key_id(self, key_id: str) -> IntegrationClient | None:
        statement = select(IntegrationClientORM).where(IntegrationClientORM.key_id == key_id)
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return await self._load(row) if row is not None else None

    async def get_by_id(self, integration_id: UUID) -> IntegrationClient | None:
        row = await self._session.get(IntegrationClientORM, integration_id)
        return await self._load(row) if row is not None else None

    async def update_last_used(self, integration_id: UUID, *, last_used_at: datetime) -> IntegrationClient:
        row = await self._get_or_raise(integration_id)
        row.last_used_at = last_used_at
        await self._session.flush()
        await self._session.refresh(row)
        return await self._load(row)

    async def set_status(self, integration_id: UUID, *, status: IntegrationClientStatus) -> IntegrationClient:
        row = await self._get_or_raise(integration_id)
        row.status = status.value
        await self._session.flush()
        await self._session.refresh(row)
        return await self._load(row)

    async def list_clients(self) -> list[IntegrationClient]:
        statement = select(IntegrationClientORM).order_by(IntegrationClientORM.created_at.asc())
        result = await self._session.execute(statement)
        return [await self._load(row) for row in result.scalars().all()]

    async def _load(self, row: IntegrationClientORM) -> IntegrationClient:
        statement = select(IntegrationClientAllowedJobTypeORM.job_type).where(
            IntegrationClientAllowedJobTypeORM.integration_id == row.integration_id
        )
        result = await self._session.execute(statement)
        allowed = list(result.scalars().all())
        return integration_client_orm_to_domain(row, allowed)

    async def _get_or_raise(self, integration_id: UUID) -> IntegrationClientORM:
        row = await self._session.get(IntegrationClientORM, integration_id)
        if row is None:
            raise PersistenceError(f"No integration client found with id '{integration_id}'.")
        return row
