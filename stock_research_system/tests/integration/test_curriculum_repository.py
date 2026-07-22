"""PostgreSQL integration tests: schema checks and CurriculumRepository."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.domain.learning.enums import DifficultyLevel, FinancialSkillCategory
from stock_research_core.domain.learning.models import LearningModule, LearningPath, Skill

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
