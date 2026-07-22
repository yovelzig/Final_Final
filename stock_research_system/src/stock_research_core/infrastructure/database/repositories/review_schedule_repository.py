"""SQLAlchemy repository for `SkillReviewSchedule` persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.adaptive_learning.models import SkillReviewSchedule
from stock_research_core.infrastructure.database.mappers.adaptive_learning_mappers import (
    skill_review_schedule_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.skill_review_schedule import (
    SkillReviewScheduleORM,
)


class SqlAlchemyReviewScheduleRepository:
    """Persists and queries `SkillReviewSchedule` rows. Unique per (learner, skill)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, schedule: SkillReviewSchedule) -> SkillReviewSchedule:
        insert_stmt = pg_insert(SkillReviewScheduleORM).values(
            schedule_id=schedule.schedule_id,
            learner_id=schedule.learner_id,
            skill_id=schedule.skill_id,
            status=schedule.status.value,
            last_reviewed_at=schedule.last_reviewed_at,
            next_review_at=schedule.next_review_at,
            review_interval_days=schedule.review_interval_days,
            successful_review_count=schedule.successful_review_count,
            failed_review_count=schedule.failed_review_count,
            consecutive_successful_reviews=schedule.consecutive_successful_reviews,
            ease_factor=schedule.ease_factor,
            calculation_version=schedule.calculation_version,
        )
        statement = insert_stmt.on_conflict_do_update(
            constraint="uq_review_schedules_learner_skill",
            set_={
                "status": insert_stmt.excluded.status,
                "last_reviewed_at": insert_stmt.excluded.last_reviewed_at,
                "next_review_at": insert_stmt.excluded.next_review_at,
                "review_interval_days": insert_stmt.excluded.review_interval_days,
                "successful_review_count": insert_stmt.excluded.successful_review_count,
                "failed_review_count": insert_stmt.excluded.failed_review_count,
                "consecutive_successful_reviews": (
                    insert_stmt.excluded.consecutive_successful_reviews
                ),
                "ease_factor": insert_stmt.excluded.ease_factor,
                "calculation_version": insert_stmt.excluded.calculation_version,
                "updated_at": func.now(),
            },
        ).returning(SkillReviewScheduleORM.schedule_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()
        row = await self._session.get(SkillReviewScheduleORM, canonical_id)
        assert row is not None
        return skill_review_schedule_orm_to_domain(row)

    async def get(self, learner_id: UUID, skill_id: UUID) -> SkillReviewSchedule | None:
        statement = select(SkillReviewScheduleORM).where(
            SkillReviewScheduleORM.learner_id == learner_id,
            SkillReviewScheduleORM.skill_id == skill_id,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return skill_review_schedule_orm_to_domain(row) if row is not None else None

    async def list_for_learner(self, learner_id: UUID) -> list[SkillReviewSchedule]:
        statement = select(SkillReviewScheduleORM).where(
            SkillReviewScheduleORM.learner_id == learner_id
        )
        result = await self._session.execute(statement)
        return [skill_review_schedule_orm_to_domain(row) for row in result.scalars().all()]

    async def list_due(self, learner_id: UUID, as_of: datetime) -> list[SkillReviewSchedule]:
        statement = select(SkillReviewScheduleORM).where(
            SkillReviewScheduleORM.learner_id == learner_id,
            SkillReviewScheduleORM.next_review_at.isnot(None),
            SkillReviewScheduleORM.next_review_at <= as_of,
        )
        result = await self._session.execute(statement)
        return [skill_review_schedule_orm_to_domain(row) for row in result.scalars().all()]
