"""PostgreSQL integration tests: AttemptRepository (attempts and answers)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.learning.enums import (
    AttemptStatus,
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseAttempt,
    ExerciseOption,
    LearnerProfile,
    Lesson,
    LearningModule,
    LearningPath,
    Skill,
)

pytestmark = pytest.mark.integration


async def _seed_exercise_with_options(uow_factory):
    skill = Skill(
        code="STOCKS",
        name="Stocks",
        description="desc",
        category=FinancialSkillCategory.STOCKS,
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
        code="stocks-module",
        title="Stocks",
        description="desc",
        position=0,
        estimated_minutes=30,
        published=True,
    )
    lesson = Lesson(
        module_id=module.module_id,
        code="what-a-stock-represents",
        title="What a Stock Represents",
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
        exercise_type=ExerciseType.SINGLE_CHOICE,
        prompt="What does owning a share of stock represent?",
        explanation="explanation",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        skill_ids=[skill.skill_id],
        maximum_score=1.0,
        passing_score=1.0,
    )
    correct = ExerciseOption(
        exercise_id=exercise.exercise_id, option_key="a", content="Ownership stake", position=0, is_correct=True
    )
    incorrect = ExerciseOption(
        exercise_id=exercise.exercise_id, option_key="b", content="A loan", position=1, is_correct=False
    )

    learner = LearnerProfile(display_name="Amit")

    async with uow_factory() as uow:
        await uow.curriculum.upsert_skill(skill)
        await uow.curriculum.upsert_path(path)
        await uow.curriculum.upsert_module(module)
        await uow.curriculum.upsert_lesson(lesson)
        await uow.curriculum.upsert_exercise(exercise)
        await uow.curriculum.upsert_options([correct, incorrect])
        await uow.learners.create(learner)
        await uow.commit()

    return learner, exercise, correct, incorrect


async def test_attempt_and_answer_round_trip(uow_factory) -> None:
    learner, exercise, correct, _ = await _seed_exercise_with_options(uow_factory)

    attempt = ExerciseAttempt(
        learner_id=learner.learner_id,
        exercise_id=exercise.exercise_id,
        maximum_score=exercise.maximum_score,
        attempt_number=1,
    )
    async with uow_factory() as uow:
        created = await uow.attempts.create_attempt(attempt)
        await uow.commit()
    assert created.attempt_id == attempt.attempt_id

    now = datetime.now(timezone.utc)
    answer = ExerciseAnswer(
        attempt_id=attempt.attempt_id, selected_option_ids=[correct.option_id], submitted_at=now
    )
    async with uow_factory() as uow:
        saved_answer = await uow.attempts.save_answer(answer)
        graded_attempt = ExerciseAttempt(
            **{
                **created.model_dump(),
                "status": AttemptStatus.GRADED,
                "submitted_at": now,
                "graded_at": now,
                "score": 1.0,
                "is_correct": True,
            }
        )
        await uow.attempts.update_attempt(graded_attempt)
        await uow.commit()

    assert saved_answer.selected_option_ids == [correct.option_id]

    async with uow_factory() as uow:
        fetched_attempt = await uow.attempts.get_attempt(attempt.attempt_id)

    assert fetched_attempt is not None
    assert fetched_attempt.status == AttemptStatus.GRADED
    assert fetched_attempt.is_correct is True


async def test_list_attempts_filters_by_exercise(uow_factory) -> None:
    learner, exercise, _, _ = await _seed_exercise_with_options(uow_factory)

    async with uow_factory() as uow:
        await uow.attempts.create_attempt(
            ExerciseAttempt(
                learner_id=learner.learner_id,
                exercise_id=exercise.exercise_id,
                maximum_score=exercise.maximum_score,
                attempt_number=1,
            )
        )
        await uow.attempts.create_attempt(
            ExerciseAttempt(
                learner_id=learner.learner_id,
                exercise_id=exercise.exercise_id,
                maximum_score=exercise.maximum_score,
                attempt_number=2,
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        attempts = await uow.attempts.list_attempts(learner.learner_id, exercise.exercise_id)

    assert [a.attempt_number for a in attempts] == [1, 2]


async def test_get_attempt_returns_none_when_missing(uow_factory) -> None:
    async with uow_factory() as uow:
        result = await uow.attempts.get_attempt(uuid4())
    assert result is None
