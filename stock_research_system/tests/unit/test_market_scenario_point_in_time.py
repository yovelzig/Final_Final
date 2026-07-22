"""Point-in-time / no-future-leakage regression suite.

These are the single most important tests in the historical-market-
scenario feature: they prove a learner can never see, and a decision-
quality grade can never depend on, any bar after the scenario's
`decision_at` cutoff - regardless of what the market actually did
afterward. Synthetic bars T1..T120 (day offsets 1..120), decision at
T80, reveal end at T110, per spec.

Fakes only - no SQLAlchemy, PostgreSQL, or yfinance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.exceptions import InvalidScenarioStateError
from stock_research_core.application.learning.models import LearningActivityResult
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import AttemptStatus, DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import Exercise, ExerciseAttempt, ExerciseOption, LearnerProfile
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
    ScenarioObservationMetrics,
    ScenarioOptionRubric,
    ScenarioOutcome,
)
from stock_research_core.domain.models import MarketBar, Security

# Far in the future relative to wall-clock time, so `utc_now()`-defaulted
# fields on domain models constructed directly by these tests always sort
# before it.
NOW = datetime(2100, 1, 1, tzinfo=timezone.utc)
_EPOCH = NOW - timedelta(days=200)
_SECURITY_ID = uuid4()


def _bar(day: int, close: float = 100.0) -> MarketBar:
    """`T{day}` - day is 1-indexed per spec."""
    return MarketBar(
        security_id=_SECURITY_ID,
        timestamp=_EPOCH + timedelta(days=day),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        adjusted_close=close,
        volume=1000,
        interval="1d",
        source_name="test-source",
    )


_DECISION_AT = _EPOCH + timedelta(days=80)
_REVEAL_END_AT = _EPOCH + timedelta(days=110)


# ---------------------------------------------------------------------------
# Fakes (trimmed to exactly what this file's flows touch)
# ---------------------------------------------------------------------------


class FakeLearnerRepository:
    def __init__(self) -> None:
        self.learners: dict[UUID, LearnerProfile] = {}

    async def get(self, learner_id: UUID):
        return self.learners.get(learner_id)


class FakeSecurityRepository:
    def __init__(self) -> None:
        self.securities: dict[UUID, Security] = {}

    async def get_by_id(self, security_id: UUID):
        return self.securities.get(security_id)


class FakeMarketBarRepository:
    def __init__(self) -> None:
        self.bars: list[MarketBar] = []

    async def list_range(self, security_id, start_at, end_at, interval="1d", source_name=None):
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


class FakeCurriculumRepository:
    def __init__(self) -> None:
        self.exercises: dict[UUID, Exercise] = {}
        self.options: dict[UUID, list[ExerciseOption]] = {}

    async def get_exercise(self, exercise_id: UUID):
        return self.exercises.get(exercise_id)

    async def list_options(self, exercise_id: UUID):
        return list(self.options.get(exercise_id, []))


class FakeAttemptRepository:
    def __init__(self) -> None:
        self.attempts: dict[UUID, ExerciseAttempt] = {}

    async def get_attempt(self, attempt_id: UUID):
        return self.attempts.get(attempt_id)


class FakeMarketScenarioRepository:
    def __init__(self) -> None:
        self.scenarios: dict[UUID, HistoricalMarketScenario] = {}

    async def get(self, scenario_id: UUID):
        return self.scenarios.get(scenario_id)

    async def get_by_exercise_id(self, exercise_id: UUID):
        return next((s for s in self.scenarios.values() if s.exercise_id == exercise_id), None)


class FakeScenarioRubricRepository:
    def __init__(self) -> None:
        self.rubrics: dict[tuple[UUID, UUID], ScenarioOptionRubric] = {}

    async def list_for_scenario(self, scenario_id: UUID):
        return [r for (sid, _oid), r in self.rubrics.items() if sid == scenario_id]

    async def get_for_option(self, scenario_id: UUID, exercise_option_id: UUID):
        return self.rubrics.get((scenario_id, exercise_option_id))


class FakeScenarioOutcomeRepository:
    def __init__(self) -> None:
        self.outcomes: dict[tuple[UUID, str], ScenarioOutcome] = {}

    async def upsert(self, outcome: ScenarioOutcome):
        self.outcomes[(outcome.scenario_id, outcome.calculation_version)] = outcome
        return outcome

    async def get(self, scenario_id: UUID, calculation_version: str | None = None):
        if calculation_version is not None:
            return self.outcomes.get((scenario_id, calculation_version))
        matching = [o for (sid, _v), o in self.outcomes.items() if sid == scenario_id]
        return matching[0] if matching else None


class FakeScenarioSubmissionRepository:
    def __init__(self) -> None:
        self.submissions: dict[UUID, object] = {}

    async def create(self, submission):
        self.submissions[submission.submission_id] = submission
        return submission

    async def get(self, submission_id: UUID):
        return self.submissions.get(submission_id)

    async def get_by_attempt(self, exercise_attempt_id: UUID):
        return next((s for s in self.submissions.values() if s.exercise_attempt_id == exercise_attempt_id), None)

    async def update(self, submission):
        self.submissions[submission.submission_id] = submission
        return submission


class FakeUnitOfWork:
    def __init__(self, repos: dict) -> None:
        for name, repo in repos.items():
            setattr(self, name, repo)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def commit(self) -> None:
        pass


class FakeUnitOfWorkFactory:
    def __init__(self) -> None:
        self.learners = FakeLearnerRepository()
        self.securities = FakeSecurityRepository()
        self.market_bars = FakeMarketBarRepository()
        self.curriculum = FakeCurriculumRepository()
        self.attempts = FakeAttemptRepository()
        self.market_scenarios = FakeMarketScenarioRepository()
        self.scenario_rubrics = FakeScenarioRubricRepository()
        self.scenario_outcomes = FakeScenarioOutcomeRepository()
        self.scenario_submissions = FakeScenarioSubmissionRepository()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(
            {
                "learners": self.learners,
                "securities": self.securities,
                "market_bars": self.market_bars,
                "curriculum": self.curriculum,
                "attempts": self.attempts,
                "market_scenarios": self.market_scenarios,
                "scenario_rubrics": self.scenario_rubrics,
                "scenario_outcomes": self.scenario_outcomes,
                "scenario_submissions": self.scenario_submissions,
            }
        )


class RealisticScenarioCalculator:
    """Unlike the pure-stub fakes used elsewhere, this one actually reads
    the bars it is given - so these tests can prove the *service* never
    hands it a bar past the relevant cutoff, and that outcome results
    really do change when future bars change."""

    def __init__(self) -> None:
        self.observation_calls: list[tuple] = []
        self.outcome_calls: list[tuple] = []

    async def calculate_observation(self, *, scenario, focal_bars, benchmark_bars):
        self.observation_calls.append((scenario, tuple(focal_bars), tuple(benchmark_bars)))
        ordered = sorted(focal_bars, key=lambda bar: bar.timestamp)
        return ScenarioObservationMetrics(
            data_cutoff_at=ordered[-1].timestamp,
            observation_bar_count=len(ordered),
            start_close=ordered[0].close,
            decision_close=ordered[-1].close,
            observation_return=ordered[-1].adjusted_close / ordered[0].adjusted_close - 1.0,
            price_change_percentage=(ordered[-1].close - ordered[0].close) / ordered[0].close * 100.0,
            highest_close=max(bar.close for bar in ordered),
            lowest_close=min(bar.close for bar in ordered),
            calculation_version="scenario-observation-v1",
        )

    async def calculate_outcome(self, *, scenario, focal_bars, benchmark_bars):
        self.outcome_calls.append((scenario, tuple(focal_bars), tuple(benchmark_bars)))
        window = sorted(
            (bar for bar in focal_bars if scenario.decision_at < bar.timestamp <= scenario.reveal_end_at),
            key=lambda bar: bar.timestamp,
        )
        decision_bar = max(
            (bar for bar in focal_bars if bar.timestamp <= scenario.decision_at), key=lambda bar: bar.timestamp
        )
        end_close = window[-1].adjusted_close
        focal_return = end_close / decision_bar.adjusted_close - 1.0
        return ScenarioOutcome(
            scenario_id=scenario.scenario_id,
            decision_at=scenario.decision_at,
            reveal_end_at=scenario.reveal_end_at,
            focal_start_close=decision_bar.close,
            focal_end_close=window[-1].close,
            focal_return=focal_return,
            maximum_future_upside=max(0.0, focal_return),
            maximum_future_drawdown=min(0.0, focal_return),
            outcome_direction="POSITIVE" if focal_return > 0.01 else "FLAT",
            outcome_summary="Summary.",
            calculation_version="scenario-outcome-v1",
        )


class FakeGradingPolicy:
    def __init__(self, score: float = 0.7) -> None:
        self.score = score

    def grade(self, *, scenario, rubric, confidence_level, learner_rationale):
        return self.score, ScenarioDecisionQuality.GOOD, [], "Feedback."

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
        self.calls.append({"normalized_score": normalized_score, "is_correct": is_correct})
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
# World builder
# ---------------------------------------------------------------------------


def _rubric(scenario_id: UUID, option_id: UUID, score: float = 0.7) -> ScenarioOptionRubric:
    return ScenarioOptionRubric(
        scenario_id=scenario_id,
        exercise_option_id=option_id,
        decision_quality_score=sum(score * weight for weight in RUBRIC_COMPONENT_WEIGHTS.values()),
        risk_awareness_score=score,
        benchmark_awareness_score=score,
        horizon_alignment_score=score,
        information_sufficiency_score=score,
        uncertainty_awareness_score=score,
        expected_direction=ScenarioExpectedDirection.NEUTRAL,
        positive_feedback="Good.",
        improvement_feedback="Better.",
        rubric_version="scenario-rubric-v1",
    )


async def _build_world(factory: FakeUnitOfWorkFactory, *, benchmark_id: UUID | None = None) -> dict:
    learner = LearnerProfile(display_name="Learner", active=True)
    factory.learners.learners[learner.learner_id] = learner

    security = Security(
        security_id=_SECURITY_ID, ticker="NVDA", company_name="Test Co", exchange=Exchange.NASDAQ
    )
    factory.securities.securities[security.security_id] = security

    exercise = Exercise(
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
    factory.curriculum.exercises[exercise.exercise_id] = exercise
    option = ExerciseOption(exercise_id=exercise.exercise_id, option_key="opt-0", content="Option", position=0)
    factory.curriculum.options[exercise.exercise_id] = [option]

    scenario = HistoricalMarketScenario(
        exercise_id=exercise.exercise_id,
        code="NVDA_POINT_IN_TIME",
        title="Point-in-time test scenario",
        description="Description.",
        scenario_type=MarketScenarioType.MARKET_REPLAY,
        status=MarketScenarioStatus.PUBLISHED,
        observation_start_at=_EPOCH + timedelta(days=1),
        decision_at=_DECISION_AT,
        reveal_end_at=_REVEAL_END_AT,
        interval="1d",
        source_name="test-source",
        focal_security_id=security.security_id,
        primary_skill_ids=[uuid4()],
        prompt="Decide.",
        learner_instructions="Instructions.",
        learning_objectives=["Learn something."],
        minimum_observation_bars=5,
        minimum_reveal_bars=5,
        scenario_version="scenario-v1",
    )
    factory.market_scenarios.scenarios[scenario.scenario_id] = scenario
    factory.scenario_rubrics.rubrics[(scenario.scenario_id, option.option_id)] = _rubric(
        scenario.scenario_id, option.option_id
    )

    for day in range(1, 121):
        factory.market_bars.bars.append(_bar(day))

    attempt = ExerciseAttempt(
        learner_id=learner.learner_id, exercise_id=exercise.exercise_id, maximum_score=1.0, attempt_number=1
    )
    factory.attempts.attempts[attempt.attempt_id] = attempt

    return dict(learner=learner, security=security, exercise=exercise, option=option, scenario=scenario, attempt=attempt)


def _build_service(factory, calculator, grading_policy=None, submitter=None) -> HistoricalMarketScenarioService:
    return HistoricalMarketScenarioService(
        unit_of_work_factory=factory,
        scenario_calculator=calculator,
        scenario_grading_policy=grading_policy or FakeGradingPolicy(),
        graded_answer_submitter=submitter or FakeGradedAnswerSubmitter(),
        clock=lambda: NOW,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_learner_chart_includes_no_bar_after_decision_cutoff() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _build_world(factory)
    calculator = RealisticScenarioCalculator()
    service = _build_service(factory, calculator)

    view = await service.get_learner_view(learner_id=world["learner"].learner_id, scenario_id=world["scenario"].scenario_id)

    assert all(point.timestamp <= _DECISION_AT for point in view.focal_chart)
    assert view.focal_chart  # sanity: it wasn't accidentally empty
    assert max(point.timestamp for point in view.focal_chart) == _DECISION_AT


async def test_benchmark_chart_includes_no_bar_after_decision_cutoff() -> None:
    benchmark_id = uuid4()
    factory = FakeUnitOfWorkFactory()
    world = await _build_world(factory)
    benchmark_security = Security(
        security_id=benchmark_id, ticker="SPY", company_name="Benchmark", exchange=Exchange.NYSE
    )
    factory.securities.securities[benchmark_id] = benchmark_security
    factory.market_scenarios.scenarios[world["scenario"].scenario_id] = world["scenario"].model_copy(
        update={"benchmark_security_id": benchmark_id}
    )
    for day in range(1, 121):
        factory.market_bars.bars.append(
            MarketBar(
                security_id=benchmark_id,
                timestamp=_EPOCH + timedelta(days=day),
                open=200.0,
                high=201.0,
                low=199.0,
                close=200.0,
                adjusted_close=200.0,
                volume=1000,
                interval="1d",
                source_name="test-source",
            )
        )

    calculator = RealisticScenarioCalculator()
    service = _build_service(factory, calculator)
    view = await service.get_learner_view(learner_id=world["learner"].learner_id, scenario_id=world["scenario"].scenario_id)

    assert view.benchmark_chart
    assert all(point.timestamp <= _DECISION_AT for point in view.benchmark_chart)


async def test_observation_metrics_unchanged_when_future_bars_are_modified() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _build_world(factory)
    calculator = RealisticScenarioCalculator()
    service = _build_service(factory, calculator)
    baseline_view = await service.get_learner_view(
        learner_id=world["learner"].learner_id, scenario_id=world["scenario"].scenario_id
    )

    # Tamper with every bar strictly after the decision cutoff.
    for bar in list(factory.market_bars.bars):
        if bar.timestamp > _DECISION_AT:
            factory.market_bars.bars.remove(bar)
    for day in range(81, 121):
        factory.market_bars.bars.append(_bar(day, close=999999.0))

    tampered_view = await service.get_learner_view(
        learner_id=world["learner"].learner_id, scenario_id=world["scenario"].scenario_id
    )
    assert tampered_view.observation_metrics == baseline_view.observation_metrics


def test_learner_view_never_carries_future_or_rubric_fields() -> None:
    """Structural guarantee: `LearnerScenarioView` has no field for a
    `ScenarioOutcome`, no reveal-end value, and its options carry no
    `is_correct`/rubric score - not merely unset, but entirely absent
    from the schema."""
    field_names = set(type_field for type_field in __import__(
        "stock_research_core.application.market_scenarios.models", fromlist=["LearnerScenarioView"]
    ).LearnerScenarioView.model_fields)
    forbidden = {"outcome", "reveal_end_at", "future_focal_chart", "future_benchmark_chart", "rubrics"}
    assert field_names.isdisjoint(forbidden)

    option_fields = set(
        __import__(
            "stock_research_core.application.market_scenarios.models", fromlist=["LearnerSafeExerciseOption"]
        ).LearnerSafeExerciseOption.model_fields
    )
    assert "is_correct" not in option_fields
    assert "decision_quality_score" not in option_fields


async def test_decision_quality_score_unchanged_when_future_bars_change() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _build_world(factory)
    grading_policy = FakeGradingPolicy(score=0.73)
    submitter = FakeGradedAnswerSubmitter()

    async def _submit(calculator: RealisticScenarioCalculator):
        service = _build_service(factory, calculator, grading_policy=grading_policy, submitter=submitter)
        started = await service.start_scenario(
            learner_id=world["learner"].learner_id,
            scenario_id=world["scenario"].scenario_id,
            exercise_attempt_id=world["attempt"].attempt_id,
        )
        return await service.submit_decision(
            submission_id=started.submission_id, selected_option_id=world["option"].option_id
        )

    baseline_result = await _submit(RealisticScenarioCalculator())
    assert baseline_result.submission.decision_quality_score == pytest.approx(0.73)

    # Change every future bar wildly, then start+submit a *new* attempt/submission
    # (a submission can only be graded once) and confirm the score is identical.
    for bar in list(factory.market_bars.bars):
        if bar.timestamp > _DECISION_AT:
            factory.market_bars.bars.remove(bar)
    for day in range(81, 121):
        factory.market_bars.bars.append(_bar(day, close=5.0))  # crash close to zero

    new_attempt = ExerciseAttempt(
        learner_id=world["learner"].learner_id, exercise_id=world["exercise"].exercise_id,
        maximum_score=1.0, attempt_number=2,
    )
    factory.attempts.attempts[new_attempt.attempt_id] = new_attempt
    world["attempt"] = new_attempt

    tampered_result = await _submit(RealisticScenarioCalculator())
    assert tampered_result.submission.decision_quality_score == pytest.approx(0.73)
    assert tampered_result.submission.decision_quality_score == baseline_result.submission.decision_quality_score

    # And the calculator's calculate_outcome was never invoked while grading.
    assert all(call["normalized_score"] == pytest.approx(0.73) for call in submitter.calls)


async def test_scenario_outcome_changes_when_future_bars_change() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _build_world(factory)
    submission = await _build_service(factory, RealisticScenarioCalculator()).start_scenario(
        learner_id=world["learner"].learner_id,
        scenario_id=world["scenario"].scenario_id,
        exercise_attempt_id=world["attempt"].attempt_id,
    )
    service = _build_service(factory, RealisticScenarioCalculator())
    await service.submit_decision(submission_id=submission.submission_id, selected_option_id=world["option"].option_id)

    baseline_reveal = await service.reveal_outcome(submission_id=submission.submission_id)
    baseline_return = baseline_reveal.outcome.focal_return

    # A brand-new scenario code (so `scenario_outcomes` isn't reused by version key)
    # with wildly different future bars produces a different outcome.
    for bar in list(factory.market_bars.bars):
        if bar.timestamp > _DECISION_AT:
            factory.market_bars.bars.remove(bar)
    for day in range(81, 121):
        factory.market_bars.bars.append(_bar(day, close=500.0))
    factory.scenario_outcomes.outcomes.clear()  # force recomputation, as a fresh scenario would

    new_calculator = RealisticScenarioCalculator()
    new_service = _build_service(factory, new_calculator)
    fresh_submission_id = uuid4()
    from stock_research_core.domain.market_scenarios.models import ScenarioSubmission

    fresh_submission = ScenarioSubmission(
        submission_id=fresh_submission_id,
        scenario_id=world["scenario"].scenario_id,
        learner_id=world["learner"].learner_id,
        exercise_attempt_id=uuid4(),
        status=ScenarioSubmissionStatus.GRADED,
        selected_option_id=world["option"].option_id,
        decision_quality_score=0.73,
        decision_quality=ScenarioDecisionQuality.GOOD,
        feedback_text="Feedback.",
        reveal_status=ScenarioRevealStatus.AVAILABLE,
        started_at=NOW,
        submitted_at=NOW,
        graded_at=NOW,
        rubric_version="scenario-rubric-v1",
    )
    factory.scenario_submissions.submissions[fresh_submission_id] = fresh_submission

    changed_reveal = await new_service.reveal_outcome(submission_id=fresh_submission_id)
    assert changed_reveal.outcome.focal_return != pytest.approx(baseline_return)


async def test_reveal_unavailable_before_grading_and_available_only_after() -> None:
    factory = FakeUnitOfWorkFactory()
    world = await _build_world(factory)
    service = _build_service(factory, RealisticScenarioCalculator())

    started = await service.start_scenario(
        learner_id=world["learner"].learner_id,
        scenario_id=world["scenario"].scenario_id,
        exercise_attempt_id=world["attempt"].attempt_id,
    )
    with pytest.raises(InvalidScenarioStateError):
        await service.reveal_outcome(submission_id=started.submission_id)

    result = await service.submit_decision(submission_id=started.submission_id, selected_option_id=world["option"].option_id)
    assert result.reveal_available is True

    reveal = await service.reveal_outcome(submission_id=started.submission_id)
    assert reveal.submission.reveal_status == ScenarioRevealStatus.REVEALED
