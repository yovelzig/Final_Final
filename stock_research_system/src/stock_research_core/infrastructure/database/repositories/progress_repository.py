"""SQLAlchemy repository for `UserProgress` persistence.

A row targets exactly one granularity (path, module, or lesson);
`upsert` picks the matching partial unique index as its conflict
target based on which ID is set (see the `UserProgressORM` docstring).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.learning.models import UserProgress
from stock_research_core.infrastructure.database.mappers.learning_mappers import (
    user_progress_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.user_progress import UserProgressORM


class SqlAlchemyProgressRepository:
    """Persists and queries `UserProgress` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, progress: UserProgress) -> UserProgress:
        target_column: str
        index_where: ColumnElement[bool]
        if progress.lesson_id is not None:
            target_column, index_where = "lesson_id", UserProgressORM.lesson_id.isnot(None)
        elif progress.module_id is not None:
            target_column, index_where = "module_id", UserProgressORM.module_id.isnot(None)
        elif progress.path_id is not None:
            target_column, index_where = "path_id", UserProgressORM.path_id.isnot(None)
        else:  # pragma: no cover - blocked by UserProgress's own validator
            raise PersistenceError("UserProgress must set path_id, module_id, or lesson_id.")

        insert_stmt = pg_insert(UserProgressORM).values(
            progress_id=progress.progress_id,
            learner_id=progress.learner_id,
            path_id=progress.path_id,
            module_id=progress.module_id,
            lesson_id=progress.lesson_id,
            status=progress.status.value,
            completion_percentage=progress.completion_percentage,
            best_score=progress.best_score,
            attempt_count=progress.attempt_count,
            first_started_at=progress.first_started_at,
            completed_at=progress.completed_at,
            last_activity_at=progress.last_activity_at,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["learner_id", target_column],
            index_where=index_where,
            set_={
                "status": insert_stmt.excluded.status,
                "completion_percentage": insert_stmt.excluded.completion_percentage,
                "best_score": insert_stmt.excluded.best_score,
                "attempt_count": insert_stmt.excluded.attempt_count,
                "first_started_at": insert_stmt.excluded.first_started_at,
                "completed_at": insert_stmt.excluded.completed_at,
                "last_activity_at": insert_stmt.excluded.last_activity_at,
                "updated_at": func.now(),
            },
        ).returning(UserProgressORM.progress_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()
        row = await self._session.get(UserProgressORM, canonical_id)
        assert row is not None
        return user_progress_orm_to_domain(row)

    async def get_lesson_progress(self, learner_id: UUID, lesson_id: UUID) -> UserProgress | None:
        statement = select(UserProgressORM).where(
            UserProgressORM.learner_id == learner_id, UserProgressORM.lesson_id == lesson_id
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return user_progress_orm_to_domain(row) if row is not None else None

    async def list_for_learner(self, learner_id: UUID) -> list[UserProgress]:
        statement = select(UserProgressORM).where(UserProgressORM.learner_id == learner_id)
        result = await self._session.execute(statement)
        return [user_progress_orm_to_domain(row) for row in result.scalars().all()]
