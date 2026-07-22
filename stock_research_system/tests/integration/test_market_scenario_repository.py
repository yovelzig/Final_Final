"""PostgreSQL integration tests: migration 0004 and `MarketScenarioRepository`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import Exercise, Lesson, LearningModule, LearningPath, Skill
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
)
from stock_research_core.domain.market_scenarios.models import HistoricalMarketScenario
from stock_research_core.domain.models import Security

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

_SCENARIO_TABLES = {
    "historical_market_scenarios",
    "historical_market_scenario_primary_skills",
    "historical_market_scenario_secondary_skills",
    "scenario_securities",
    "scenario_option_rubrics",
    "scenario_option_rubric_feedback_codes",
    "scenario_outcomes",
    "scenario_submissions",
    "scenario_submission_feedback_codes",
    "scenario_generation_runs",
}


async def test_migration_reaches_head(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(text("SELECT version_num FROM alembic_version"))
        revision = result.scalar_one()
    assert revision == "0011_ragas_learning_quality"


async def test_all_scenario_tables_exist(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync_conn: sa_inspect(sync_conn).get_table_names())
    assert _SCENARIO_TABLES <= set(table_names)


async def test_exercise_attempts_has_grading_version_column(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync_conn: {col["name"] for col in sa_inspect(sync_conn).get_columns("exercise_attempts")}
        )
    assert "grading_version" in columns


async def _seed_exercise(uow_factory) -> tuple[Exercise, Skill, Security]:
    skill = Skill(
        code=f"RISK_AND_RETURN_{uuid4().hex[:8].upper()}",
        name="Risk and Return",
        description="desc",
        category="RISK_AND_RETURN",
        difficulty=DifficultyLevel.MEDIUM,
    )
    security = Security(ticker=f"T{uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ)
    async with uow_factory() as uow:
        stored_skill = await uow.curriculum.upsert_skill(skill)
        stored_security = await uow.securities.upsert(security)
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"path-{uuid4().hex[:8]}", title="Path", description="d",
                difficulty=DifficultyLevel.MEDIUM, position=0, estimated_minutes=10, published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code=f"mod-{uuid4().hex[:8]}", title="Module", description="d",
                position=0, estimated_minutes=10, published=True,
            )
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code=f"lesson-{uuid4().hex[:8]}", title="Lesson", summary="s",
                content_markdown="# c", difficulty=DifficultyLevel.MEDIUM, status="PUBLISHED",
                position=0, estimated_minutes=10, primary_skill_id=stored_skill.skill_id,
            )
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(
                lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SCENARIO_DECISION,
                prompt="Decide.", explanation="Explanation.", difficulty=DifficultyLevel.MEDIUM,
                position=0, skill_ids=[stored_skill.skill_id], maximum_score=1.0, passing_score=0.6,
            )
        )
        await uow.commit()
    return exercise, stored_skill, stored_security


def _scenario(exercise: Exercise, skill: Skill, security: Security, **overrides) -> HistoricalMarketScenario:
    defaults: dict = dict(
        exercise_id=exercise.exercise_id,
        code=f"TEST_{uuid4().hex[:10].upper()}",
        title="Test scenario",
        description="Description.",
        scenario_type=MarketScenarioType.MARKET_REPLAY,
        observation_start_at=NOW - timedelta(days=60),
        decision_at=NOW - timedelta(days=20),
        reveal_end_at=NOW,
        interval="1d",
        source_name="test-source",
        focal_security_id=security.security_id,
        primary_skill_ids=[skill.skill_id],
        prompt="Decide.",
        learner_instructions="Instructions.",
        learning_objectives=["Learn something."],
        minimum_observation_bars=5,
        minimum_reveal_bars=5,
        scenario_version="scenario-v1",
    )
    defaults.update(overrides)
    return HistoricalMarketScenario(**defaults)


async def test_scenario_round_trip_preserves_associations(uow_factory) -> None:
    exercise, skill, security = await _seed_exercise(uow_factory)
    scenario = _scenario(exercise, skill, security)

    async with uow_factory() as uow:
        created = await uow.market_scenarios.upsert(scenario)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.market_scenarios.get(created.scenario_id)

    assert fetched is not None
    assert fetched.focal_security_id == security.security_id
    assert fetched.benchmark_security_id is None
    assert fetched.primary_skill_ids == [skill.skill_id]
    assert fetched.code == scenario.code
    assert fetched.learning_objectives == scenario.learning_objectives


async def test_scenario_upsert_is_idempotent_and_updates_in_place(uow_factory) -> None:
    exercise, skill, security = await _seed_exercise(uow_factory)
    scenario = _scenario(exercise, skill, security)

    async with uow_factory() as uow:
        first = await uow.market_scenarios.upsert(scenario)
        await uow.commit()

    updated_scenario = scenario.model_copy(update={"scenario_id": first.scenario_id, "title": "Updated title"})
    async with uow_factory() as uow:
        second = await uow.market_scenarios.upsert(updated_scenario)
        await uow.commit()

    assert second.scenario_id == first.scenario_id
    assert second.title == "Updated title"


async def test_scenario_code_is_unique(uow_factory) -> None:
    exercise, skill, security = await _seed_exercise(uow_factory)
    exercise2, _skill2, _security2 = await _seed_exercise(uow_factory)
    code = f"UNIQUE_{uuid4().hex[:10].upper()}"
    scenario_a = _scenario(exercise, skill, security, code=code)
    scenario_b = _scenario(exercise2, skill, security, code=code)

    async with uow_factory() as uow:
        await uow.market_scenarios.upsert(scenario_a)
        await uow.commit()

    with pytest.raises(Exception):  # noqa: B017 - a database-level unique-constraint violation
        async with uow_factory() as uow:
            await uow.market_scenarios.upsert(scenario_b)
            await uow.commit()


async def test_get_by_exercise_id(uow_factory) -> None:
    exercise, skill, security = await _seed_exercise(uow_factory)
    scenario = _scenario(exercise, skill, security)
    async with uow_factory() as uow:
        created = await uow.market_scenarios.upsert(scenario)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.market_scenarios.get_by_exercise_id(exercise.exercise_id)

    assert fetched is not None
    assert fetched.scenario_id == created.scenario_id


async def test_get_by_code(uow_factory) -> None:
    exercise, skill, security = await _seed_exercise(uow_factory)
    scenario = _scenario(exercise, skill, security)
    async with uow_factory() as uow:
        await uow.market_scenarios.upsert(scenario)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.market_scenarios.get_by_code(scenario.code)

    assert fetched is not None
    assert fetched.code == scenario.code


async def test_list_published_returns_only_published_scenarios(uow_factory) -> None:
    exercise, skill, security = await _seed_exercise(uow_factory)
    draft = _scenario(exercise, skill, security, status=MarketScenarioStatus.DRAFT)
    exercise2, _skill2, _security2 = await _seed_exercise(uow_factory)
    published = _scenario(exercise2, skill, security, status=MarketScenarioStatus.PUBLISHED)

    async with uow_factory() as uow:
        created_draft = await uow.market_scenarios.upsert(draft)
        created_published = await uow.market_scenarios.upsert(published)
        await uow.commit()

    async with uow_factory() as uow:
        results = await uow.market_scenarios.list_published()

    result_ids = {s.scenario_id for s in results}
    assert created_published.scenario_id in result_ids
    assert created_draft.scenario_id not in result_ids


async def test_set_status_transitions_scenario(uow_factory) -> None:
    exercise, skill, security = await _seed_exercise(uow_factory)
    scenario = _scenario(exercise, skill, security)
    async with uow_factory() as uow:
        created = await uow.market_scenarios.upsert(scenario)
        await uow.commit()

    async with uow_factory() as uow:
        ready = await uow.market_scenarios.set_status(created.scenario_id, MarketScenarioStatus.READY)
        await uow.commit()
    assert ready.status == MarketScenarioStatus.READY

    async with uow_factory() as uow:
        published = await uow.market_scenarios.set_status(created.scenario_id, MarketScenarioStatus.PUBLISHED)
        await uow.commit()
    assert published.status == MarketScenarioStatus.PUBLISHED


async def test_scenario_with_benchmark_security(uow_factory) -> None:
    exercise, skill, security = await _seed_exercise(uow_factory)
    benchmark = Security(ticker=f"B{uuid4().hex[:6].upper()}", company_name="Benchmark", exchange=Exchange.NYSE)
    async with uow_factory() as uow:
        stored_benchmark = await uow.securities.upsert(benchmark)
        await uow.commit()

    scenario = _scenario(
        exercise, skill, security,
        benchmark_security_id=stored_benchmark.security_id,
        scenario_type=MarketScenarioType.BENCHMARK_COMPARISON,
    )
    async with uow_factory() as uow:
        created = await uow.market_scenarios.upsert(scenario)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.market_scenarios.get(created.scenario_id)

    assert fetched is not None
    assert fetched.benchmark_security_id == stored_benchmark.security_id
