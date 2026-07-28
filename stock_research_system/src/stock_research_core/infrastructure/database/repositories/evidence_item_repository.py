"""SQLAlchemy repository for `EvidenceItem` persistence.

`EvidenceItem` rows are immutable once created - this repository exposes
no mutator methods, only `create`/`get`/`get_by_content_hash`/`list_for_run`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.live_research.models import EvidenceItem
from stock_research_core.infrastructure.database.mappers.live_research_mappers import (
    evidence_item_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.evidence_item import EvidenceItemORM


class SqlAlchemyEvidenceItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: EvidenceItem) -> EvidenceItem:
        row = EvidenceItemORM(
            evidence_id=item.evidence_id,
            run_id=item.run_id,
            source_type=item.source_type.value,
            classification=item.classification.value,
            source_url=str(item.source_url) if item.source_url else None,
            official_identifier=item.official_identifier,
            source_title=item.source_title,
            publisher=item.publisher,
            retrieved_at=item.retrieved_at,
            published_at=item.published_at,
            raw_excerpt=item.raw_excerpt,
            normalized_text=item.normalized_text,
            content_hash=item.content_hash,
            structured_facts=item.structured_facts,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(
                f"Could not create evidence item: run '{item.run_id}' already has an evidence item "
                f"with content_hash '{item.content_hash}'."
            ) from exc
        return evidence_item_orm_to_domain(row)

    async def get(self, evidence_id: UUID) -> EvidenceItem | None:
        row = await self._session.get(EvidenceItemORM, evidence_id)
        return evidence_item_orm_to_domain(row) if row is not None else None

    async def get_by_content_hash(self, run_id: UUID, content_hash: str) -> EvidenceItem | None:
        statement = select(EvidenceItemORM).where(
            EvidenceItemORM.run_id == run_id, EvidenceItemORM.content_hash == content_hash
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return evidence_item_orm_to_domain(row) if row is not None else None

    async def list_for_run(self, run_id: UUID) -> list[EvidenceItem]:
        statement = (
            select(EvidenceItemORM)
            .where(EvidenceItemORM.run_id == run_id)
            .order_by(EvidenceItemORM.retrieved_at.asc())
        )
        result = await self._session.execute(statement)
        return [evidence_item_orm_to_domain(row) for row in result.scalars().all()]

    async def list_page_for_run(self, run_id: UUID, *, limit: int, offset: int) -> list[EvidenceItem]:
        """Applies `LIMIT`/`OFFSET` in SQL (Phase G2C) - never loads every
        evidence row for a run and slices in Python. `evidence_id` is an
        added, stable tiebreaker after `retrieved_at` so a page never
        skips or repeats a row when two items share the same timestamp."""
        statement = (
            select(EvidenceItemORM)
            .where(EvidenceItemORM.run_id == run_id)
            .order_by(EvidenceItemORM.retrieved_at.asc(), EvidenceItemORM.evidence_id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(statement)
        return [evidence_item_orm_to_domain(row) for row in result.scalars().all()]
