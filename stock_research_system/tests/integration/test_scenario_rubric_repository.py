"""PostgreSQL integration tests: `ScenarioRubricRepository`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseOption,
    Lesson,
    LearningModule,
    LearningPath,
    Skill,
)
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioType,
    ScenarioExpectedDirection,
    ScenarioFeedbackCode,
)
from stock_research_core.domain.market_scenarios.models import (
    RUBRIC_COMPONENT_WEIGHTS,
    HistoricalMarketScenario,
    ScenarioOptionRubric,
)
from stock_research_core.domain.models import Security

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_scenario_with_options(uow_factory, option_count: int = 2):
    skill = Skill(
        code=f"RISK_AND_RETURN_{uuid4().hex[:8].upper()}",
        name="Risk and Return", description="desc",
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
        options = [
            ExerciseOption(exercise_id=exercise.exercise_id, option_key=f"opt-{i}", content=f"Option {i}", position=i)
            for i in range(option_count)
        ]
        await uow.curriculum.upsert_options(options)

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
    return scenario, options


def _rubric(scenario_id, option_id, score: float = 0.7, **overrides) -> ScenarioOptionRubric:
    defaults: dict = dict(
        scenario_id=scenario_id,
        exercise_option_id=option_id,
        decision_quality_score=sum(score * weight for weight in RUBRIC_COMPONENT_WEIGHTS.values()),
        risk_awareness_score=score,
        benchmark_awareness_score=score,
        horizon_alignment_score=score,
        information_sufficiency_score=score,
        uncertainty_awareness_score=score,
        expected_direction=ScenarioExpectedDirection.NEUTRAL,
        feedback_codes=[ScenarioFeedbackCode.IDENTIFIED_RISK],
        positive_feedback="Good.",
        improvement_feedback="Better.",
        rubric_version="scenario-rubric-v1",
    )
    defaults.update(overrides)
    return ScenarioOptionRubric(**defaults)


async def test_upsert_many_round_trips_component_scores_and_feedback_codes(uow_factory) -> None:
    scenario, options = await _seed_scenario_with_options(uow_factory)
    rubrics = [_rubric(scenario.scenario_id, option.option_id) for option in options]

    async with uow_factory() as uow:
        count = await uow.scenario_rubrics.upsert_many(rubrics)
        await uow.commit()
    assert count == len(rubrics)

    async with uow_factory() as uow:
        fetched = await uow.scenario_rubrics.get_for_option(scenario.scenario_id, options[0].option_id)

    assert fetched is not None
    assert fetched.decision_quality_score == pytest.approx(rubrics[0].decision_quality_score)
    assert fetched.feedback_codes == [ScenarioFeedbackCode.IDENTIFIED_RISK]
    assert fetched.expected_direction == ScenarioExpectedDirection.NEUTRAL


async def test_upsert_many_is_idempotent(uow_factory) -> None:
    scenario, options = await _seed_scenario_with_options(uow_factory, option_count=3)
    rubrics = [_rubric(scenario.scenario_id, option.option_id) for option in options]

    async with uow_factory() as uow:
        await uow.scenario_rubrics.upsert_many(rubrics)
        await uow.commit()
    async with uow_factory() as uow:
        await uow.scenario_rubrics.upsert_many(rubrics)
        await uow.commit()

    async with uow_factory() as uow:
        all_rubrics = await uow.scenario_rubrics.list_for_scenario(scenario.scenario_id)
    assert len(all_rubrics) == len(options)


async def test_upsert_many_updates_scores_in_place(uow_factory) -> None:
    scenario, options = await _seed_scenario_with_options(uow_factory, option_count=1)
    rubric = _rubric(scenario.scenario_id, options[0].option_id, score=0.5)
    async with uow_factory() as uow:
        await uow.scenario_rubrics.upsert_many([rubric])
        await uow.commit()

    updated = _rubric(scenario.scenario_id, options[0].option_id, score=0.9)
    async with uow_factory() as uow:
        await uow.scenario_rubrics.upsert_many([updated])
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.scenario_rubrics.get_for_option(scenario.scenario_id, options[0].option_id)
    assert fetched.decision_quality_score == pytest.approx(updated.decision_quality_score)


async def test_list_for_scenario_returns_all_option_rubrics(uow_factory) -> None:
    scenario, options = await _seed_scenario_with_options(uow_factory, option_count=4)
    rubrics = [_rubric(scenario.scenario_id, option.option_id) for option in options]
    async with uow_factory() as uow:
        await uow.scenario_rubrics.upsert_many(rubrics)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.scenario_rubrics.list_for_scenario(scenario.scenario_id)

    assert {r.exercise_option_id for r in fetched} == {o.option_id for o in options}


async def test_get_for_option_returns_none_when_missing(uow_factory) -> None:
    scenario, options = await _seed_scenario_with_options(uow_factory, option_count=1)
    async with uow_factory() as uow:
        fetched = await uow.scenario_rubrics.get_for_option(scenario.scenario_id, uuid4())
    assert fetched is None
