"""PostgreSQL integration tests: `ScenarioSubmissionRepository`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

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
    MarketScenarioType,
    ScenarioDecisionQuality,
    ScenarioFeedbackCode,
    ScenarioRevealStatus,
    ScenarioSubmissionStatus,
)
from stock_research_core.domain.market_scenarios.models import HistoricalMarketScenario, ScenarioSubmission
from stock_research_core.domain.models import Security

pytestmark = pytest.mark.integration

# Deliberately far in the future relative to wall-clock time: `ScenarioSubmission.
# started_at` defaults to `utc_now()` when constructed directly by these
# tests, and that default must sort *before* this fixture's `NOW` for the
# timestamp-ordering validator to pass.
NOW = datetime(2100, 1, 1, tzinfo=timezone.utc)


async def _seed_world(uow_factory):
    learner = LearnerProfile(display_name="Learner")
    skill = Skill(
        code=f"RISK_AND_RETURN_{uuid4().hex[:8].upper()}", name="Risk and Return", description="desc",
        category="RISK_AND_RETURN", difficulty=DifficultyLevel.MEDIUM,
    )
    security = Security(ticker=f"T{uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ)
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
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
        await uow.curriculum.upsert_options(
            [ExerciseOption(exercise_id=exercise.exercise_id, option_key="opt-0", content="Option", position=0)]
        )
        option = (await uow.curriculum.list_options(exercise.exercise_id))[0]
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
        attempt = await uow.attempts.create_attempt(
            ExerciseAttempt(learner_id=stored_learner.learner_id, exercise_id=exercise.exercise_id,
                             maximum_score=1.0, attempt_number=1)
        )
        await uow.commit()
    return dict(learner=stored_learner, scenario=scenario, option=option, attempt=attempt)


def _submission(world: dict, **overrides) -> ScenarioSubmission:
    defaults: dict = dict(
        scenario_id=world["scenario"].scenario_id,
        learner_id=world["learner"].learner_id,
        exercise_attempt_id=world["attempt"].attempt_id,
        rubric_version="scenario-rubric-v1",
    )
    defaults.update(overrides)
    return ScenarioSubmission(**defaults)


async def test_create_and_get_round_trip(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    submission = _submission(world)

    async with uow_factory() as uow:
        created = await uow.scenario_submissions.create(submission)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.scenario_submissions.get(created.submission_id)

    assert fetched is not None
    assert fetched.status == ScenarioSubmissionStatus.STARTED
    assert fetched.scenario_id == world["scenario"].scenario_id


async def test_get_by_attempt(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    submission = _submission(world)
    async with uow_factory() as uow:
        created = await uow.scenario_submissions.create(submission)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.scenario_submissions.get_by_attempt(world["attempt"].attempt_id)

    assert fetched is not None
    assert fetched.submission_id == created.submission_id


async def test_update_round_trips_grading_fields_and_feedback_codes(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    submission = _submission(world)
    async with uow_factory() as uow:
        created = await uow.scenario_submissions.create(submission)
        await uow.commit()

    graded = created.model_copy(
        update={
            "status": ScenarioSubmissionStatus.GRADED,
            "selected_option_id": world["option"].option_id,
            "decision_quality_score": 0.73,
            "decision_quality": ScenarioDecisionQuality.GOOD,
            "feedback_codes": [ScenarioFeedbackCode.IDENTIFIED_RISK, ScenarioFeedbackCode.CONSIDERED_BENCHMARK],
            "feedback_text": "Well reasoned.",
            "reveal_status": ScenarioRevealStatus.AVAILABLE,
            "submitted_at": NOW,
            "graded_at": NOW,
        }
    )
    async with uow_factory() as uow:
        updated = await uow.scenario_submissions.update(graded)
        await uow.commit()

    assert updated.decision_quality_score == pytest.approx(0.73)
    assert set(updated.feedback_codes) == {
        ScenarioFeedbackCode.IDENTIFIED_RISK,
        ScenarioFeedbackCode.CONSIDERED_BENCHMARK,
    }

    async with uow_factory() as uow:
        fetched = await uow.scenario_submissions.get(created.submission_id)
    assert fetched.status == ScenarioSubmissionStatus.GRADED
    assert set(fetched.feedback_codes) == {
        ScenarioFeedbackCode.IDENTIFIED_RISK,
        ScenarioFeedbackCode.CONSIDERED_BENCHMARK,
    }


async def test_exercise_attempt_id_is_unique(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    submission_a = _submission(world)
    submission_b = _submission(world)

    async with uow_factory() as uow:
        await uow.scenario_submissions.create(submission_a)
        await uow.commit()

    with pytest.raises(Exception):  # noqa: B017 - a database-level unique-constraint violation
        async with uow_factory() as uow:
            await uow.scenario_submissions.create(submission_b)
            await uow.commit()


async def test_list_for_learner(uow_factory) -> None:
    world = await _seed_world(uow_factory)
    submission = _submission(world)
    async with uow_factory() as uow:
        created = await uow.scenario_submissions.create(submission)
        await uow.commit()

    async with uow_factory() as uow:
        submissions = await uow.scenario_submissions.list_for_learner(world["learner"].learner_id)

    assert {s.submission_id for s in submissions} == {created.submission_id}
