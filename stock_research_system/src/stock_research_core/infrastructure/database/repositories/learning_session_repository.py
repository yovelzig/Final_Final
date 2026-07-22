"""SQLAlchemy repository for `LearningSession` / `LearningSessionActivity` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.adaptive_learning.enums import LearningSessionStatus
from stock_research_core.domain.adaptive_learning.models import (
    LearningSession,
    LearningSessionActivity,
)
from stock_research_core.infrastructure.database.mappers.adaptive_learning_mappers import (
    learning_session_activity_orm_to_domain,
    learning_session_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.learning_session import LearningSessionORM
from stock_research_core.infrastructure.database.orm.learning_session_activity import (
    LearningSessionActivityORM,
)


class SqlAlchemyLearningSessionRepository:
    """Persists and queries `LearningSession` and `LearningSessionActivity` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(self, session: LearningSession) -> LearningSession:
        row = LearningSessionORM(
            session_id=session.session_id,
            learner_id=session.learner_id,
            session_type=session.session_type.value,
            status=session.status.value,
            goal_minutes=session.goal_minutes,
            started_at=session.started_at,
            last_activity_at=session.last_activity_at,
            completed_at=session.completed_at,
            abandoned_at=session.abandoned_at,
            recommended_item_count=session.recommended_item_count,
            completed_item_count=session.completed_item_count,
            correct_item_count=session.correct_item_count,
            total_score=session.total_score,
            maximum_score=session.maximum_score,
            policy_version=session.policy_version,
        )
        self._session.add(row)
        await self._session.flush()
        return learning_session_orm_to_domain(row)

    async def get_session(self, session_id: UUID) -> LearningSession | None:
        row = await self._session.get(LearningSessionORM, session_id)
        return learning_session_orm_to_domain(row) if row is not None else None

    async def update_session(self, session: LearningSession) -> LearningSession:
        row = await self._session.get(LearningSessionORM, session.session_id)
        if row is None:
            raise PersistenceError(f"No learning session found with id '{session.session_id}'.")
        row.status = session.status.value
        row.goal_minutes = session.goal_minutes
        row.last_activity_at = session.last_activity_at
        row.completed_at = session.completed_at
        row.abandoned_at = session.abandoned_at
        row.recommended_item_count = session.recommended_item_count
        row.completed_item_count = session.completed_item_count
        row.correct_item_count = session.correct_item_count
        row.total_score = session.total_score
        row.maximum_score = session.maximum_score
        await self._session.flush()
        await self._session.refresh(row)
        return learning_session_orm_to_domain(row)

    async def list_active_sessions(self, learner_id: UUID) -> list[LearningSession]:
        active_statuses = (
            LearningSessionStatus.STARTED.value,
            LearningSessionStatus.ACTIVE.value,
        )
        statement = select(LearningSessionORM).where(
            LearningSessionORM.learner_id == learner_id,
            LearningSessionORM.status.in_(active_statuses),
        )
        result = await self._session.execute(statement)
        return [learning_session_orm_to_domain(row) for row in result.scalars().all()]

    async def add_activity(self, activity: LearningSessionActivity) -> LearningSessionActivity:
        row = LearningSessionActivityORM(
            activity_id=activity.activity_id,
            session_id=activity.session_id,
            learner_id=activity.learner_id,
            exercise_id=activity.exercise_id,
            attempt_id=activity.attempt_id,
            decision_id=activity.decision_id,
            position=activity.position,
            recommended_at=activity.recommended_at,
            started_at=activity.started_at,
            completed_at=activity.completed_at,
            skipped_at=activity.skipped_at,
        )
        self._session.add(row)
        await self._session.flush()
        return learning_session_activity_orm_to_domain(row)

    async def get_activity(self, activity_id: UUID) -> LearningSessionActivity | None:
        row = await self._session.get(LearningSessionActivityORM, activity_id)
        return learning_session_activity_orm_to_domain(row) if row is not None else None

    async def get_activity_by_decision(self, decision_id: UUID) -> LearningSessionActivity | None:
        statement = select(LearningSessionActivityORM).where(
            LearningSessionActivityORM.decision_id == decision_id
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return learning_session_activity_orm_to_domain(row) if row is not None else None

    async def update_activity(self, activity: LearningSessionActivity) -> LearningSessionActivity:
        row = await self._session.get(LearningSessionActivityORM, activity.activity_id)
        if row is None:
            raise PersistenceError(f"No session activity found with id '{activity.activity_id}'.")
        row.attempt_id = activity.attempt_id
        row.started_at = activity.started_at
        row.completed_at = activity.completed_at
        row.skipped_at = activity.skipped_at
        await self._session.flush()
        return learning_session_activity_orm_to_domain(row)

    async def list_activities(self, session_id: UUID) -> list[LearningSessionActivity]:
        statement = (
            select(LearningSessionActivityORM)
            .where(LearningSessionActivityORM.session_id == session_id)
            .order_by(LearningSessionActivityORM.position.asc())
        )
        result = await self._session.execute(statement)
        return [learning_session_activity_orm_to_domain(row) for row in result.scalars().all()]
