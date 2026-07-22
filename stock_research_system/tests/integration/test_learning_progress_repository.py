"""PostgreSQL integration tests: ProgressRepository, end-to-end submission,
transaction rollback, and a check that existing market tables are untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.application.learning.service import LearningService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import (
    AttemptStatus,
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
    ProgressStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    LearnerProfile,
    Lesson,
    LearningModule,
    LearningPath,
    Skill,
    ExerciseOption,
    UserProgress,
)
from stock_research_core.domain.models import Security

pytestmark = pytest.mark.integration


async def _seed_learner_and_lesson(uow_factory):
    learner = LearnerProfile(display_name="Amit")
    skill = Skill(
        code="DIVERSIFICATION",
        name="Diversification",
        description="desc",
        category=FinancialSkillCategory.DIVERSIFICATION,
        difficulty=DifficultyLevel.BEGINNER,
    )
    path = LearningPath(
        code="investing-foundations",
        title="Investing Foundations",
        description="desc",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        estimated_minutes=60,
        published=True,
    )
    module = LearningModule(
        path_id=path.path_id,
        code="diversification-module",
        title="Diversification",
        description="desc",
        position=0,
        estimated_minutes=30,
        published=True,
    )
    lesson = Lesson(
        module_id=module.module_id,
        code="why-diversification-matters",
        title="Why Diversification Matters",
        summary="summary",
        content_markdown="# content",
        difficulty=DifficultyLevel.BEGINNER,
        status=LessonStatus.PUBLISHED,
        position=0,
        estimated_minutes=15,
        primary_skill_id=skill.skill_id,
    )
    exercise = Exercise(
        lesson_id=lesson.lesson_id,
        exercise_type=ExerciseType.TRUE_FALSE,
        prompt="Diversification guarantees no losses.",
        explanation="explanation",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        skill_ids=[skill.skill_id],
        maximum_score=1.0,
        passing_score=1.0,
    )
    true_option = ExerciseOption(
        exercise_id=exercise.exercise_id, option_key="true", content="True", position=0, is_correct=False
    )
    false_option = ExerciseOption(
        exercise_id=exercise.exercise_id, option_key="false", content="False", position=1, is_correct=True
    )

    async with uow_factory() as uow:
        await uow.learners.create(learner)
        await uow.curriculum.upsert_skill(skill)
        await uow.curriculum.upsert_path(path)
        await uow.curriculum.upsert_module(module)
        await uow.curriculum.upsert_lesson(lesson)
        await uow.curriculum.upsert_exercise(exercise)
        await uow.curriculum.upsert_options([true_option, false_option])
        await uow.commit()

    return learner, lesson, exercise, false_option


async def test_progress_upsert_is_idempotent(uow_factory) -> None:
    learner, lesson, _, _ = await _seed_learner_and_lesson(uow_factory)
    progress = UserProgress(learner_id=learner.learner_id, lesson_id=lesson.lesson_id, attempt_count=1)

    async with uow_factory() as uow:
        first = await uow.progress.upsert(progress)
        await uow.commit()

    updated = progress.model_copy(update={"attempt_count": 2, "status": ProgressStatus.IN_PROGRESS})
    async with uow_factory() as uow:
        second = await uow.progress.upsert(updated)
        await uow.commit()

    assert first.progress_id == second.progress_id
    assert second.attempt_count == 2

    async with uow_factory() as uow:
        all_progress = await uow.progress.list_for_learner(learner.learner_id)
    assert len(all_progress) == 1


async def test_get_lesson_progress_returns_none_when_missing(uow_factory) -> None:
    async with uow_factory() as uow:
        result = await uow.progress.get_lesson_progress(uuid4(), uuid4())
    assert result is None


async def test_complete_learning_submission_end_to_end(uow_factory) -> None:
    learner, lesson, exercise, false_option = await _seed_learner_and_lesson(uow_factory)
    service = LearningService(unit_of_work_factory=uow_factory)

    attempt = await service.start_exercise_attempt(
        learner_id=learner.learner_id, exercise_id=exercise.exercise_id
    )
    assert attempt.attempt_number == 1

    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, selected_option_ids=[false_option.option_id])
    result = await service.submit_answer(attempt_id=attempt.attempt_id, answer=answer)

    assert result.attempt.status == AttemptStatus.GRADED
    assert result.attempt.is_correct is True
    assert len(result.updated_mastery) == 1
    assert result.updated_progress is not None
    assert result.updated_progress.status == ProgressStatus.COMPLETED

    async with uow_factory() as uow:
        stored_progress = await uow.progress.get_lesson_progress(learner.learner_id, lesson.lesson_id)
    assert stored_progress is not None
    assert stored_progress.status == ProgressStatus.COMPLETED


async def test_failed_transaction_rolls_back(uow_factory, test_engine: AsyncEngine) -> None:
    learner = LearnerProfile(display_name="Rollback Test")

    with pytest.raises(RuntimeError):
        async with uow_factory() as uow:
            await uow.learners.create(learner)
            raise RuntimeError("simulated failure before commit")

    async with test_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT COUNT(*) FROM learner_profiles WHERE display_name = 'Rollback Test'")
        )
        count = result.scalar_one()
    assert count == 0


async def test_existing_market_tables_remain_valid(uow_factory) -> None:
    """Learning-schema migration/tests must not disturb Phase 1-3 market tables."""
    security = Security(ticker="AAPL", company_name="Apple Inc.", exchange=Exchange.NASDAQ)

    async with uow_factory() as uow:
        stored = await uow.securities.upsert(security)
        await uow.commit()

    assert stored.ticker == "AAPL"

    async with uow_factory() as uow:
        fetched = await uow.securities.get_by_id(stored.security_id)
    assert fetched is not None
    assert fetched.ticker == "AAPL"
