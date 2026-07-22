"""PostgreSQL integration tests: AdaptiveProfileRepository."""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.domain.adaptive_learning.models import ExerciseAdaptiveProfile
from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import Exercise, Lesson, LearningModule, LearningPath, Skill

pytestmark = pytest.mark.integration


async def _seed_exercise(uow_factory) -> Exercise:
    skill = Skill(
        code=f"MONEY_BASICS_{uuid4().hex[:8].upper()}",
        name="Money Basics",
        description="desc",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    async with uow_factory() as uow:
        stored_skill = await uow.curriculum.upsert_skill(skill)
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"path-{uuid4().hex[:8]}", title="Path", description="d",
                difficulty=DifficultyLevel.BEGINNER, position=0, estimated_minutes=10, published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code="mod", title="Module", description="d",
                position=0, estimated_minutes=10, published=True,
            )
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="lesson", title="Lesson", summary="s",
                content_markdown="# c", difficulty=DifficultyLevel.BEGINNER,
                status=LessonStatus.PUBLISHED, position=0, estimated_minutes=10,
                primary_skill_id=stored_skill.skill_id,
            )
        )
        exercise = Exercise(
            lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE,
            prompt="prompt", explanation="explanation", difficulty=DifficultyLevel.BEGINNER,
            position=0, skill_ids=[stored_skill.skill_id], maximum_score=1.0, passing_score=1.0,
        )
        stored_exercise = await uow.curriculum.upsert_exercise(exercise)
        await uow.commit()
    return stored_exercise


async def test_adaptive_profile_upsert_is_idempotent(uow_factory) -> None:
    exercise = await _seed_exercise(uow_factory)
    profile = ExerciseAdaptiveProfile(
        exercise_id=exercise.exercise_id,
        base_difficulty_score=0.3,
        estimated_seconds=45,
        diagnostic_eligible=True,
        policy_tags=["foundation"],
    )

    async with uow_factory() as uow:
        first = await uow.adaptive_profiles.upsert(profile)
        await uow.commit()

    updated = profile.model_copy(update={"base_difficulty_score": 0.6, "review_eligible": True})
    async with uow_factory() as uow:
        second = await uow.adaptive_profiles.upsert(updated)
        await uow.commit()

    assert first.profile_id == second.profile_id
    assert second.base_difficulty_score == pytest.approx(0.6)
    assert second.review_eligible is True


async def test_adaptive_profile_get_by_exercise(uow_factory) -> None:
    exercise = await _seed_exercise(uow_factory)
    profile = ExerciseAdaptiveProfile(
        exercise_id=exercise.exercise_id, base_difficulty_score=0.5, estimated_seconds=30
    )

    async with uow_factory() as uow:
        await uow.adaptive_profiles.upsert(profile)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.adaptive_profiles.get_by_exercise(exercise.exercise_id)
        missing = await uow.adaptive_profiles.get_by_exercise(uuid4())

    assert found is not None
    assert found.exercise_id == exercise.exercise_id
    assert missing is None


async def test_adaptive_profile_list_active_filters_by_eligibility(uow_factory) -> None:
    diagnostic_exercise = await _seed_exercise(uow_factory)
    review_exercise = await _seed_exercise(uow_factory)

    async with uow_factory() as uow:
        await uow.adaptive_profiles.upsert(
            ExerciseAdaptiveProfile(
                exercise_id=diagnostic_exercise.exercise_id,
                base_difficulty_score=0.3,
                estimated_seconds=30,
                diagnostic_eligible=True,
            )
        )
        await uow.adaptive_profiles.upsert(
            ExerciseAdaptiveProfile(
                exercise_id=review_exercise.exercise_id,
                base_difficulty_score=0.3,
                estimated_seconds=30,
                review_eligible=True,
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        diagnostic_only = await uow.adaptive_profiles.list_active(diagnostic_only=True)
        review_only = await uow.adaptive_profiles.list_active(review_only=True)
        every_active = await uow.adaptive_profiles.list_active()

    assert {p.exercise_id for p in diagnostic_only} == {diagnostic_exercise.exercise_id}
    assert {p.exercise_id for p in review_only} == {review_exercise.exercise_id}
    assert {diagnostic_exercise.exercise_id, review_exercise.exercise_id} <= {
        p.exercise_id for p in every_active
    }
