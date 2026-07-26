"""SQLAlchemy repository for `ClaimEvidenceLink` persistence.

The sole persistence surface for the claim<->evidence relationship - no
other repository exposes evidence-ID lists.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import DuplicateClaimEvidenceLinkError
from stock_research_core.domain.live_research.enums import EvidenceStance
from stock_research_core.domain.live_research.models import ClaimEvidenceLink
from stock_research_core.infrastructure.database.mappers.live_research_mappers import (
    claim_evidence_link_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.claim_evidence_link import ClaimEvidenceLinkORM


class SqlAlchemyClaimEvidenceLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_link(self, claim_id: UUID, evidence_id: UUID, stance: EvidenceStance) -> ClaimEvidenceLink:
        link = ClaimEvidenceLink(claim_id=claim_id, evidence_id=evidence_id, stance=stance)
        row = ClaimEvidenceLinkORM(
            link_id=link.link_id,
            claim_id=link.claim_id,
            evidence_id=link.evidence_id,
            stance=link.stance.value,
            created_at=link.created_at,
            updated_at=link.updated_at,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateClaimEvidenceLinkError(
                f"Claim '{claim_id}' and evidence '{evidence_id}' are already linked."
            ) from exc
        return claim_evidence_link_orm_to_domain(row)

    async def get_link(self, claim_id: UUID, evidence_id: UUID) -> ClaimEvidenceLink | None:
        statement = select(ClaimEvidenceLinkORM).where(
            ClaimEvidenceLinkORM.claim_id == claim_id, ClaimEvidenceLinkORM.evidence_id == evidence_id
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return claim_evidence_link_orm_to_domain(row) if row is not None else None

    async def list_links_for_claim(self, claim_id: UUID) -> list[ClaimEvidenceLink]:
        statement = select(ClaimEvidenceLinkORM).where(ClaimEvidenceLinkORM.claim_id == claim_id)
        result = await self._session.execute(statement)
        return [claim_evidence_link_orm_to_domain(row) for row in result.scalars().all()]

    async def list_links_for_evidence(self, evidence_id: UUID) -> list[ClaimEvidenceLink]:
        statement = select(ClaimEvidenceLinkORM).where(ClaimEvidenceLinkORM.evidence_id == evidence_id)
        result = await self._session.execute(statement)
        return [claim_evidence_link_orm_to_domain(row) for row in result.scalars().all()]
