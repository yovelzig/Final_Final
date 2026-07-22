"""Unit tests for `RuleBasedScenarioGradingPolicy`.

Deterministic, offline: no database, no network, no outcome ever read
by `grade()`.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import InvalidScenarioStateError
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.domain.learning.enums import ConfidenceLevel
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioType,
    ScenarioDecisionQuality,
    ScenarioExpectedDirection,
    ScenarioFeedbackCode,
    ScenarioOutcomeDirection,
    ScenarioSubmissionStatus,
)
from stock_research_core.domain.market_scenarios.models import (
    RUBRIC_COMPONENT_WEIGHTS,
    HistoricalMarketScenario,
    ScenarioOptionRubric,
    ScenarioOutcome,
    ScenarioSubmission,
)

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _scenario() -> HistoricalMarketScenario:
    return HistoricalMarketScenario(
        exercise_id=uuid4(),
        code="TEST_SCENARIO",
        title="t",
        description="d",
        scenario_type=MarketScenarioType.MARKET_REPLAY,
        observation_start_at=NOW - timedelta(days=90),
        decision_at=NOW - timedelta(days=30),
        reveal_end_at=NOW,
        interval="1d",
        source_name="test-source",
        focal_security_id=uuid4(),
        primary_skill_ids=[uuid4()],
        prompt="p",
        learner_instructions="li",
        learning_objectives=["o"],
        minimum_observation_bars=40,
        minimum_reveal_bars=20,
        scenario_version="scenario-v1",
    )


def _rubric(
    *,
    risk: float = 0.6,
    benchmark: float = 0.6,
    horizon: float = 0.6,
    information: float = 0.6,
    uncertainty: float = 0.6,
    expected_direction: ScenarioExpectedDirection = ScenarioExpectedDirection.NEUTRAL,
    feedback_codes: list[ScenarioFeedbackCode] | None = None,
) -> ScenarioOptionRubric:
    components = {
        "risk_awareness_score": risk,
        "benchmark_awareness_score": benchmark,
        "horizon_alignment_score": horizon,
        "information_sufficiency_score": information,
        "uncertainty_awareness_score": uncertainty,
    }
    decision_quality_score = sum(components[name] * weight for name, weight in RUBRIC_COMPONENT_WEIGHTS.items())
    return ScenarioOptionRubric(
        scenario_id=uuid4(),
        exercise_option_id=uuid4(),
        decision_quality_score=decision_quality_score,
        risk_awareness_score=risk,
        benchmark_awareness_score=benchmark,
        horizon_alignment_score=horizon,
        information_sufficiency_score=information,
        uncertainty_awareness_score=uncertainty,
        expected_direction=expected_direction,
        feedback_codes=feedback_codes or [],
        positive_feedback="Good reasoning here.",
        improvement_feedback="Consider this next time.",
        rubric_version="scenario-rubric-v1",
    )


def _outcome(direction: ScenarioOutcomeDirection) -> ScenarioOutcome:
    return ScenarioOutcome(
        scenario_id=uuid4(),
        decision_at=NOW - timedelta(days=30),
        reveal_end_at=NOW,
        focal_start_close=100.0,
        focal_end_close=110.0,
        focal_return=0.10,
        maximum_future_upside=0.15,
        maximum_future_drawdown=-0.05,
        outcome_direction=direction,
        outcome_summary="The security moved.",
        calculation_version="scenario-outcome-v1",
    )


def _submission(
    *, decision_quality_score: float, outcome_alignment_score: float, feedback_text: str = "Feedback text."
) -> ScenarioSubmission:
    return ScenarioSubmission(
        scenario_id=uuid4(),
        learner_id=uuid4(),
        exercise_attempt_id=uuid4(),
        status=ScenarioSubmissionStatus.GRADED,
        selected_option_id=uuid4(),
        decision_quality_score=decision_quality_score,
        outcome_alignment_score=outcome_alignment_score,
        decision_quality=ScenarioDecisionQuality.GOOD,
        feedback_text=feedback_text,
        started_at=NOW,
        submitted_at=NOW,
        graded_at=NOW,
        rubric_version="scenario-rubric-v1",
    )


@pytest.fixture
def policy() -> RuleBasedScenarioGradingPolicy:
    return RuleBasedScenarioGradingPolicy()


# ---------------------------------------------------------------------------
# grade()
# ---------------------------------------------------------------------------


def test_grade_matches_rubric_weighted_score_without_confidence(policy: RuleBasedScenarioGradingPolicy) -> None:
    rubric = _rubric(risk=0.6, benchmark=0.6, horizon=0.6, information=0.6, uncertainty=0.6)
    score, quality, codes, feedback = policy.grade(
        scenario=_scenario(), rubric=rubric, confidence_level=None, learner_rationale=None
    )
    assert score == pytest.approx(rubric.decision_quality_score)
    assert quality == ScenarioDecisionQuality.GOOD
    assert codes == list(rubric.feedback_codes)
    assert feedback


def test_grade_never_reads_a_scenario_outcome_argument() -> None:
    """`grade()` structurally cannot depend on the realized outcome - it
    has no `outcome`/`ScenarioOutcome` parameter at all."""
    signature = inspect.signature(RuleBasedScenarioGradingPolicy.grade)
    assert "outcome" not in signature.parameters
    for parameter in signature.parameters.values():
        assert "ScenarioOutcome" not in str(parameter.annotation)


def test_grade_applies_overconfident_penalty_for_low_quality_high_confidence(
    policy: RuleBasedScenarioGradingPolicy,
) -> None:
    rubric = _rubric(risk=0.2, benchmark=0.2, horizon=0.2, information=0.2, uncertainty=0.2)
    assert rubric.decision_quality_score < 0.50
    score, quality, codes, _feedback = policy.grade(
        scenario=_scenario(), rubric=rubric, confidence_level=ConfidenceLevel.HIGH, learner_rationale=None
    )
    assert score == pytest.approx(max(0.0, rubric.decision_quality_score - 0.10))
    assert ScenarioFeedbackCode.OVERCONFIDENT_DECISION in codes


def test_grade_does_not_penalize_strong_decision_with_low_confidence(
    policy: RuleBasedScenarioGradingPolicy,
) -> None:
    rubric = _rubric(risk=0.9, benchmark=0.9, horizon=0.9, information=0.9, uncertainty=0.9)
    assert rubric.decision_quality_score >= 0.80
    score, quality, codes, _feedback = policy.grade(
        scenario=_scenario(), rubric=rubric, confidence_level=ConfidenceLevel.LOW, learner_rationale=None
    )
    assert score == pytest.approx(rubric.decision_quality_score)
    assert ScenarioFeedbackCode.RECOGNIZED_UNCERTAINTY in codes
    assert quality == ScenarioDecisionQuality.STRONG


def test_grade_clamps_score_to_zero(policy: RuleBasedScenarioGradingPolicy) -> None:
    rubric = _rubric(risk=0.02, benchmark=0.02, horizon=0.02, information=0.02, uncertainty=0.02)
    score, _quality, _codes, _feedback = policy.grade(
        scenario=_scenario(), rubric=rubric, confidence_level=ConfidenceLevel.VERY_HIGH, learner_rationale=None
    )
    assert score == pytest.approx(0.0)
    assert score >= 0.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.10, ScenarioDecisionQuality.POOR),
        (0.29, ScenarioDecisionQuality.POOR),
        (0.30, ScenarioDecisionQuality.DEVELOPING),
        (0.59, ScenarioDecisionQuality.DEVELOPING),
        (0.60, ScenarioDecisionQuality.GOOD),
        (0.84, ScenarioDecisionQuality.GOOD),
        (0.85, ScenarioDecisionQuality.STRONG),
        (1.0, ScenarioDecisionQuality.STRONG),
    ],
)
def test_grade_classification_thresholds(
    policy: RuleBasedScenarioGradingPolicy, score: float, expected: ScenarioDecisionQuality
) -> None:
    assert policy._classify(score) == expected  # noqa: SLF001 - deterministic thresholds under test


def test_grade_is_deterministic(policy: RuleBasedScenarioGradingPolicy) -> None:
    rubric = _rubric()
    first = policy.grade(
        scenario=_scenario(), rubric=rubric, confidence_level=ConfidenceLevel.HIGH, learner_rationale=None
    )
    second = policy.grade(
        scenario=_scenario(), rubric=rubric, confidence_level=ConfidenceLevel.HIGH, learner_rationale=None
    )
    assert first == second


def test_grade_feedback_is_non_empty_english_text(policy: RuleBasedScenarioGradingPolicy) -> None:
    rubric = _rubric()
    _score, _quality, _codes, feedback = policy.grade(
        scenario=_scenario(), rubric=rubric, confidence_level=None, learner_rationale=None
    )
    assert feedback.strip()
    assert feedback.isascii()


# ---------------------------------------------------------------------------
# calculate_outcome_alignment()
# ---------------------------------------------------------------------------


def test_outcome_alignment_directional_match(policy: RuleBasedScenarioGradingPolicy) -> None:
    rubric = _rubric(expected_direction=ScenarioExpectedDirection.POSITIVE)
    outcome = _outcome(ScenarioOutcomeDirection.POSITIVE)
    assert policy.calculate_outcome_alignment(rubric=rubric, outcome=outcome) == pytest.approx(1.0)


def test_outcome_alignment_directional_mismatch(policy: RuleBasedScenarioGradingPolicy) -> None:
    rubric = _rubric(expected_direction=ScenarioExpectedDirection.POSITIVE)
    outcome = _outcome(ScenarioOutcomeDirection.NEGATIVE)
    assert policy.calculate_outcome_alignment(rubric=rubric, outcome=outcome) == pytest.approx(0.0)


def test_outcome_alignment_neutral_decision(policy: RuleBasedScenarioGradingPolicy) -> None:
    rubric = _rubric(expected_direction=ScenarioExpectedDirection.NEUTRAL)
    outcome = _outcome(ScenarioOutcomeDirection.POSITIVE)
    assert policy.calculate_outcome_alignment(rubric=rubric, outcome=outcome) == pytest.approx(0.5)


def test_outcome_alignment_information_required_decision(policy: RuleBasedScenarioGradingPolicy) -> None:
    rubric = _rubric(expected_direction=ScenarioExpectedDirection.INFORMATION_REQUIRED)
    outcome = _outcome(ScenarioOutcomeDirection.FLAT)
    assert policy.calculate_outcome_alignment(rubric=rubric, outcome=outcome) == pytest.approx(0.5)


def test_outcome_alignment_directional_decision_facing_flat_outcome(
    policy: RuleBasedScenarioGradingPolicy,
) -> None:
    rubric = _rubric(expected_direction=ScenarioExpectedDirection.NEGATIVE)
    outcome = _outcome(ScenarioOutcomeDirection.FLAT)
    assert policy.calculate_outcome_alignment(rubric=rubric, outcome=outcome) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# build_reveal_feedback()
# ---------------------------------------------------------------------------


def test_reveal_feedback_good_process_good_outcome(policy: RuleBasedScenarioGradingPolicy) -> None:
    submission = _submission(decision_quality_score=0.80, outcome_alignment_score=1.0)
    rubric = _rubric()
    outcome = _outcome(ScenarioOutcomeDirection.POSITIVE)
    _decision, _outcome_text, summary = policy.build_reveal_feedback(
        submission=submission, rubric=rubric, outcome=outcome
    )
    assert "good" in summary.lower()
    assert "keep using" in summary.lower()


def test_reveal_feedback_good_process_bad_outcome_includes_bias_warning(
    policy: RuleBasedScenarioGradingPolicy,
) -> None:
    submission = _submission(decision_quality_score=0.80, outcome_alignment_score=0.0)
    rubric = _rubric()
    outcome = _outcome(ScenarioOutcomeDirection.NEGATIVE)
    _decision, _outcome_text, summary = policy.build_reveal_feedback(
        submission=submission, rubric=rubric, outcome=outcome
    )
    assert "unlucky result" in summary.lower()
    assert "different things" in summary.lower()  # outcome-bias warning text


def test_reveal_feedback_bad_process_good_outcome_includes_bias_warning(
    policy: RuleBasedScenarioGradingPolicy,
) -> None:
    submission = _submission(decision_quality_score=0.20, outcome_alignment_score=1.0)
    rubric = _rubric()
    outcome = _outcome(ScenarioOutcomeDirection.POSITIVE)
    _decision, _outcome_text, summary = policy.build_reveal_feedback(
        submission=submission, rubric=rubric, outcome=outcome
    )
    assert "lucky result" in summary.lower()
    assert "different things" in summary.lower()


def test_reveal_feedback_bad_process_bad_outcome(policy: RuleBasedScenarioGradingPolicy) -> None:
    submission = _submission(decision_quality_score=0.20, outcome_alignment_score=0.0)
    rubric = _rubric()
    outcome = _outcome(ScenarioOutcomeDirection.NEGATIVE)
    _decision, _outcome_text, summary = policy.build_reveal_feedback(
        submission=submission, rubric=rubric, outcome=outcome
    )
    assert "weak" in summary.lower()


def test_reveal_feedback_requires_a_graded_submission_with_alignment(
    policy: RuleBasedScenarioGradingPolicy,
) -> None:
    submission = _submission(decision_quality_score=0.80, outcome_alignment_score=1.0).model_copy(
        update={"outcome_alignment_score": None}
    )
    with pytest.raises(InvalidScenarioStateError):
        policy.build_reveal_feedback(submission=submission, rubric=_rubric(), outcome=_outcome(ScenarioOutcomeDirection.POSITIVE))
