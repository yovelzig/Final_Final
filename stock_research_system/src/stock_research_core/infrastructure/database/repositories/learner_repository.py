"""SQLAlchemy repository for `LearnerProfile` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.infrastructure.database.mappers.learning_mappers import (
    learner_profile_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.learner_profile import LearnerProfileORM


class SqlAlchemyLearnerRepository:
    """Persists and retrieves `LearnerProfile` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, learner: LearnerProfile) -> LearnerProfile:
        row = LearnerProfileORM(
            learner_id=learner.learner_id,
            display_name=learner.display_name,
            preferred_language=learner.preferred_language,
            financial_experience_level=learner.financial_experience_level.value,
            daily_goal_minutes=learner.daily_goal_minutes,
            active=learner.active,
        )
        self._session.add(row)
        await self._session.flush()
        return learner_profile_orm_to_domain(row)

    async def get(self, learner_id: UUID) -> LearnerProfile | None:
        row = await self._session.get(LearnerProfileORM, learner_id)
        return learner_profile_orm_to_domain(row) if row is not None else None

    async def update(self, learner: LearnerProfile) -> LearnerProfile:
        row = await self._get_or_raise(learner.learner_id)
        row.display_name = learner.display_name
        row.preferred_language = learner.preferred_language
        row.financial_experience_level = learner.financial_experience_level.value
        row.daily_goal_minutes = learner.daily_goal_minutes
        row.active = learner.active
        await self._session.flush()
        # `updated_at` is server-computed (onupdate=func.now()); refresh it
        # explicitly so reading it below doesn't trigger an implicit,
        # non-async-safe lazy load.
        await self._session.refresh(row)
        return learner_profile_orm_to_domain(row)

    async def set_active(self, learner_id: UUID, active: bool) -> LearnerProfile:
        row = await self._get_or_raise(learner_id)
        row.active = active
        await self._session.flush()
        await self._session.refresh(row)
        return learner_profile_orm_to_domain(row)

    async def _get_or_raise(self, learner_id: UUID) -> LearnerProfileORM:
        row = await self._session.get(LearnerProfileORM, learner_id)
        if row is None:
            raise PersistenceError(f"No learner found with id '{learner_id}'.")
        return row
