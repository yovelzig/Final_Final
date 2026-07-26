"""PostgreSQL integration tests: schema checks and CurriculumRepository."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    LearningModule,
    LearningPath,
    Lesson,
    Skill,
)

pytestmark = pytest.mark.integration

_EXPECTED_LEARNING_TABLES = {
    "learner_profiles",
    "financial_skills",
    "skill_prerequisites",
    "learning_paths",
    "learning_modules",
    "lessons",
    "lesson_secondary_skills",
    "exercises",
    "exercise_skills",
    "exercise_options",
    "exercise_attempts",
    "exercise_answers",
    "exercise_answer_selected_options",
    "exercise_answer_ordered_options",
    "skill_mastery",
    "user_progress",
    "misconceptions",
    "misconception_evidence_attempts",
}


async def test_migration_reaches_head(test_engine: AsyncEngine) -> None:
    from sqlalchemy import text

    async with test_engine.connect() as connection:
        result = await connection.execute(text("SELECT version_num FROM alembic_version"))
        revision = result.scalar_one()
    assert revision == "0011_ragas_learning_quality"


async def test_all_learning_tables_exist(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_conn: sa_inspect(sync_conn).get_table_names()
        )
    assert _EXPECTED_LEARNING_TABLES.issubset(set(table_names))


async def _seed_skill(uow_factory, code: str = "MONEY_BASICS") -> Skill:
    skill = Skill(
        code=code,
        name=code.title(),
        description="desc",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    async with uow_factory() as uow:
        stored = await uow.curriculum.upsert_skill(skill)
        await uow.commit()
    return stored


async def test_skill_upsert_is_idempotent_and_preserves_prerequisites(uow_factory) -> None:
    prerequisite = await _seed_skill(uow_factory, "MONEY_BASICS")
    skill = Skill(
        code="COMPOUND_INTEREST",
        name="Compound Interest",
        description="desc",
        category=FinancialSkillCategory.COMPOUND_INTEREST,
        difficulty=DifficultyLevel.BEGINNER,
        prerequisite_skill_ids=[prerequisite.skill_id],
    )

    async with uow_factory() as uow:
        await uow.curriculum.upsert_skill(skill)
        await uow.commit()

    # Re-run with the same skill_id: must update in place, not duplicate.
    async with uow_factory() as uow:
        await uow.curriculum.upsert_skill(skill)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.curriculum.get_skill(skill.skill_id)
        all_skills = await uow.curriculum.list_skills(active_only=False)

    assert fetched is not None
    assert fetched.prerequisite_skill_ids == [prerequisite.skill_id]
    assert len([s for s in all_skills if s.skill_id == skill.skill_id]) == 1


async def test_curriculum_ordering_is_deterministic(uow_factory) -> None:
    path = LearningPath(
        code="investing-foundations",
        title="Investing Foundations",
        description="desc",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        estimated_minutes=60,
        published=True,
    )
    async with uow_factory() as uow:
        await uow.curriculum.upsert_path(path)
        await uow.commit()

    modules = [
        LearningModule(
            path_id=path.path_id,
            code=f"module-{i}",
            title=f"Module {i}",
            description="desc",
            position=i,
            estimated_minutes=30,
            published=True,
        )
        for i in (2, 0, 1)
    ]
    async with uow_factory() as uow:
        for module in modules:
            await uow.curriculum.upsert_module(module)
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.curriculum.list_modules(path.path_id)

    assert [m.position for m in listed] == [0, 1, 2]


async def test_get_skill_returns_none_when_missing(uow_factory) -> None:
    async with uow_factory() as uow:
        result = await uow.curriculum.get_skill(uuid4())
    assert result is None


async def _seed_full_hierarchy(
    uow_factory,
    *,
    module_published: bool = True,
    lesson_status: LessonStatus = LessonStatus.PUBLISHED,
    exercise_active: bool = True,
) -> tuple[LearningPath, LearningModule, Lesson, Exercise]:
    skill = await _seed_skill(uow_factory, "STOCKS")
    path = LearningPath(
        code="filter-test-path", title="Path", description="d", difficulty=DifficultyLevel.BEGINNER,
        position=0, estimated_minutes=10, published=True,
    )
    module = LearningModule(
        path_id=path.path_id, code="filter-test-module", title="Module", description="d",
        position=0, estimated_minutes=10, published=module_published,
    )
    lesson = Lesson(
        module_id=module.module_id, code="filter-test-lesson", title="Lesson", summary="s",
        content_markdown="# c", difficulty=DifficultyLevel.BEGINNER, status=lesson_status,
        position=0, estimated_minutes=10, primary_skill_id=skill.skill_id,
    )
    exercise = Exercise(
        lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE, prompt="p",
        explanation="e", difficulty=DifficultyLevel.BEGINNER, position=0,
        skill_ids=[skill.skill_id], maximum_score=1.0, passing_score=1.0, active=exercise_active,
    )
    async with uow_factory() as uow:
        await uow.curriculum.upsert_path(path)
        await uow.curriculum.upsert_module(module)
        await uow.curriculum.upsert_lesson(lesson)
        await uow.curriculum.upsert_exercise(exercise)
        await uow.commit()
    return path, module, lesson, exercise


async def test_list_modules_published_only_defaults_to_unfiltered(uow_factory) -> None:
    path, module, _lesson, _exercise = await _seed_full_hierarchy(uow_factory, module_published=False)

    async with uow_factory() as uow:
        unfiltered = await uow.curriculum.list_modules(path.path_id)
        filtered = await uow.curriculum.list_modules(path.path_id, published_only=True)

    assert [m.module_id for m in unfiltered] == [module.module_id]
    assert filtered == []


async def test_list_lessons_published_only_defaults_to_unfiltered(uow_factory) -> None:
    _path, module, lesson, _exercise = await _seed_full_hierarchy(
        uow_factory, lesson_status=LessonStatus.DRAFT
    )

    async with uow_factory() as uow:
        unfiltered = await uow.curriculum.list_lessons(module.module_id)
        filtered = await uow.curriculum.list_lessons(module.module_id, published_only=True)

    assert [lesson_row.lesson_id for lesson_row in unfiltered] == [lesson.lesson_id]
    assert filtered == []


async def test_list_exercises_active_only_defaults_to_unfiltered(uow_factory) -> None:
    _path, _module, lesson, exercise = await _seed_full_hierarchy(uow_factory, exercise_active=False)

    async with uow_factory() as uow:
        unfiltered = await uow.curriculum.list_exercises(lesson.lesson_id)
        filtered = await uow.curriculum.list_exercises(lesson.lesson_id, active_only=True)

    assert [ex.exercise_id for ex in unfiltered] == [exercise.exercise_id]
    assert filtered == []


async def test_lesson_ordering_is_deterministic(uow_factory) -> None:
    skill = await _seed_skill(uow_factory, "BONDS")
    path = LearningPath(
        code="lesson-order-path", title="Path", description="d", difficulty=DifficultyLevel.BEGINNER,
        position=0, estimated_minutes=10, published=True,
    )
    module = LearningModule(
        path_id=path.path_id, code="lesson-order-module", title="Module", description="d",
        position=0, estimated_minutes=10, published=True,
    )
    async with uow_factory() as uow:
        await uow.curriculum.upsert_path(path)
        await uow.curriculum.upsert_module(module)
        await uow.commit()

    lessons = [
        Lesson(
            module_id=module.module_id, code=f"lesson-{i}", title=f"Lesson {i}", summary="s",
            content_markdown="# c", difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED,
            position=i, estimated_minutes=10, primary_skill_id=skill.skill_id,
        )
        for i in (2, 0, 1)
    ]
    async with uow_factory() as uow:
        for lesson in lessons:
            await uow.curriculum.upsert_lesson(lesson)
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.curriculum.list_lessons(module.module_id)

    assert [lesson.position for lesson in listed] == [0, 1, 2]


async def test_exercise_ordering_is_deterministic(uow_factory) -> None:
    skill = await _seed_skill(uow_factory, "RISK_AND_RETURN")
    path = LearningPath(
        code="exercise-order-path", title="Path", description="d", difficulty=DifficultyLevel.BEGINNER,
        position=0, estimated_minutes=10, published=True,
    )
    module = LearningModule(
        path_id=path.path_id, code="exercise-order-module", title="Module", description="d",
        position=0, estimated_minutes=10, published=True,
    )
    lesson = Lesson(
        module_id=module.module_id, code="exercise-order-lesson", title="Lesson", summary="s",
        content_markdown="# c", difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED,
        position=0, estimated_minutes=10, primary_skill_id=skill.skill_id,
    )
    async with uow_factory() as uow:
        await uow.curriculum.upsert_path(path)
        await uow.curriculum.upsert_module(module)
        await uow.curriculum.upsert_lesson(lesson)
        await uow.commit()

    exercises = [
        Exercise(
            lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE, prompt=f"p{i}",
            explanation="e", difficulty=DifficultyLevel.BEGINNER, position=i,
            skill_ids=[skill.skill_id], maximum_score=1.0, passing_score=1.0,
        )
        for i in (2, 0, 1)
    ]
    async with uow_factory() as uow:
        for exercise in exercises:
            await uow.curriculum.upsert_exercise(exercise)
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.curriculum.list_exercises(lesson.lesson_id)

    assert [ex.position for ex in listed] == [0, 1, 2]
