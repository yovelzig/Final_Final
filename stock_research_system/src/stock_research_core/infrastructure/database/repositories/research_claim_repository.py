"""SQLAlchemy repository for `ResearchClaim` persistence.

Scalar claim data only - never returns or accepts evidence-ID lists. See
`claim_evidence_link_repository.py` for the claim<->evidence relationship.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import ResearchClaimNotFoundError
from stock_research_core.domain.live_research.enums import ClaimStatus
from stock_research_core.domain.live_research.models import ResearchClaim
from stock_research_core.infrastructure.database.mappers.live_research_mappers import (
    research_claim_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.research_claim import ResearchClaimORM


class SqlAlchemyResearchClaimRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, claim: ResearchClaim) -> ResearchClaim:
        row = ResearchClaimORM(
            claim_id=claim.claim_id,
            run_id=claim.run_id,
            claim_text=claim.claim_text,
            category=claim.category.value,
            status=claim.status.value,
            confidence_score=Decimal(str(claim.confidence_score)) if claim.confidence_score is not None else None,
            created_at=claim.created_at,
            updated_at=claim.updated_at,
        )
        self._session.add(row)
        await self._session.flush()
        return research_claim_orm_to_domain(row)

    async def get(self, claim_id: UUID) -> ResearchClaim | None:
        row = await self._session.get(ResearchClaimORM, claim_id)
        return research_claim_orm_to_domain(row) if row is not None else None

    async def list_for_run(self, run_id: UUID) -> list[ResearchClaim]:
        statement = (
            select(ResearchClaimORM)
            .where(ResearchClaimORM.run_id == run_id)
            .order_by(ResearchClaimORM.created_at.asc())
        )
        result = await self._session.execute(statement)
        return [research_claim_orm_to_domain(row) for row in result.scalars().all()]

    async def update_status(
        self, claim_id: UUID, status: ClaimStatus, *, confidence_score: float | None = None
    ) -> ResearchClaim:
        row = await self._session.get(ResearchClaimORM, claim_id)
        if row is None:
            raise ResearchClaimNotFoundError(f"No research claim found with id '{claim_id}'.")
        row.status = status.value
        row.confidence_score = Decimal(str(confidence_score)) if confidence_score is not None else None
        await self._session.flush()
        await self._session.refresh(row)
        return research_claim_orm_to_domain(row)
