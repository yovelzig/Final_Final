"""SQLAlchemy repository for the curriculum hierarchy.

Skills, paths, modules, lessons, and exercises are seeded with stable,
deterministic IDs (see `scripts/seed_learning_curriculum.py`), so every
upsert here targets the primary key directly - re-running the seed
updates the same rows in place instead of creating duplicates.
Association tables (prerequisites, secondary skills, exercise skills)
are replaced wholesale on each upsert: simple, correct, and idempotent.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseOption,
    LearningModule,
    LearningPath,
    Lesson,
    Skill,
)
from stock_research_core.infrastructure.database.mappers.learning_mappers import (
    exercise_option_orm_to_domain,
    exercise_orm_to_domain,
    learning_module_orm_to_domain,
    learning_path_orm_to_domain,
    lesson_orm_to_domain,
    skill_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.exercise import ExerciseORM, ExerciseSkillORM
from stock_research_core.infrastructure.database.orm.exercise_option import ExerciseOptionORM
from stock_research_core.infrastructure.database.orm.learning_module import LearningModuleORM
from stock_research_core.infrastructure.database.orm.learning_path import LearningPathORM
from stock_research_core.infrastructure.database.orm.lesson import LessonORM, LessonSecondarySkillORM
from stock_research_core.infrastructure.database.orm.skill import (
    FinancialSkillORM,
    SkillPrerequisiteORM,
)


class SqlAlchemyCurriculumRepository:
    """Persists and queries skills, paths, modules, lessons, exercises, and options."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- skills ---------------------------------------------------------

    async def upsert_skill(self, skill: Skill) -> Skill:
        insert_stmt = pg_insert(FinancialSkillORM).values(
            skill_id=skill.skill_id,
            code=skill.code,
            name=skill.name,
            description=skill.description,
            category=skill.category.value,
            difficulty=skill.difficulty.value,
            active=skill.active,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["skill_id"],
            set_={
                "code": insert_stmt.excluded.code,
                "name": insert_stmt.excluded.name,
                "description": insert_stmt.excluded.description,
                "category": insert_stmt.excluded.category,
                "difficulty": insert_stmt.excluded.difficulty,
                "active": insert_stmt.excluded.active,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)

        await self._session.execute(
            delete(SkillPrerequisiteORM).where(SkillPrerequisiteORM.skill_id == skill.skill_id)
        )
        for prerequisite_id in skill.prerequisite_skill_ids:
            self._session.add(
                SkillPrerequisiteORM(skill_id=skill.skill_id, prerequisite_skill_id=prerequisite_id)
            )
        await self._session.flush()

        row = await self._session.get(FinancialSkillORM, skill.skill_id)
        assert row is not None
        return skill_orm_to_domain(row, skill.prerequisite_skill_ids)

    async def get_skill(self, skill_id: UUID) -> Skill | None:
        row = await self._session.get(FinancialSkillORM, skill_id)
        if row is None:
            return None
        return skill_orm_to_domain(row, await self._load_prerequisites(skill_id))

    async def list_skills(self, active_only: bool = True) -> list[Skill]:
        statement = select(FinancialSkillORM).order_by(FinancialSkillORM.code.asc())
        if active_only:
            statement = statement.where(FinancialSkillORM.active.is_(True))
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        return [
            skill_orm_to_domain(row, await self._load_prerequisites(row.skill_id)) for row in rows
        ]

    async def _load_prerequisites(self, skill_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(SkillPrerequisiteORM.prerequisite_skill_id).where(
                SkillPrerequisiteORM.skill_id == skill_id
            )
        )
        return list(result.scalars().all())

    # -- learning paths ---------------------------------------------------

    async def upsert_path(self, path: LearningPath) -> LearningPath:
        insert_stmt = pg_insert(LearningPathORM).values(
            path_id=path.path_id,
            code=path.code,
            title=path.title,
            description=path.description,
            difficulty=path.difficulty.value,
            position=path.position,
            estimated_minutes=path.estimated_minutes,
            published=path.published,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["path_id"],
            set_={
                "code": insert_stmt.excluded.code,
                "title": insert_stmt.excluded.title,
                "description": insert_stmt.excluded.description,
                "difficulty": insert_stmt.excluded.difficulty,
                "position": insert_stmt.excluded.position,
                "estimated_minutes": insert_stmt.excluded.estimated_minutes,
                "published": insert_stmt.excluded.published,
                "updated_at": func.now(),
            },
        ).returning(LearningPathORM.path_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()
        row = await self._session.get(LearningPathORM, canonical_id)
        assert row is not None
        return learning_path_orm_to_domain(row)

    async def list_paths(self, published_only: bool = True) -> list[LearningPath]:
        statement = select(LearningPathORM).order_by(LearningPathORM.position.asc())
        if published_only:
            statement = statement.where(LearningPathORM.published.is_(True))
        result = await self._session.execute(statement)
        return [learning_path_orm_to_domain(row) for row in result.scalars().all()]

    async def get_path(self, path_id: UUID) -> LearningPath | None:
        row = await self._session.get(LearningPathORM, path_id)
        return learning_path_orm_to_domain(row) if row is not None else None

    # -- learning modules ---------------------------------------------------

    async def upsert_module(self, module: LearningModule) -> LearningModule:
        insert_stmt = pg_insert(LearningModuleORM).values(
            module_id=module.module_id,
            path_id=module.path_id,
            code=module.code,
            title=module.title,
            description=module.description,
            position=module.position,
            estimated_minutes=module.estimated_minutes,
            published=module.published,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["module_id"],
            set_={
                "path_id": insert_stmt.excluded.path_id,
                "code": insert_stmt.excluded.code,
                "title": insert_stmt.excluded.title,
                "description": insert_stmt.excluded.description,
                "position": insert_stmt.excluded.position,
                "estimated_minutes": insert_stmt.excluded.estimated_minutes,
                "published": insert_stmt.excluded.published,
                "updated_at": func.now(),
            },
        ).returning(LearningModuleORM.module_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()
        row = await self._session.get(LearningModuleORM, canonical_id)
        assert row is not None
        return learning_module_orm_to_domain(row)

    async def list_modules(self, path_id: UUID) -> list[LearningModule]:
        statement = (
            select(LearningModuleORM)
            .where(LearningModuleORM.path_id == path_id)
            .order_by(LearningModuleORM.position.asc())
        )
        result = await self._session.execute(statement)
        return [learning_module_orm_to_domain(row) for row in result.scalars().all()]

    async def get_module(self, module_id: UUID) -> LearningModule | None:
        row = await self._session.get(LearningModuleORM, module_id)
        return learning_module_orm_to_domain(row) if row is not None else None

    # -- lessons ---------------------------------------------------

    async def upsert_lesson(self, lesson: Lesson) -> Lesson:
        insert_stmt = pg_insert(LessonORM).values(
            lesson_id=lesson.lesson_id,
            module_id=lesson.module_id,
            code=lesson.code,
            title=lesson.title,
            summary=lesson.summary,
            content_markdown=lesson.content_markdown,
            difficulty=lesson.difficulty.value,
            status=lesson.status.value,
            position=lesson.position,
            estimated_minutes=lesson.estimated_minutes,
            primary_skill_id=lesson.primary_skill_id,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["lesson_id"],
            set_={
                "module_id": insert_stmt.excluded.module_id,
                "code": insert_stmt.excluded.code,
                "title": insert_stmt.excluded.title,
                "summary": insert_stmt.excluded.summary,
                "content_markdown": insert_stmt.excluded.content_markdown,
                "difficulty": insert_stmt.excluded.difficulty,
                "status": insert_stmt.excluded.status,
                "position": insert_stmt.excluded.position,
                "estimated_minutes": insert_stmt.excluded.estimated_minutes,
                "primary_skill_id": insert_stmt.excluded.primary_skill_id,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)

        await self._session.execute(
            delete(LessonSecondarySkillORM).where(
                LessonSecondarySkillORM.lesson_id == lesson.lesson_id
            )
        )
        for skill_id in lesson.secondary_skill_ids:
            self._session.add(
                LessonSecondarySkillORM(lesson_id=lesson.lesson_id, skill_id=skill_id)
            )
        await self._session.flush()

        row = await self._session.get(LessonORM, lesson.lesson_id)
        assert row is not None
        return lesson_orm_to_domain(row, lesson.secondary_skill_ids)

    async def get_lesson(self, lesson_id: UUID) -> Lesson | None:
        row = await self._session.get(LessonORM, lesson_id)
        if row is None:
            return None
        return lesson_orm_to_domain(row, await self._load_secondary_skills(lesson_id))

    async def list_lessons(self, module_id: UUID) -> list[Lesson]:
        statement = (
            select(LessonORM)
            .where(LessonORM.module_id == module_id)
            .order_by(LessonORM.position.asc())
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        return [
            lesson_orm_to_domain(row, await self._load_secondary_skills(row.lesson_id))
            for row in rows
        ]

    async def _load_secondary_skills(self, lesson_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(LessonSecondarySkillORM.skill_id).where(
                LessonSecondarySkillORM.lesson_id == lesson_id
            )
        )
        return list(result.scalars().all())

    # -- exercises ---------------------------------------------------

    async def upsert_exercise(self, exercise: Exercise) -> Exercise:
        insert_stmt = pg_insert(ExerciseORM).values(
            exercise_id=exercise.exercise_id,
            lesson_id=exercise.lesson_id,
            exercise_type=exercise.exercise_type.value,
            prompt=exercise.prompt,
            explanation=exercise.explanation,
            difficulty=exercise.difficulty.value,
            position=exercise.position,
            maximum_score=exercise.maximum_score,
            passing_score=exercise.passing_score,
            configuration=exercise.configuration,
            active=exercise.active,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["exercise_id"],
            set_={
                "lesson_id": insert_stmt.excluded.lesson_id,
                "exercise_type": insert_stmt.excluded.exercise_type,
                "prompt": insert_stmt.excluded.prompt,
                "explanation": insert_stmt.excluded.explanation,
                "difficulty": insert_stmt.excluded.difficulty,
                "position": insert_stmt.excluded.position,
                "maximum_score": insert_stmt.excluded.maximum_score,
                "passing_score": insert_stmt.excluded.passing_score,
                "configuration": insert_stmt.excluded.configuration,
                "active": insert_stmt.excluded.active,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)

        await self._session.execute(
            delete(ExerciseSkillORM).where(ExerciseSkillORM.exercise_id == exercise.exercise_id)
        )
        for skill_id in exercise.skill_ids:
            self._session.add(ExerciseSkillORM(exercise_id=exercise.exercise_id, skill_id=skill_id))
        await self._session.flush()

        row = await self._session.get(ExerciseORM, exercise.exercise_id)
        assert row is not None
        return exercise_orm_to_domain(row, exercise.skill_ids)

    async def get_exercise(self, exercise_id: UUID) -> Exercise | None:
        row = await self._session.get(ExerciseORM, exercise_id)
        if row is None:
            return None
        return exercise_orm_to_domain(row, await self._load_exercise_skills(exercise_id))

    async def list_exercises(self, lesson_id: UUID) -> list[Exercise]:
        statement = (
            select(ExerciseORM)
            .where(ExerciseORM.lesson_id == lesson_id)
            .order_by(ExerciseORM.position.asc())
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        return [
            exercise_orm_to_domain(row, await self._load_exercise_skills(row.exercise_id))
            for row in rows
        ]

    async def _load_exercise_skills(self, exercise_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(ExerciseSkillORM.skill_id).where(ExerciseSkillORM.exercise_id == exercise_id)
        )
        return list(result.scalars().all())

    # -- exercise options ---------------------------------------------------

    async def upsert_options(self, options: list[ExerciseOption]) -> int:
        if not options:
            return 0

        values = [
            {
                "option_id": option.option_id,
                "exercise_id": option.exercise_id,
                "option_key": option.option_key,
                "content": option.content,
                "position": option.position,
                "is_correct": option.is_correct,
                "feedback": option.feedback,
            }
            for option in options
        ]
        insert_stmt = pg_insert(ExerciseOptionORM).values(values)
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["option_id"],
            set_={
                "exercise_id": insert_stmt.excluded.exercise_id,
                "option_key": insert_stmt.excluded.option_key,
                "content": insert_stmt.excluded.content,
                "position": insert_stmt.excluded.position,
                "is_correct": insert_stmt.excluded.is_correct,
                "feedback": insert_stmt.excluded.feedback,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)
        return len(options)

    async def list_options(self, exercise_id: UUID) -> list[ExerciseOption]:
        statement = (
            select(ExerciseOptionORM)
            .where(ExerciseOptionORM.exercise_id == exercise_id)
            .order_by(ExerciseOptionORM.position.asc())
        )
        result = await self._session.execute(statement)
        return [exercise_option_orm_to_domain(row) for row in result.scalars().all()]
