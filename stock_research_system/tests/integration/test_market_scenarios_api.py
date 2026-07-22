"""Integration tests for `/api/v1/scenarios/*` against the real PostgreSQL
test database, driven over HTTP - catalog, learner-safe view,
start/submit/reveal, and ownership.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.conftest import auth_headers
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType, LessonStatus
from stock_research_core.domain.learning.models import Exercise, ExerciseOption, Lesson, LearningModule, LearningPath, Skill
from stock_research_core.domain.market_scenarios.enums import MarketScenarioStatus, MarketScenarioType, ScenarioExpectedDirection
from stock_research_core.domain.market_scenarios.models import RUBRIC_COMPONENT_WEIGHTS, HistoricalMarketScenario, ScenarioOptionRubric
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.infrastructure.market_scenarios.pandas_scenario_calculator import PandasScenarioCalculator

pytestmark = pytest.mark.integration

_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)
_MIN_OBS = 40
_MIN_REVEAL = 20


def _email() -> str:
    return f"scenario-{uuid.uuid4().hex[:10]}@example.com"


def _rubric(scenario_id, option_id, score, direction) -> ScenarioOptionRubric:
    return ScenarioOptionRubric(
        scenario_id=scenario_id, exercise_option_id=option_id,
        decision_quality_score=sum(score * w for w in RUBRIC_COMPONENT_WEIGHTS.values()),
        risk_awareness_score=score, benchmark_awareness_score=score, horizon_alignment_score=score,
        information_sufficiency_score=score, uncertainty_awareness_score=score,
        expected_direction=direction, positive_feedback="Good reasoning.",
        improvement_feedback="Consider the benchmark.", rubric_version="scenario-rubric-v1",
    )


async def _seed_scenario(uow_factory) -> dict:
    suffix = uuid.uuid4().hex[:8].upper()
    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(code=f"SCEN_{suffix}", name="Scenario Skill", description="d", category="RISK_AND_RETURN", difficulty=DifficultyLevel.MEDIUM)
        )
        security = await uow.securities.upsert(Security(ticker=f"SC{suffix[:6]}", company_name="Scenario Co", exchange=Exchange.NASDAQ))
        path = await uow.curriculum.upsert_path(
            LearningPath(code=f"path-{suffix}", title="P", description="d", difficulty=DifficultyLevel.MEDIUM, position=0, estimated_minutes=10, published=True)
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(path_id=path.path_id, code="mod", title="M", description="d", position=0, estimated_minutes=10, published=True)
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(module_id=module.module_id, code="lesson", title="L", summary="s", content_markdown="# c", difficulty=DifficultyLevel.MEDIUM, status=LessonStatus.PUBLISHED, position=0, estimated_minutes=10, primary_skill_id=skill.skill_id)
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SCENARIO_DECISION, prompt="Decide.", explanation="E.", difficulty=DifficultyLevel.MEDIUM, position=0, skill_ids=[skill.skill_id], maximum_score=1.0, passing_score=0.6)
        )
        options = [
            ExerciseOption(exercise_id=exercise.exercise_id, option_key="good", content="Diversify.", position=0),
            ExerciseOption(exercise_id=exercise.exercise_id, option_key="bad", content="Chase trend.", position=1),
        ]
        await uow.curriculum.upsert_options(options)
        stored_options = await uow.curriculum.list_options(exercise.exercise_id)

        bars = [
            MarketBar(security_id=security.security_id, timestamp=_EPOCH + timedelta(days=d), open=100.0 + d * 0.5, high=101.0 + d * 0.5, low=max(0.01, 99.0 + d * 0.5), close=100.0 + d * 0.5, adjusted_close=100.0 + d * 0.5, volume=1_000_000, interval="1d", source_name="test-source")
            for d in range(60)
        ]
        future_bars = [
            MarketBar(security_id=security.security_id, timestamp=_EPOCH + timedelta(days=d), open=130.0 + (d - 60) * 0.5, high=131.0 + (d - 60) * 0.5, low=max(0.01, 129.0 + (d - 60) * 0.5), close=130.0 + (d - 60) * 0.5, adjusted_close=130.0 + (d - 60) * 0.5, volume=1_000_000, interval="1d", source_name="test-source")
            for d in range(60, 90)
        ]
        await uow.market_bars.upsert_many(bars)
        await uow.market_bars.upsert_many(future_bars)
        await uow.commit()

    scenario = HistoricalMarketScenario(
        exercise_id=exercise.exercise_id, code=f"SC_{suffix}", title="Scenario", description="D.",
        scenario_type=MarketScenarioType.MARKET_REPLAY, status=MarketScenarioStatus.PUBLISHED,
        observation_start_at=_EPOCH, decision_at=_EPOCH + timedelta(days=59), reveal_end_at=_EPOCH + timedelta(days=89),
        interval="1d", source_name="test-source", focal_security_id=security.security_id,
        primary_skill_ids=[skill.skill_id], prompt="Decide.", learner_instructions="Instructions.",
        learning_objectives=["Learn."], minimum_observation_bars=_MIN_OBS, minimum_reveal_bars=_MIN_REVEAL,
        scenario_version="scenario-v1",
    )
    rubrics = [
        _rubric(scenario.scenario_id, stored_options[0].option_id, 0.9, ScenarioExpectedDirection.NEUTRAL),
        _rubric(scenario.scenario_id, stored_options[1].option_id, 0.2, ScenarioExpectedDirection.POSITIVE),
    ]
    scenario_service = HistoricalMarketScenarioService(
        unit_of_work_factory=uow_factory, scenario_calculator=PandasScenarioCalculator(),
        scenario_grading_policy=RuleBasedScenarioGradingPolicy(), graded_answer_submitter=LearningService(uow_factory),
    )
    stored_scenario = await scenario_service.create_or_update_scenario(scenario=scenario, rubrics=rubrics)
    return {"scenario_id": stored_scenario.scenario_id, "good_option_id": stored_options[0].option_id}


async def test_full_catalog_view_start_submit_reveal_flow(api_client, uow_factory) -> None:
    world = await _seed_scenario(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.get("/api/v1/scenarios", headers=headers)
    assert r.status_code == 200
    assert any(s["scenario_id"] == str(world["scenario_id"]) for s in r.json())

    r = await api_client.get(f"/api/v1/scenarios/{world['scenario_id']}", headers=headers)
    assert r.status_code == 200
    view = r.json()
    assert "outcome" not in view
    for option in view["exercise_options"]:
        assert "is_correct" not in option

    r = await api_client.post(f"/api/v1/scenarios/{world['scenario_id']}/start", headers=headers)
    assert r.status_code == 201
    submission_id = r.json()["submission_id"]
    assert r.json()["status"] == "STARTED"

    r = await api_client.post(f"/api/v1/scenarios/submissions/{submission_id}/reveal", headers=headers)
    assert r.status_code in (400, 409)

    r = await api_client.post(
        f"/api/v1/scenarios/submissions/{submission_id}/submit", headers=headers,
        json={"selected_option_id": str(world["good_option_id"]), "confidence_level": "MEDIUM"},
    )
    assert r.status_code == 200
    graded = r.json()
    assert graded["status"] == "GRADED"
    assert graded["decision_quality_score"] is not None
    assert graded["outcome_alignment_score"] is None

    r = await api_client.post(f"/api/v1/scenarios/submissions/{submission_id}/reveal", headers=headers)
    assert r.status_code == 200
    reveal = r.json()
    assert reveal["submission"]["reveal_status"] == "REVEALED"
    assert len(reveal["future_focal_chart"]) > 0

    r = await api_client.get(f"/api/v1/scenarios/submissions/{submission_id}/reveal", headers=headers)
    assert r.status_code == 200


async def test_submission_ownership_is_enforced(api_client, uow_factory) -> None:
    world = await _seed_scenario(uow_factory)
    owner_headers = await auth_headers(api_client, email=_email())
    other_headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(f"/api/v1/scenarios/{world['scenario_id']}/start", headers=owner_headers)
    submission_id = r.json()["submission_id"]

    r = await api_client.post(
        f"/api/v1/scenarios/submissions/{submission_id}/submit", headers=other_headers,
        json={"selected_option_id": str(world["good_option_id"])},
    )
    assert r.status_code == 404


async def test_scenarios_require_authentication(api_client) -> None:
    response = await api_client.get("/api/v1/scenarios")
    assert response.status_code == 401
