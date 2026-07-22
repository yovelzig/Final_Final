"""Unit tests for `HistoricalMarketScenarioService`.

Fake repository/port implementations and a fake Unit of Work - no
SQLAlchemy, PostgreSQL, or yfinance is involved anywhere in this file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.exceptions import (
    InactiveLearnerError,
    InvalidScenarioStateError,
    LearnerNotFoundError,
)
from stock_research_core.application.learning.models import LearningActivityResult
from stock_research_core.application.market_scenarios.models import LearnerScenarioView
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import AttemptStatus, ConfidenceLevel, DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseAttempt,
    ExerciseOption,
    LearnerProfile,
)
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
    ScenarioDecisionQuality,
    ScenarioExpectedDirection,
    ScenarioRevealStatus,
    ScenarioSubmissionStatus,
)
from stock_research_core.domain.market_scenarios.models import (
    RUBRIC_COMPONENT_WEIGHTS,
    HistoricalMarketScenario,
    ScenarioOptionRubric,
    ScenarioOutcome,
    ScenarioSubmission,
)
from stock_research_core.domain.models import MarketBar, Security

# Deliberately far in the future relative to wall-clock time: several
# domain models (e.g. `ScenarioSubmission.started_at`) default to
# `utc_now()` when a test constructs one directly (bypassing the
# service's injected `clock`), and those defaults must sort *before*
# this fixture's `NOW` for timestamp-ordering validators to pass.
NOW = datetime(2100, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLearnerRepository:
    def __init__(self) -> None:
        self.learners: dict[UUID, LearnerProfile] = {}

    async def create(self, learner: LearnerProfile) -> LearnerProfile:
        self.learners[learner.learner_id] = learner
        return learner

    async def get(self, learner_id: UUID) -> LearnerProfile | None:
        return self.learners.get(learner_id)

    async def update(self, learner: LearnerProfile) -> LearnerProfile:
        self.learners[learner.learner_id] = learner
        return learner

    async def set_active(self, learner_id: UUID, active: bool) -> LearnerProfile:
        updated = self.learners[learner_id].model_copy(update={"active": active})
        self.learners[learner_id] = updated
        return updated


class FakeSecurityRepository:
    def __init__(self) -> None:
        self.securities: dict[UUID, Security] = {}

    async def upsert(self, security: Security) -> Security:
        self.securities[security.security_id] = security
        return security

    async def get_by_id(self, security_id: UUID) -> Security | None:
        return self.securities.get(security_id)

    async def get_by_ticker(self, ticker: str, exchange=None) -> Security | None:
        for security in self.securities.values():
            if security.ticker == ticker.upper():
                return security
        return None


class FakeMarketBarRepository:
    def __init__(self) -> None:
        self.bars: list[MarketBar] = []
        self.list_range_calls: list[tuple] = []

    async def upsert_many(self, bars: list[MarketBar]) -> int:
        self.bars.extend(bars)
        return len(bars)

    async def list_range(
        self, security_id: UUID, start_at: datetime, end_at: datetime, interval: str = "1d", source_name=None
    ) -> list[MarketBar]:
        self.list_range_calls.append((security_id, start_at, end_at, interval))
        return sorted(
            (
                bar
                for bar in self.bars
                if bar.security_id == security_id
                and bar.interval == interval
                and start_at <= bar.timestamp <= end_at
            ),
            key=lambda bar: bar.timestamp,
        )

    async def get_latest_timestamp(self, security_id, interval="1d", source_name=None):
        matching = [bar.timestamp for bar in self.bars if bar.security_id == security_id]
        return max(matching) if matching else None

    async def count(self, security_id, interval="1d") -> int:
        return sum(1 for bar in self.bars if bar.security_id == security_id)


class FakeCurriculumRepository:
    def __init__(self) -> None:
        self.exercises: dict[UUID, Exercise] = {}
        self.options: dict[UUID, list[ExerciseOption]] = {}

    async def get_exercise(self, exercise_id: UUID) -> Exercise | None:
        return self.exercises.get(exercise_id)

    async def list_options(self, exercise_id: UUID) -> list[ExerciseOption]:
        return list(self.options.get(exercise_id, []))

    # Unused by these tests but present for Protocol compatibility if ever needed.
    async def upsert_exercise(self, exercise: Exercise) -> Exercise:
        self.exercises[exercise.exercise_id] = exercise
        return exercise

    async def upsert_options(self, options: list[ExerciseOption]) -> int:
        for option in options:
            bucket = self.options.setdefault(option.exercise_id, [])
            bucket[:] = [o for o in bucket if o.option_id != option.option_id]
            bucket.append(option)
        return len(options)


class FakeAttemptRepository:
    def __init__(self) -> None:
        self.attempts: dict[UUID, ExerciseAttempt] = {}

    async def create_attempt(self, attempt: ExerciseAttempt) -> ExerciseAttempt:
        self.attempts[attempt.attempt_id] = attempt
        return attempt

    async def get_attempt(self, attempt_id: UUID) -> ExerciseAttempt | None:
        return self.attempts.get(attempt_id)


class FakeAdaptiveProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[UUID, object] = {}

    async def get_by_exercise(self, exercise_id: UUID):
        return self.profiles.get(exercise_id)


class FakeMarketScenarioRepository:
    def __init__(self) -> None:
        self.scenarios: dict[UUID, HistoricalMarketScenario] = {}

    async def upsert(self, scenario: HistoricalMarketScenario) -> HistoricalMarketScenario:
        self.scenarios[scenario.scenario_id] = scenario
        return scenario

    async def get(self, scenario_id: UUID) -> HistoricalMarketScenario | None:
        return self.scenarios.get(scenario_id)

    async def get_by_code(self, code: str) -> HistoricalMarketScenario | None:
        return next((s for s in self.scenarios.values() if s.code == code), None)

    async def get_by_exercise_id(self, exercise_id: UUID) -> HistoricalMarketScenario | None:
        return next((s for s in self.scenarios.values() if s.exercise_id == exercise_id), None)

    async def list_published(self, skill_id=None, scenario_type=None) -> list[HistoricalMarketScenario]:
        values = [s for s in self.scenarios.values() if s.status == MarketScenarioStatus.PUBLISHED]
        if scenario_type is not None:
            values = [s for s in values if s.scenario_type == scenario_type]
        if skill_id is not None:
            values = [s for s in values if skill_id in s.primary_skill_ids]
        return sorted(values, key=lambda s: s.code)

    async def set_status(self, scenario_id: UUID, status: MarketScenarioStatus) -> HistoricalMarketScenario:
        updated = self.scenarios[scenario_id].model_copy(update={"status": status})
        self.scenarios[scenario_id] = updated
        return updated


class FakeScenarioRubricRepository:
    def __init__(self) -> None:
        self.rubrics: dict[tuple[UUID, UUID], ScenarioOptionRubric] = {}

    async def upsert_many(self, rubrics: list[ScenarioOptionRubric]) -> int:
        for rubric in rubrics:
            self.rubrics[(rubric.scenario_id, rubric.exercise_option_id)] = rubric
        return len(rubrics)

    async def get_for_option(self, scenario_id: UUID, exercise_option_id: UUID) -> ScenarioOptionRubric | None:
        return self.rubrics.get((scenario_id, exercise_option_id))

    async def list_for_scenario(self, scenario_id: UUID) -> list[ScenarioOptionRubric]:
        return [r for (sid, _oid), r in self.rubrics.items() if sid == scenario_id]


class FakeScenarioOutcomeRepository:
    def __init__(self) -> None:
        self.outcomes: dict[tuple[UUID, str], ScenarioOutcome] = {}
        self.upsert_calls = 0

    async def upsert(self, outcome: ScenarioOutcome) -> ScenarioOutcome:
        self.upsert_calls += 1
        self.outcomes[(outcome.scenario_id, outcome.calculation_version)] = outcome
        return outcome

    async def get(self, scenario_id: UUID, calculation_version: str | None = None) -> ScenarioOutcome | None:
        if calculation_version is not None:
            return self.outcomes.get((scenario_id, calculation_version))
        matching = [o for (sid, _v), o in self.outcomes.items() if sid == scenario_id]
        return matching[0] if matching else None


class FakeScenarioSubmissionRepository:
    def __init__(self) -> None:
        self.submissions: dict[UUID, ScenarioSubmission] = {}
        self.fail_on_create = False

    async def create(self, submission: ScenarioSubmission) -> ScenarioSubmission:
        if self.fail_on_create:
            raise RuntimeError("simulated database failure")
        self.submissions[submission.submission_id] = submission
        return submission

    async def get(self, submission_id: UUID) -> ScenarioSubmission | None:
        return self.submissions.get(submission_id)

    async def get_by_attempt(self, exercise_attempt_id: UUID) -> ScenarioSubmission | None:
        return next(
            (s for s in self.submissions.values() if s.exercise_attempt_id == exercise_attempt_id), None
        )

    async def update(self, submission: ScenarioSubmission) -> ScenarioSubmission:
        self.submissions[submission.submission_id] = submission
        return submission

    async def list_for_learner(self, learner_id: UUID) -> list[ScenarioSubmission]:
        return [s for s in self.submissions.values() if s.learner_id == learner_id]


class FakeUnitOfWork:
    def __init__(self, repos: dict) -> None:
        for name, repo in repos.items():
            setattr(self, name, repo)
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None:
            self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeUnitOfWorkFactory:
    def __init__(self) -> None:
        self.learners = FakeLearnerRepository()
        self.securities = FakeSecurityRepository()
        self.market_bars = FakeMarketBarRepository()
        self.curriculum = FakeCurriculumRepository()
        self.attempts = FakeAttemptRepository()
        self.adaptive_profiles = FakeAdaptiveProfileRepository()
        self.market_scenarios = FakeMarketScenarioRepository()
        self.scenario_rubrics = FakeScenarioRubricRepository()
        self.scenario_outcomes = FakeScenarioOutcomeRepository()
        self.scenario_submissions = FakeScenarioSubmissionRepository()
        self.instances: list[FakeUnitOfWork] = []

    def __call__(self) -> FakeUnitOfWork:
        uow = FakeUnitOfWork(
            {
                "learners": self.learners,
                "securities": self.securities,
                "market_bars": self.market_bars,
                "curriculum": self.curriculum,
                "attempts": self.attempts,
                "adaptive_profiles": self.adaptive_profiles,
                "market_scenarios": self.market_scenarios,
                "scenario_rubrics": self.scenario_rubrics,
                "scenario_outcomes": self.scenario_outcomes,
                "scenario_submissions": self.scenario_submissions,
            }
        )
        self.instances.append(uow)
        return uow


class FakeScenarioCalculator:
    def __init__(self, observation_metrics=None, outcome_factory=None) -> None:
        self.observation_metrics = observation_metrics
        self.outcome_factory = outcome_factory
        self.observation_calls: list[tuple] = []
        self.outcome_calls: list[tuple] = []

    async def calculate_observation(self, *, scenario, focal_bars, benchmark_bars):
        self.observation_calls.append((scenario, tuple(focal_bars), tuple(benchmark_bars)))
        return self.observation_metrics

    async def calculate_outcome(self, *, scenario, focal_bars, benchmark_bars):
        self.outcome_calls.append((scenario, tuple(focal_bars), tuple(benchmark_bars)))
        return self.outcome_factory(scenario)


class FakeGradingPolicy:
    def __init__(self, score: float = 0.7, quality=ScenarioDecisionQuality.GOOD) -> None:
        self.score = score
        self.quality = quality
        self.grade_calls: list[tuple] = []

    def grade(self, *, scenario, rubric, confidence_level, learner_rationale):
        self.grade_calls.append((scenario, rubric, confidence_level, learner_rationale))
        return self.score, self.quality, [], "Good reasoning."

    def calculate_outcome_alignment(self, *, rubric, outcome):
        return 0.5

    def build_reveal_feedback(self, *, submission, rubric, outcome):
        return "decision feedback", "outcome feedback", "combined summary"


class FakeGradedAnswerSubmitter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def submit_externally_graded_answer(
        self, *, attempt_id, answer, normalized_score, is_correct, grading_version
    ) -> LearningActivityResult:
        self.calls.append(
            dict(
                attempt_id=attempt_id,
                answer=answer,
                normalized_score=normalized_score,
                is_correct=is_correct,
                grading_version=grading_version,
            )
        )
        attempt = ExerciseAttempt(
            attempt_id=attempt_id,
            learner_id=uuid4(),
            exercise_id=uuid4(),
            status=AttemptStatus.GRADED,
            maximum_score=1.0,
            score=normalized_score,
            is_correct=is_correct,
            attempt_number=1,
            grading_version=grading_version,
            started_at=NOW,
            submitted_at=NOW,
            graded_at=NOW,
        )
        return LearningActivityResult(attempt=attempt, answer=answer, updated_mastery=[], updated_progress=None)


# ---------------------------------------------------------------------------
# World-builder helpers
# ---------------------------------------------------------------------------


def _security(ticker: str = "NVDA") -> Security:
    return Security(ticker=ticker, company_name="Test Co", exchange=Exchange.NASDAQ)


def _bar(security_id: UUID, day_offset: int, close: float = 100.0) -> MarketBar:
    return MarketBar(
        security_id=security_id,
        timestamp=NOW - timedelta(days=60) + timedelta(days=day_offset),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        adjusted_close=close,
        volume=1000,
        interval="1d",
        source_name="test-source",
    )


def _exercise(exercise_id: UUID) -> Exercise:
    return Exercise(
        exercise_id=exercise_id,
        lesson_id=uuid4(),
        exercise_type=ExerciseType.SCENARIO_DECISION,
        prompt="Decide.",
        explanation="Explanation.",
        difficulty=DifficultyLevel.MEDIUM,
        position=0,
        skill_ids=[uuid4()],
        maximum_score=1.0,
        passing_score=0.6,
    )


def _options(exercise_id: UUID, count: int = 2) -> list[ExerciseOption]:
    return [
        ExerciseOption(exercise_id=exercise_id, option_key=f"opt-{i}", content=f"Option {i}", position=i)
        for i in range(count)
    ]


def _scenario(
    *, exercise_id: UUID, focal_security_id: UUID, status: MarketScenarioStatus = MarketScenarioStatus.PUBLISHED
) -> HistoricalMarketScenario:
    return HistoricalMarketScenario(
        exercise_id=exercise_id,
        code="NVDA_20240101",
        title="Test scenario",
        description="A test scenario.",
        scenario_type=MarketScenarioType.MARKET_REPLAY,
        status=status,
        observation_start_at=NOW - timedelta(days=60),
        decision_at=NOW - timedelta(days=20),
        reveal_end_at=NOW,
        interval="1d",
        source_name="test-source",
        focal_security_id=focal_security_id,
        primary_skill_ids=[uuid4()],
        prompt="Decide.",
        learner_instructions="Instructions.",
        learning_objectives=["Learn something."],
        minimum_observation_bars=5,
        minimum_reveal_bars=5,
        scenario_version="scenario-v1",
    )


def _rubric(scenario_id: UUID, option_id: UUID, score: float = 0.7) -> ScenarioOptionRubric:
    component = score
    return ScenarioOptionRubric(
        scenario_id=scenario_id,
        exercise_option_id=option_id,
        decision_quality_score=sum(component * weight for weight in RUBRIC_COMPONENT_WEIGHTS.values()),
        risk_awareness_score=component,
        benchmark_awareness_score=component,
        horizon_alignment_score=component,
        information_sufficiency_score=component,
        uncertainty_awareness_score=component,
        expected_direction=ScenarioExpectedDirection.NEUTRAL,
        positive_feedback="Good.",
        improvement_feedback="Better next time.",
        rubric_version="scenario-rubric-v1",
    )


def _build_service(factory: FakeUnitOfWorkFactory, calculator=None, grading_policy=None, submitter=None):
    return HistoricalMarketScenarioService(
        unit_of_work_factory=factory,
        scenario_calculator=calculator or FakeScenarioCalculator(),
        scenario_grading_policy=grading_policy or FakeGradingPolicy(),
        graded_answer_submitter=submitter or FakeGradedAnswerSubmitter(),
        clock=lambda: NOW,
    )


async def _seed_world(factory: FakeUnitOfWorkFactory) -> dict:
    learner = LearnerProfile(display_name="Learner", active=True)
    factory.learners.learners[learner.learner_id] = learner

    security = _security()
    factory.securities.securities[security.security_id] = security

    exercise = _exercise(uuid4())
    factory.curriculum.exercises[exercise.exercise_id] = exercise
    options = _options(exercise.exercise_id, count=2)
    factory.curriculum.options[exercise.exercise_id] = options

    scenario = _scenario(exercise_id=exercise.exercise_id, focal_security_id=security.security_id)
    factory.market_scenarios.scenarios[scenario.scenario_id] = scenario

    for option in options:
        rubric = _rubric(scenario.scenario_id, option.option_id)
        factory.scenario_rubrics.rubrics[(scenario.scenario_id, option.option_id)] = rubric

    for i in range(61):
        bar = _bar(security.security_id, i)
        factory.market_bars.bars.append(bar)

    attempt = ExerciseAttempt(
        learner_id=learner.learner_id,
        exercise_id=exercise.exercise_id,
        maximum_score=1.0,
        attempt_number=1,
    )
    factory.attempts.attempts[attempt.attempt_id] = attempt

    return dict(learner=learner, security=security, exercise=exercise, options=options, scenario=scenario, attempt=attempt)


def _fake_observation_metrics():
    from stock_research_core.domain.market_scenarios.models import ScenarioObservationMetrics

    return ScenarioObservationMetrics(
        data_cutoff_at=NOW - timedelta(days=20),
        observation_bar_count=40,
        start_close=100.0,
        decision_close=110.0,
        observation_return=0.10,
        price_change_percentage=10.0,
        highest_close=112.0,
        lowest_close=98.0,
        calculation_version="scenario-observation-v1",
    )


def _fake_outcome(scenario: HistoricalMarketScenario) -> ScenarioOutcome:
    return ScenarioOutcome(
        scenario_id=scenario.scenario_id,
        decision_at=scenario.decision_at,
        reveal_end_at=scenario.reveal_end_at,
        focal_start_close=110.0,
        focal_end_close=120.0,
        focal_return=0.09,
        maximum_future_upside=0.12,
        maximum_future_drawdown=-0.02,
        outcome_direction="POSITIVE",
        outcome_summary="It rose.",
        calculation_version="scenario-outcome-v1",
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


async def test_list_scenarios_returns_published_only() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    draft_scenario = _scenario(
        exercise_id=uuid4(), focal_security_id=world["security"].security_id, status=MarketScenarioStatus.DRAFT
    )
    factory.market_scenarios.scenarios[draft_scenario.scenario_id] = draft_scenario
    factory.curriculum.exercises[draft_scenario.exercise_id] = _exercise(draft_scenario.exercise_id)

    service = _build_service(factory)
    items = await service.list_scenarios()

    assert len(items) == 1
    assert items[0].scenario_id == world["scenario"].scenario_id
    assert items[0].published is True


# ---------------------------------------------------------------------------
# Learner-safe view
# ---------------------------------------------------------------------------


async def test_learner_view_rejects_inactive_learner() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    factory.learners.learners[world["learner"].learner_id] = world["learner"].model_copy(update={"active": False})
    service = _build_service(factory, calculator=FakeScenarioCalculator(observation_metrics=_fake_observation_metrics()))

    with pytest.raises(InactiveLearnerError):
        await service.get_learner_view(learner_id=world["learner"].learner_id, scenario_id=world["scenario"].scenario_id)


async def test_learner_view_rejects_unknown_learner() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    service = _build_service(factory, calculator=FakeScenarioCalculator(observation_metrics=_fake_observation_metrics()))

    with pytest.raises(LearnerNotFoundError):
        await service.get_learner_view(learner_id=uuid4(), scenario_id=world["scenario"].scenario_id)


async def test_learner_view_only_requests_bars_up_to_decision_at() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    calculator = FakeScenarioCalculator(observation_metrics=_fake_observation_metrics())
    service = _build_service(factory, calculator=calculator)

    view = await service.get_learner_view(learner_id=world["learner"].learner_id, scenario_id=world["scenario"].scenario_id)

    assert isinstance(view, LearnerScenarioView)
    assert len(calculator.observation_calls) == 1
    assert calculator.outcome_calls == []
    (_, focal_bars, _benchmark_bars) = calculator.observation_calls[0]
    assert all(bar.timestamp <= world["scenario"].decision_at for bar in focal_bars)
    # market_bars.list_range must have been called with decision_at as the end bound.
    _security_id, _start_at, end_at, _interval = factory.market_bars.list_range_calls[-1]
    assert end_at == world["scenario"].decision_at


async def test_learner_view_hides_option_correctness_and_rubrics() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    service = _build_service(factory, calculator=FakeScenarioCalculator(observation_metrics=_fake_observation_metrics()))

    view = await service.get_learner_view(learner_id=world["learner"].learner_id, scenario_id=world["scenario"].scenario_id)

    for option in view.exercise_options:
        assert not hasattr(option, "is_correct")
    assert not hasattr(view, "rubrics")
    assert not hasattr(view, "outcome")


# ---------------------------------------------------------------------------
# start_scenario
# ---------------------------------------------------------------------------


async def test_start_scenario_validates_attempt_ownership() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    other_learner_id = uuid4()
    service = _build_service(factory)

    with pytest.raises(InvalidScenarioStateError):
        await service.start_scenario(
            learner_id=other_learner_id,
            scenario_id=world["scenario"].scenario_id,
            exercise_attempt_id=world["attempt"].attempt_id,
        )


async def test_start_scenario_is_idempotent() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    service = _build_service(factory)

    first = await service.start_scenario(
        learner_id=world["learner"].learner_id,
        scenario_id=world["scenario"].scenario_id,
        exercise_attempt_id=world["attempt"].attempt_id,
    )
    second = await service.start_scenario(
        learner_id=world["learner"].learner_id,
        scenario_id=world["scenario"].scenario_id,
        exercise_attempt_id=world["attempt"].attempt_id,
    )
    assert first.submission_id == second.submission_id
    assert len(factory.scenario_submissions.submissions) == 1


async def test_start_scenario_rolls_back_on_failure() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    factory.scenario_submissions.fail_on_create = True
    service = _build_service(factory)

    with pytest.raises(RuntimeError):
        await service.start_scenario(
            learner_id=world["learner"].learner_id,
            scenario_id=world["scenario"].scenario_id,
            exercise_attempt_id=world["attempt"].attempt_id,
        )
    assert factory.instances[-1].rolled_back is True
    assert factory.instances[-1].committed is False


# ---------------------------------------------------------------------------
# submit_decision
# ---------------------------------------------------------------------------


async def _started_submission(factory: FakeUnitOfWorkFactory, world: dict) -> ScenarioSubmission:
    service = _build_service(factory)
    return await service.start_scenario(
        learner_id=world["learner"].learner_id,
        scenario_id=world["scenario"].scenario_id,
        exercise_attempt_id=world["attempt"].attempt_id,
    )


async def test_submit_decision_validates_option_ownership() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    submission = await _started_submission(factory, world)
    service = _build_service(factory)

    with pytest.raises(InvalidScenarioStateError):
        await service.submit_decision(submission_id=submission.submission_id, selected_option_id=uuid4())


async def test_submit_decision_uses_rubric_decision_quality_for_mastery() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    submission = await _started_submission(factory, world)

    grading_policy = FakeGradingPolicy(score=0.73, quality=ScenarioDecisionQuality.GOOD)
    submitter = FakeGradedAnswerSubmitter()
    calculator = FakeScenarioCalculator(outcome_factory=_fake_outcome)
    service = _build_service(factory, calculator=calculator, grading_policy=grading_policy, submitter=submitter)

    result = await service.submit_decision(
        submission_id=submission.submission_id,
        selected_option_id=world["options"][0].option_id,
        confidence_level=ConfidenceLevel.MEDIUM,
    )

    assert result.submission.decision_quality_score == pytest.approx(0.73)
    assert result.submission.status == ScenarioSubmissionStatus.GRADED
    assert result.submission.reveal_status == ScenarioRevealStatus.AVAILABLE
    assert result.reveal_available is True

    # The externally graded learning flow was called with the decision-quality
    # score, never a realized market return.
    assert len(submitter.calls) == 1
    assert submitter.calls[0]["normalized_score"] == pytest.approx(0.73)
    assert submitter.calls[0]["attempt_id"] == world["attempt"].attempt_id

    # The realized future outcome was never touched during grading.
    assert calculator.outcome_calls == []


async def test_submit_decision_requires_started_submission() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    submission = await _started_submission(factory, world)
    service = _build_service(factory)
    await service.submit_decision(submission_id=submission.submission_id, selected_option_id=world["options"][0].option_id)

    with pytest.raises(InvalidScenarioStateError):
        await service.submit_decision(submission_id=submission.submission_id, selected_option_id=world["options"][0].option_id)


# ---------------------------------------------------------------------------
# reveal_outcome / get_reveal
# ---------------------------------------------------------------------------


async def test_reveal_is_blocked_before_grading() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    submission = await _started_submission(factory, world)
    service = _build_service(factory)

    with pytest.raises(InvalidScenarioStateError):
        await service.reveal_outcome(submission_id=submission.submission_id)


async def test_reveal_outcome_is_idempotent_and_persists_by_version() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    submission = await _started_submission(factory, world)

    submitter = FakeGradedAnswerSubmitter()
    calculator = FakeScenarioCalculator(outcome_factory=_fake_outcome)
    service = _build_service(factory, calculator=calculator, submitter=submitter)
    await service.submit_decision(
        submission_id=submission.submission_id, selected_option_id=world["options"][0].option_id
    )

    first_reveal = await service.reveal_outcome(submission_id=submission.submission_id)
    second_reveal = await service.reveal_outcome(submission_id=submission.submission_id)

    assert first_reveal.submission.status == ScenarioSubmissionStatus.REVEALED
    assert second_reveal.submission.status == ScenarioSubmissionStatus.REVEALED
    assert first_reveal.outcome.calculation_version == second_reveal.outcome.calculation_version

    # The outcome was computed and persisted exactly once (version-keyed reuse).
    assert len(calculator.outcome_calls) == 1
    assert factory.scenario_outcomes.upsert_calls == 1
    assert (world["scenario"].scenario_id, "scenario-outcome-v1") in factory.scenario_outcomes.outcomes

    # Mastery/grading was never re-invoked by reveal.
    assert len(submitter.calls) == 1


async def test_reveal_mastery_score_used_equals_decision_quality_score() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    submission = await _started_submission(factory, world)

    grading_policy = FakeGradingPolicy(score=0.81, quality=ScenarioDecisionQuality.STRONG)
    calculator = FakeScenarioCalculator(outcome_factory=_fake_outcome)
    service = _build_service(factory, calculator=calculator, grading_policy=grading_policy)
    result = await service.submit_decision(
        submission_id=submission.submission_id, selected_option_id=world["options"][0].option_id
    )

    reveal = await service.reveal_outcome(submission_id=submission.submission_id)
    assert reveal.mastery_score_used == pytest.approx(result.submission.decision_quality_score)
    assert reveal.mastery_score_used == pytest.approx(0.81)


async def test_get_reveal_requires_already_revealed_submission() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    submission = await _started_submission(factory, world)
    service = _build_service(factory)

    with pytest.raises(InvalidScenarioStateError):
        await service.get_reveal(submission_id=submission.submission_id)


# ---------------------------------------------------------------------------
# Adaptive eligibility
# ---------------------------------------------------------------------------


async def test_is_exercise_eligible_true_for_fully_configured_published_scenario() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    service = _build_service(factory)

    assert await service.is_exercise_eligible(world["exercise"].exercise_id) is True


async def test_is_exercise_eligible_false_when_scenario_not_published() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    factory.market_scenarios.scenarios[world["scenario"].scenario_id] = world["scenario"].model_copy(
        update={"status": MarketScenarioStatus.DRAFT}
    )
    service = _build_service(factory)

    assert await service.is_exercise_eligible(world["exercise"].exercise_id) is False


async def test_is_exercise_eligible_false_when_an_option_has_no_rubric() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _seed_world(factory)
    extra_option = ExerciseOption(exercise_id=world["exercise"].exercise_id, option_key="extra", content="x", position=99)
    factory.curriculum.options[world["exercise"].exercise_id].append(extra_option)
    service = _build_service(factory)

    assert await service.is_exercise_eligible(world["exercise"].exercise_id) is False
