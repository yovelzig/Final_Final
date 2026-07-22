"""PostgreSQL integration tests: `ScenarioOutcomeRepository`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import Exercise, Lesson, LearningModule, LearningPath, Skill
from stock_research_core.domain.market_scenarios.enums import MarketScenarioType, ScenarioOutcomeDirection
from stock_research_core.domain.market_scenarios.models import HistoricalMarketScenario, ScenarioOutcome
from stock_research_core.domain.models import Security

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_scenario(uow_factory) -> HistoricalMarketScenario:
    skill = Skill(
        code=f"RISK_AND_RETURN_{uuid4().hex[:8].upper()}", name="Risk and Return", description="desc",
        category="RISK_AND_RETURN", difficulty=DifficultyLevel.MEDIUM,
    )
    security = Security(ticker=f"T{uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ)
    async with uow_factory() as uow:
        stored_skill = await uow.curriculum.upsert_skill(skill)
        stored_security = await uow.securities.upsert(security)
        path = await uow.curriculum.upsert_path(
            LearningPath(code=f"path-{uuid4().hex[:8]}", title="P", description="d",
                         difficulty=DifficultyLevel.MEDIUM, position=0, estimated_minutes=10, published=True)
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(path_id=path.path_id, code=f"mod-{uuid4().hex[:8]}", title="M", description="d",
                            position=0, estimated_minutes=10, published=True)
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(module_id=module.module_id, code=f"lesson-{uuid4().hex[:8]}", title="L", summary="s",
                   content_markdown="# c", difficulty=DifficultyLevel.MEDIUM, status="PUBLISHED",
                   position=0, estimated_minutes=10, primary_skill_id=stored_skill.skill_id)
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SCENARIO_DECISION,
                     prompt="Decide.", explanation="Explanation.", difficulty=DifficultyLevel.MEDIUM,
                     position=0, skill_ids=[stored_skill.skill_id], maximum_score=1.0, passing_score=0.6)
        )
        scenario = await uow.market_scenarios.upsert(
            HistoricalMarketScenario(
                exercise_id=exercise.exercise_id, code=f"TEST_{uuid4().hex[:10].upper()}",
                title="t", description="d", scenario_type=MarketScenarioType.MARKET_REPLAY,
                observation_start_at=NOW - timedelta(days=60), decision_at=NOW - timedelta(days=20),
                reveal_end_at=NOW, interval="1d", source_name="test-source",
                focal_security_id=stored_security.security_id, primary_skill_ids=[stored_skill.skill_id],
                prompt="p", learner_instructions="li", learning_objectives=["o"],
                minimum_observation_bars=5, minimum_reveal_bars=5, scenario_version="scenario-v1",
            )
        )
        await uow.commit()
    return scenario


def _outcome(scenario: HistoricalMarketScenario, *, calculation_version: str = "scenario-outcome-v1", **overrides) -> ScenarioOutcome:
    defaults: dict = dict(
        scenario_id=scenario.scenario_id,
        decision_at=scenario.decision_at,
        reveal_end_at=scenario.reveal_end_at,
        focal_start_close=100.0,
        focal_end_close=110.0,
        focal_return=0.10,
        maximum_future_upside=0.15,
        maximum_future_drawdown=-0.05,
        outcome_direction=ScenarioOutcomeDirection.POSITIVE,
        outcome_summary="It rose.",
        calculation_version=calculation_version,
    )
    defaults.update(overrides)
    return ScenarioOutcome(**defaults)


async def test_upsert_and_get_round_trip(uow_factory) -> None:
    scenario = await _seed_scenario(uow_factory)
    outcome = _outcome(scenario)

    async with uow_factory() as uow:
        created = await uow.scenario_outcomes.upsert(outcome)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.scenario_outcomes.get(scenario.scenario_id)

    assert fetched is not None
    assert fetched.focal_return == pytest.approx(0.10)
    assert fetched.outcome_direction == ScenarioOutcomeDirection.POSITIVE
    assert created.calculation_version == "scenario-outcome-v1"


async def test_upsert_is_idempotent_by_calculation_version(uow_factory) -> None:
    scenario = await _seed_scenario(uow_factory)
    outcome = _outcome(scenario, focal_return=0.10)

    async with uow_factory() as uow:
        await uow.scenario_outcomes.upsert(outcome)
        await uow.commit()

    updated_outcome = outcome.model_copy(update={"outcome_id": uuid4(), "focal_return": 0.20})
    async with uow_factory() as uow:
        await uow.scenario_outcomes.upsert(updated_outcome)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.scenario_outcomes.get(scenario.scenario_id, "scenario-outcome-v1")

    assert fetched.focal_return == pytest.approx(0.20)


async def test_different_calculation_versions_coexist(uow_factory) -> None:
    scenario = await _seed_scenario(uow_factory)
    v1 = _outcome(scenario, calculation_version="scenario-outcome-v1", focal_return=0.10)
    v2 = _outcome(scenario, calculation_version="scenario-outcome-v2", focal_return=0.20)

    async with uow_factory() as uow:
        await uow.scenario_outcomes.upsert(v1)
        await uow.scenario_outcomes.upsert(v2)
        await uow.commit()

    async with uow_factory() as uow:
        fetched_v1 = await uow.scenario_outcomes.get(scenario.scenario_id, "scenario-outcome-v1")
        fetched_v2 = await uow.scenario_outcomes.get(scenario.scenario_id, "scenario-outcome-v2")

    assert fetched_v1.focal_return == pytest.approx(0.10)
    assert fetched_v2.focal_return == pytest.approx(0.20)


async def test_get_returns_none_when_missing(uow_factory) -> None:
    scenario = await _seed_scenario(uow_factory)
    async with uow_factory() as uow:
        fetched = await uow.scenario_outcomes.get(scenario.scenario_id)
    assert fetched is None
