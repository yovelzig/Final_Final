"""SQLAlchemy repository for `ExerciseAttempt` / `ExerciseAnswer` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.learning.models import ExerciseAnswer, ExerciseAttempt
from stock_research_core.infrastructure.database.mappers.learning_mappers import (
    exercise_answer_orm_to_domain,
    exercise_attempt_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.exercise_answer import (
    ExerciseAnswerOrderedOptionORM,
    ExerciseAnswerORM,
    ExerciseAnswerSelectedOptionORM,
)
from stock_research_core.infrastructure.database.orm.exercise_attempt import ExerciseAttemptORM


class SqlAlchemyAttemptRepository:
    """Persists and queries `ExerciseAttempt` and `ExerciseAnswer` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_attempt(self, attempt: ExerciseAttempt) -> ExerciseAttempt:
        row = ExerciseAttemptORM(
            attempt_id=attempt.attempt_id,
            learner_id=attempt.learner_id,
            exercise_id=attempt.exercise_id,
            status=attempt.status.value,
            started_at=attempt.started_at,
            submitted_at=attempt.submitted_at,
            graded_at=attempt.graded_at,
            score=attempt.score,
            maximum_score=attempt.maximum_score,
            is_correct=attempt.is_correct,
            confidence_level=attempt.confidence_level.value if attempt.confidence_level else None,
            response_time_seconds=attempt.response_time_seconds,
            attempt_number=attempt.attempt_number,
            grading_version=attempt.grading_version,
        )
        self._session.add(row)
        await self._session.flush()
        return exercise_attempt_orm_to_domain(row)

    async def get_attempt(self, attempt_id: UUID) -> ExerciseAttempt | None:
        row = await self._session.get(ExerciseAttemptORM, attempt_id)
        return exercise_attempt_orm_to_domain(row) if row is not None else None

    async def update_attempt(self, attempt: ExerciseAttempt) -> ExerciseAttempt:
        row = await self._session.get(ExerciseAttemptORM, attempt.attempt_id)
        if row is None:
            raise PersistenceError(f"No exercise attempt found with id '{attempt.attempt_id}'.")
        row.status = attempt.status.value
        row.submitted_at = attempt.submitted_at
        row.graded_at = attempt.graded_at
        row.score = attempt.score
        row.is_correct = attempt.is_correct
        row.confidence_level = attempt.confidence_level.value if attempt.confidence_level else None
        row.response_time_seconds = attempt.response_time_seconds
        row.grading_version = attempt.grading_version
        await self._session.flush()
        return exercise_attempt_orm_to_domain(row)

    async def list_attempts(
        self, learner_id: UUID, exercise_id: UUID | None = None
    ) -> list[ExerciseAttempt]:
        statement = (
            select(ExerciseAttemptORM)
            .where(ExerciseAttemptORM.learner_id == learner_id)
            .order_by(ExerciseAttemptORM.started_at.asc())
        )
        if exercise_id is not None:
            statement = statement.where(ExerciseAttemptORM.exercise_id == exercise_id)
        result = await self._session.execute(statement)
        return [exercise_attempt_orm_to_domain(row) for row in result.scalars().all()]

    async def save_answer(self, answer: ExerciseAnswer) -> ExerciseAnswer:
        row = ExerciseAnswerORM(
            answer_id=answer.answer_id,
            attempt_id=answer.attempt_id,
            numeric_answer=answer.numeric_answer,
            text_answer=answer.text_answer,
            submitted_at=answer.submitted_at,
        )
        self._session.add(row)

        for option_id in answer.selected_option_ids:
            self._session.add(
                ExerciseAnswerSelectedOptionORM(answer_id=answer.answer_id, option_id=option_id)
            )
        for index, option_id in enumerate(answer.ordered_option_ids):
            self._session.add(
                ExerciseAnswerOrderedOptionORM(
                    answer_id=answer.answer_id, option_id=option_id, sequence_index=index
                )
            )
        await self._session.flush()

        return exercise_answer_orm_to_domain(
            row, list(answer.selected_option_ids), list(answer.ordered_option_ids)
        )
