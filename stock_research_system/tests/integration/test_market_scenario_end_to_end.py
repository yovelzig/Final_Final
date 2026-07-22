"""PostgreSQL end-to-end integration tests for the historical market
scenario engine: real repositories, real `PandasScenarioCalculator`,
real `RuleBasedScenarioGradingPolicy`, and the real `LearningService`
as the `graded_answer_submitter` - the full learner flow against
Postgres/TimescaleDB.

`MarketScenarioLearningOrchestrator`'s own delegation logic is already
covered by `test_market_scenario_orchestrator.py` (fakes); this file
does not re-drive the full adaptive-session machinery, since that is
independently covered by the existing Phase 5 adaptive integration
tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from stock_research_core.application.exceptions import InvalidScenarioStateError
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAttempt,
    ExerciseOption,
    LearnerProfile,
    Lesson,
    LearningModule,
    LearningPath,
    Skill,
)
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
    ScenarioExpectedDirection,
    ScenarioRevealStatus,
    ScenarioSubmissionStatus,
)
from stock_research_core.domain.market_scenarios.models import (
    RUBRIC_COMPONENT_WEIGHTS,
    HistoricalMarketScenario,
    ScenarioOptionRubric,
)
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.infrastructure.market_scenarios.pandas_scenario_calculator import (
    PandasScenarioCalculator,
)

pytestmark = pytest.mark.integration

_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)
_MINIMUM_OBSERVATION_BARS = 40
_MINIMUM_REVEAL_BARS = 20


def _service(uow_factory) -> HistoricalMarketScenarioService:
    return HistoricalMarketScenarioService(
        unit_of_work_factory=uow_factory,
        scenario_calculator=PandasScenarioCalculator(),
        scenario_grading_policy=RuleBasedScenarioGradingPolicy(),
        graded_answer_submitter=LearningService(uow_factory),
    )


def _rubric(scenario_id, option_id, score: float, expected_direction: ScenarioExpectedDirection) -> ScenarioOptionRubric:
    return ScenarioOptionRubric(
        scenario_id=scenario_id,
        exercise_option_id=option_id,
        decision_quality_score=sum(score * weight for weight in RUBRIC_COMPONENT_WEIGHTS.values()),
        risk_awareness_score=score,
        benchmark_awareness_score=score,
        horizon_alignment_score=score,
        information_sufficiency_score=score,
        uncertainty_awareness_score=score,
        expected_direction=expected_direction,
        positive_feedback="Good reasoning.",
        improvement_feedback="Consider the benchmark next time.",
        rubric_version="scenario-rubric-v1",
    )


async def _seed_bars(uow, security_id, *, count: int, close_fn) -> None:
    bars = [
        MarketBar(
            security_id=security_id,
            timestamp=_EPOCH + timedelta(days=day),
            open=close_fn(day),
            high=close_fn(day) + 1,
            low=max(0.01, close_fn(day) - 1),
            close=close_fn(day),
            adjusted_close=close_fn(day),
            volume=1_000_000,
            interval="1d",
            source_name="test-source",
        )
        for day in range(count)
    ]
    await uow.market_bars.upsert_many(bars)


async def _seed_world(uow_factory, *, reveal_close_fn=None) -> dict:
    """90 daily bars: decision at day 59 (60 observation bars), reveal end
    at day 89 (30 reveal bars) - comfortably above the 40/20 minimums."""
    learner = LearnerProfile(display_name="Learner")
    skill = Skill(
        code=f"RISK_AND_RETURN_{uuid.uuid4().hex[:8].upper()}", name="Risk and Return", description="desc",
        category="RISK_AND_RETURN", difficulty=DifficultyLevel.MEDIUM,
    )
    security = Security(ticker=f"T{uuid.uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ)

    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        stored_skill = await uow.curriculum.upsert_skill(skill)
        stored_security = await uow.securities.upsert(security)

        path = await uow.curriculum.upsert_path(
            LearningPath(code=f"path-{uuid.uuid4().hex[:8]}", title="P", description="d",
                         difficulty=DifficultyLevel.MEDIUM, position=0, estimated_minutes=10, published=True)
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(path_id=path.path_id, code=f"mod-{uuid.uuid4().hex[:8]}", title="M", description="d",
                            position=0, estimated_minutes=10, published=True)
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(module_id=module.module_id, code=f"lesson-{uuid.uuid4().hex[:8]}", title="L", summary="s",
                   content_markdown="# c", difficulty=DifficultyLevel.MEDIUM, status="PUBLISHED",
                   position=0, estimated_minutes=10, primary_skill_id=stored_skill.skill_id)
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SCENARIO_DECISION,
                     prompt="Decide.", explanation="Explanation.", difficulty=DifficultyLevel.MEDIUM,
                     position=0, skill_ids=[stored_skill.skill_id], maximum_score=1.0, passing_score=0.6)
        )
        options = [
            ExerciseOption(exercise_id=exercise.exercise_id, option_key="good", content="Diversify.", position=0),
            ExerciseOption(exercise_id=exercise.exercise_id, option_key="bad", content="Chase the trend.", position=1),
        ]
        await uow.curriculum.upsert_options(options)
        stored_options = await uow.curriculum.list_options(exercise.exercise_id)

        await _seed_bars(uow, stored_security.security_id, count=60, close_fn=lambda day: 100.0 + day * 0.5)
        reveal_close_fn = reveal_close_fn or (lambda day: 130.0 + (day - 60) * 0.5)
        future_bars = [
            MarketBar(
                security_id=stored_security.security_id,
                timestamp=_EPOCH + timedelta(days=day),
                open=reveal_close_fn(day), high=reveal_close_fn(day) + 1, low=max(0.01, reveal_close_fn(day) - 1),
                close=reveal_close_fn(day), adjusted_close=reveal_close_fn(day),
                volume=1_000_000, interval="1d", source_name="test-source",
            )
            for day in range(60, 90)
        ]
        await uow.market_bars.upsert_many(future_bars)

        attempt = await uow.attempts.create_attempt(
            ExerciseAttempt(learner_id=stored_learner.learner_id, exercise_id=exercise.exercise_id,
                             maximum_score=1.0, attempt_number=1)
        )
        await uow.commit()

    scenario = HistoricalMarketScenario(
        exercise_id=exercise.exercise_id,
        code=f"TEST_{uuid.uuid4().hex[:10].upper()}",
        title="Test scenario",
        description="Description.",
        scenario_type=MarketScenarioType.MARKET_REPLAY,
        status=MarketScenarioStatus.PUBLISHED,
        observation_start_at=_EPOCH,
        decision_at=_EPOCH + timedelta(days=59),
        reveal_end_at=_EPOCH + timedelta(days=89),
        interval="1d",
        source_name="test-source",
        focal_security_id=stored_security.security_id,
        primary_skill_ids=[stored_skill.skill_id],
        prompt="Decide.",
        learner_instructions="Instructions.",
        learning_objectives=["Learn something."],
        minimum_observation_bars=_MINIMUM_OBSERVATION_BARS,
        minimum_reveal_bars=_MINIMUM_REVEAL_BARS,
        scenario_version="scenario-v1",
    )
    rubrics = [
        _rubric(scenario.scenario_id, stored_options[0].option_id, 0.9, ScenarioExpectedDirection.NEUTRAL),
        _rubric(scenario.scenario_id, stored_options[1].option_id, 0.2, ScenarioExpectedDirection.POSITIVE),
    ]

    service = _service(uow_factory)
    stored_scenario = await service.create_or_update_scenario(scenario=scenario, rubrics=rubrics)

    return dict(
        service=service,
        learner=stored_learner,
        security=stored_security,
        exercise=exercise,
        options=stored_options,
        scenario=stored_scenario,
        attempt=attempt,
        skill=stored_skill,
    )


async def test_learner_safe_view_hides_future_data_end_to_end(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    view = await world["service"].get_learner_view(
        learner_id=world["learner"].learner_id, scenario_id=world["scenario"].scenario_id
    )

    assert view.data_cutoff_at <= world["scenario"].decision_at
    assert all(point.timestamp <= world["scenario"].decision_at for point in view.focal_chart)
    for option in view.exercise_options:
        assert not hasattr(option, "is_correct")


async def test_scenario_submission_updates_skill_mastery_end_to_end(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    service = world["service"]

    started = await service.start_scenario(
        learner_id=world["learner"].learner_id,
        scenario_id=world["scenario"].scenario_id,
        exercise_attempt_id=world["attempt"].attempt_id,
    )
    result = await service.submit_decision(
        submission_id=started.submission_id, selected_option_id=world["options"][0].option_id
    )
    assert result.submission.status == ScenarioSubmissionStatus.GRADED
    assert result.submission.decision_quality_score == pytest.approx(0.9, abs=1e-6)

    async with uow_factory() as uow:
        mastery = await uow.mastery.get(world["learner"].learner_id, world["skill"].skill_id)
    assert mastery is not None
    assert mastery.mastery_score == pytest.approx(0.9, abs=1e-6)


async def test_reveal_works_end_to_end_and_is_idempotent(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    service = world["service"]

    started = await service.start_scenario(
        learner_id=world["learner"].learner_id,
        scenario_id=world["scenario"].scenario_id,
        exercise_attempt_id=world["attempt"].attempt_id,
    )
    with pytest.raises(InvalidScenarioStateError):
        await service.reveal_outcome(submission_id=started.submission_id)

    await service.submit_decision(submission_id=started.submission_id, selected_option_id=world["options"][0].option_id)

    first_reveal = await service.reveal_outcome(submission_id=started.submission_id)
    assert first_reveal.submission.reveal_status == ScenarioRevealStatus.REVEALED
    assert first_reveal.outcome.focal_return > 0  # prices rise throughout the reveal window

    second_reveal = await service.reveal_outcome(submission_id=started.submission_id)
    assert second_reveal.outcome.calculation_version == first_reveal.outcome.calculation_version
    assert second_reveal.outcome.focal_return == pytest.approx(first_reveal.outcome.focal_return)

    async with uow_factory() as uow:
        stored_outcomes = await uow.scenario_outcomes.get(world["scenario"].scenario_id)
    assert stored_outcomes is not None


async def test_future_bars_change_outcome_but_never_decision_quality_or_mastery(uow_factory) -> None:
    falling_world = await _seed_world(
        uow_factory, reveal_close_fn=lambda day: max(1.0, 130.0 - (day - 60) * 2.0)
    )
    service = falling_world["service"]

    started = await service.start_scenario(
        learner_id=falling_world["learner"].learner_id,
        scenario_id=falling_world["scenario"].scenario_id,
        exercise_attempt_id=falling_world["attempt"].attempt_id,
    )
    result = await service.submit_decision(
        submission_id=started.submission_id, selected_option_id=falling_world["options"][0].option_id
    )
    # Decision quality (a good, diversified choice) is unaffected by the
    # fact that the market happened to fall afterward.
    assert result.submission.decision_quality_score == pytest.approx(0.9, abs=1e-6)

    async with uow_factory() as uow:
        mastery = await uow.mastery.get(falling_world["learner"].learner_id, falling_world["skill"].skill_id)
    assert mastery.mastery_score == pytest.approx(0.9, abs=1e-6)

    reveal = await service.reveal_outcome(submission_id=started.submission_id)
    assert reveal.outcome.focal_return < 0  # this world's prices fell


async def test_failed_scenario_creation_does_not_persist_partial_state(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    service = world["service"]

    duplicate_code_scenario = HistoricalMarketScenario(
        exercise_id=world["exercise"].exercise_id,
        code=world["scenario"].code,  # already used - violates the unique constraint
        title="Duplicate",
        description="Description.",
        scenario_type=MarketScenarioType.MARKET_REPLAY,
        status=MarketScenarioStatus.DRAFT,
        observation_start_at=_EPOCH,
        decision_at=_EPOCH + timedelta(days=59),
        reveal_end_at=_EPOCH + timedelta(days=89),
        interval="1d",
        source_name="test-source",
        focal_security_id=world["security"].security_id,
        primary_skill_ids=[world["skill"].skill_id],
        prompt="Decide.",
        learner_instructions="Instructions.",
        learning_objectives=["Learn something."],
        minimum_observation_bars=_MINIMUM_OBSERVATION_BARS,
        minimum_reveal_bars=_MINIMUM_REVEAL_BARS,
        scenario_version="scenario-v1",
    )
    rubrics = [
        _rubric(duplicate_code_scenario.scenario_id, world["options"][0].option_id, 0.9, ScenarioExpectedDirection.NEUTRAL),
        _rubric(duplicate_code_scenario.scenario_id, world["options"][1].option_id, 0.2, ScenarioExpectedDirection.POSITIVE),
    ]

    with pytest.raises(Exception):  # noqa: B017 - a database-level unique-constraint violation
        await service.create_or_update_scenario(scenario=duplicate_code_scenario, rubrics=rubrics)

    async with uow_factory() as uow:
        fetched = await uow.market_scenarios.get(duplicate_code_scenario.scenario_id)
    assert fetched is None


async def test_seed_script_generation_is_idempotent(uow_factory) -> None:
    from scripts.seed_historical_market_scenarios import (
        _MINIMUM_OBSERVATION_BARS as SEED_MIN_OBSERVATION,
        _MINIMUM_REVEAL_BARS as SEED_MIN_REVEAL,
        _ensure_curriculum_scaffold,
        _seed_one_scenario,
        _select_decision_positions,
    )

    security = Security(ticker=f"SEED{uuid.uuid4().hex[:6].upper()}", company_name="Seed Co", exchange=Exchange.NASDAQ)
    async with uow_factory() as uow:
        stored_security = await uow.securities.upsert(security)
        await _seed_bars(
            uow, stored_security.security_id,
            count=SEED_MIN_OBSERVATION + SEED_MIN_REVEAL + 5,
            close_fn=lambda day: 100.0 + day * 0.25,
        )
        skill_ids = await _ensure_curriculum_scaffold(uow)
        bars = await uow.market_bars.list_range(
            stored_security.security_id, _EPOCH, _EPOCH + timedelta(days=365), interval="1d"
        )
        await uow.commit()

    positions = _select_decision_positions(len(bars), scenario_count=1)
    assert positions

    service = _service(uow_factory)
    target_skill_ids = [skill_ids["RISK_AND_RETURN"], skill_ids["CHART_READING"]]

    published_first = await _seed_one_scenario(
        unit_of_work_factory=uow_factory,
        market_scenario_service=service,
        ticker=security.ticker,
        focal_security_id=stored_security.security_id,
        benchmark_security_id=None,
        focal_bars=bars,
        position=positions[0],
        exercise_position=0,
        target_skill_ids=target_skill_ids,
    )
    published_second = await _seed_one_scenario(
        unit_of_work_factory=uow_factory,
        market_scenario_service=service,
        ticker=security.ticker,
        focal_security_id=stored_security.security_id,
        benchmark_security_id=None,
        focal_bars=bars,
        position=positions[0],
        exercise_position=0,
        target_skill_ids=target_skill_ids,
    )
    assert published_first is True
    assert published_second is True

    async with uow_factory() as uow:
        scenario = await uow.market_scenarios.get_by_code(f"{security.ticker}_{bars[positions[0]].timestamp.strftime('%Y%m%d')}")
        assert scenario is not None
        rubrics = await uow.scenario_rubrics.list_for_scenario(scenario.scenario_id)
    assert len(rubrics) == 5  # one per seeded option, not duplicated across the two runs
