"""SQLAlchemy repository for `SkillMastery` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.learning.models import SkillMastery
from stock_research_core.infrastructure.database.mappers.learning_mappers import (
    skill_mastery_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.skill_mastery import SkillMasteryORM


class SqlAlchemyMasteryRepository:
    """Persists and queries `SkillMastery` rows. Unique per (learner, skill)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, mastery: SkillMastery) -> SkillMastery:
        insert_stmt = pg_insert(SkillMasteryORM).values(
            mastery_id=mastery.mastery_id,
            learner_id=mastery.learner_id,
            skill_id=mastery.skill_id,
            mastery_score=mastery.mastery_score,
            mastery_level=mastery.mastery_level.value,
            correct_attempts=mastery.correct_attempts,
            total_attempts=mastery.total_attempts,
            consecutive_correct=mastery.consecutive_correct,
            last_practiced_at=mastery.last_practiced_at,
            next_review_at=mastery.next_review_at,
            calculation_version=mastery.calculation_version,
        )
        statement = insert_stmt.on_conflict_do_update(
            constraint="uq_skill_mastery_learner_skill",
            set_={
                "mastery_score": insert_stmt.excluded.mastery_score,
                "mastery_level": insert_stmt.excluded.mastery_level,
                "correct_attempts": insert_stmt.excluded.correct_attempts,
                "total_attempts": insert_stmt.excluded.total_attempts,
                "consecutive_correct": insert_stmt.excluded.consecutive_correct,
                "last_practiced_at": insert_stmt.excluded.last_practiced_at,
                "next_review_at": insert_stmt.excluded.next_review_at,
                "calculation_version": insert_stmt.excluded.calculation_version,
                "updated_at": func.now(),
            },
        ).returning(SkillMasteryORM.mastery_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()
        row = await self._session.get(SkillMasteryORM, canonical_id)
        assert row is not None
        return skill_mastery_orm_to_domain(row)

    async def get(self, learner_id: UUID, skill_id: UUID) -> SkillMastery | None:
        statement = select(SkillMasteryORM).where(
            SkillMasteryORM.learner_id == learner_id, SkillMasteryORM.skill_id == skill_id
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return skill_mastery_orm_to_domain(row) if row is not None else None

    async def list_for_learner(self, learner_id: UUID) -> list[SkillMastery]:
        statement = select(SkillMasteryORM).where(SkillMasteryORM.learner_id == learner_id)
        result = await self._session.execute(statement)
        return [skill_mastery_orm_to_domain(row) for row in result.scalars().all()]
