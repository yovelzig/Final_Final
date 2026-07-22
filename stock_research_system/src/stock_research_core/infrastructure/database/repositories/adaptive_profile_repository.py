"""SQLAlchemy repository for `ExerciseAdaptiveProfile` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.adaptive_learning.models import ExerciseAdaptiveProfile
from stock_research_core.infrastructure.database.mappers.adaptive_learning_mappers import (
    exercise_adaptive_profile_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.exercise_adaptive_profile import (
    ExerciseAdaptiveProfileORM,
)


class SqlAlchemyAdaptiveProfileRepository:
    """Persists and queries `ExerciseAdaptiveProfile` rows. Unique per exercise."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, profile: ExerciseAdaptiveProfile) -> ExerciseAdaptiveProfile:
        insert_stmt = pg_insert(ExerciseAdaptiveProfileORM).values(
            profile_id=profile.profile_id,
            exercise_id=profile.exercise_id,
            base_difficulty_score=profile.base_difficulty_score,
            estimated_seconds=profile.estimated_seconds,
            diagnostic_eligible=profile.diagnostic_eligible,
            review_eligible=profile.review_eligible,
            remediation_eligible=profile.remediation_eligible,
            minimum_mastery_score=profile.minimum_mastery_score,
            maximum_mastery_score=profile.maximum_mastery_score,
            recommended_prerequisite_skill_ids=profile.recommended_prerequisite_skill_ids,
            policy_tags=profile.policy_tags,
            active=profile.active,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["exercise_id"],
            set_={
                "base_difficulty_score": insert_stmt.excluded.base_difficulty_score,
                "estimated_seconds": insert_stmt.excluded.estimated_seconds,
                "diagnostic_eligible": insert_stmt.excluded.diagnostic_eligible,
                "review_eligible": insert_stmt.excluded.review_eligible,
                "remediation_eligible": insert_stmt.excluded.remediation_eligible,
                "minimum_mastery_score": insert_stmt.excluded.minimum_mastery_score,
                "maximum_mastery_score": insert_stmt.excluded.maximum_mastery_score,
                "recommended_prerequisite_skill_ids": (
                    insert_stmt.excluded.recommended_prerequisite_skill_ids
                ),
                "policy_tags": insert_stmt.excluded.policy_tags,
                "active": insert_stmt.excluded.active,
                "updated_at": func.now(),
            },
        ).returning(ExerciseAdaptiveProfileORM.profile_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()
        row = await self._session.get(ExerciseAdaptiveProfileORM, canonical_id)
        assert row is not None
        return exercise_adaptive_profile_orm_to_domain(row)

    async def get_by_exercise(self, exercise_id: UUID) -> ExerciseAdaptiveProfile | None:
        statement = select(ExerciseAdaptiveProfileORM).where(
            ExerciseAdaptiveProfileORM.exercise_id == exercise_id
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return exercise_adaptive_profile_orm_to_domain(row) if row is not None else None

    async def list_active(
        self, diagnostic_only: bool = False, review_only: bool = False
    ) -> list[ExerciseAdaptiveProfile]:
        statement = select(ExerciseAdaptiveProfileORM).where(
            ExerciseAdaptiveProfileORM.active.is_(True)
        )
        if diagnostic_only:
            statement = statement.where(ExerciseAdaptiveProfileORM.diagnostic_eligible.is_(True))
        if review_only:
            statement = statement.where(ExerciseAdaptiveProfileORM.review_eligible.is_(True))
        result = await self._session.execute(statement)
        return [exercise_adaptive_profile_orm_to_domain(row) for row in result.scalars().all()]
