"""SQLAlchemy repository for `ResearchRequest` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.live_research.hashing import requester_key as _derive_requester_key
from stock_research_core.domain.live_research.models import ResearchRequest
from stock_research_core.infrastructure.database.mappers.live_research_mappers import (
    research_request_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.research_request import ResearchRequestORM


class SqlAlchemyResearchRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, request: ResearchRequest) -> ResearchRequest:
        requester_key = _derive_requester_key(
            account_id=request.requested_by_account_id,
            integration_id=request.requested_by_integration_id,
        )
        row = ResearchRequestORM(
            request_id=request.request_id,
            requested_by_account_id=request.requested_by_account_id,
            requested_by_integration_id=request.requested_by_integration_id,
            requester_key=requester_key,
            original_question=request.original_question,
            normalized_query=request.normalized_query,
            subject_security_id=request.subject_security_id,
            subject_raw_text=request.subject_raw_text,
            scope=request.scope.value,
            idempotency_key=request.idempotency_key,
            request_hash=request.request_hash,
            created_at=request.created_at,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(
                f"Could not create research request: an identical request (same requester and "
                f"idempotency key '{request.idempotency_key}') already exists."
            ) from exc
        return research_request_orm_to_domain(row)

    async def get(self, request_id: UUID) -> ResearchRequest | None:
        row = await self._session.get(ResearchRequestORM, request_id)
        return research_request_orm_to_domain(row) if row is not None else None

    async def get_for_update(self, request_id: UUID) -> ResearchRequest | None:
        statement = (
            select(ResearchRequestORM)
            .where(ResearchRequestORM.request_id == request_id)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return research_request_orm_to_domain(row) if row is not None else None

    async def get_by_idempotency_key(
        self, *, requester_key: str, idempotency_key: str
    ) -> ResearchRequest | None:
        statement = select(ResearchRequestORM).where(
            ResearchRequestORM.requester_key == requester_key,
            ResearchRequestORM.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return research_request_orm_to_domain(row) if row is not None else None
