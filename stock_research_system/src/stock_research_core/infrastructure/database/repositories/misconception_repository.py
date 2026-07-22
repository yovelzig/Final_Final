"""SQLAlchemy repository for `Misconception` persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.learning.enums import MisconceptionStatus
from stock_research_core.domain.learning.models import Misconception
from stock_research_core.infrastructure.database.mappers.learning_mappers import (
    misconception_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.misconception import (
    MisconceptionEvidenceAttemptORM,
    MisconceptionORM,
)


class SqlAlchemyMisconceptionRepository:
    """Persists and queries `Misconception` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, misconception: Misconception) -> Misconception:
        insert_stmt = pg_insert(MisconceptionORM).values(
            misconception_id=misconception.misconception_id,
            learner_id=misconception.learner_id,
            skill_id=misconception.skill_id,
            code=misconception.code,
            description=misconception.description,
            status=misconception.status.value,
            confidence_score=misconception.confidence_score,
            first_detected_at=misconception.first_detected_at,
            last_detected_at=misconception.last_detected_at,
            resolved_at=misconception.resolved_at,
            detector_version=misconception.detector_version,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["misconception_id"],
            set_={
                "learner_id": insert_stmt.excluded.learner_id,
                "skill_id": insert_stmt.excluded.skill_id,
                "code": insert_stmt.excluded.code,
                "description": insert_stmt.excluded.description,
                "status": insert_stmt.excluded.status,
                "confidence_score": insert_stmt.excluded.confidence_score,
                "first_detected_at": insert_stmt.excluded.first_detected_at,
                "last_detected_at": insert_stmt.excluded.last_detected_at,
                "resolved_at": insert_stmt.excluded.resolved_at,
                "detector_version": insert_stmt.excluded.detector_version,
            },
        )
        await self._session.execute(statement)

        existing_evidence = await self._session.execute(
            select(MisconceptionEvidenceAttemptORM.attempt_id).where(
                MisconceptionEvidenceAttemptORM.misconception_id == misconception.misconception_id
            )
        )
        existing_ids = set(existing_evidence.scalars().all())
        for attempt_id in misconception.evidence_attempt_ids:
            if attempt_id not in existing_ids:
                self._session.add(
                    MisconceptionEvidenceAttemptORM(
                        misconception_id=misconception.misconception_id, attempt_id=attempt_id
                    )
                )
        await self._session.flush()

        row = await self._session.get(MisconceptionORM, misconception.misconception_id)
        assert row is not None
        return misconception_orm_to_domain(row, list(misconception.evidence_attempt_ids))

    async def list_active(self, learner_id: UUID) -> list[Misconception]:
        statement = select(MisconceptionORM).where(
            MisconceptionORM.learner_id == learner_id,
            MisconceptionORM.status == MisconceptionStatus.ACTIVE.value,
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        return [
            misconception_orm_to_domain(row, await self._load_evidence(row.misconception_id))
            for row in rows
        ]

    async def resolve(self, misconception_id: UUID, resolved_at: datetime) -> Misconception:
        row = await self._session.get(MisconceptionORM, misconception_id)
        if row is None:
            raise PersistenceError(f"No misconception found with id '{misconception_id}'.")
        row.status = MisconceptionStatus.RESOLVED.value
        row.resolved_at = resolved_at
        await self._session.flush()
        evidence = await self._load_evidence(misconception_id)
        return misconception_orm_to_domain(row, evidence)

    async def _load_evidence(self, misconception_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(MisconceptionEvidenceAttemptORM.attempt_id).where(
                MisconceptionEvidenceAttemptORM.misconception_id == misconception_id
            )
        )
        return list(result.scalars().all())
