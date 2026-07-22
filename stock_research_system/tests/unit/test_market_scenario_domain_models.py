"""Unit tests for the historical-market-scenario domain models.

Pure Pydantic model tests: no SQLAlchemy, no fakes, no I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.learning.enums import ConfidenceLevel
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioType,
    ScenarioDecisionQuality,
    ScenarioExpectedDirection,
    ScenarioFeedbackCode,
    ScenarioGenerationRunStatus,
    ScenarioOutcomeDirection,
    ScenarioRevealStatus,
    ScenarioSubmissionStatus,
)
from stock_research_core.domain.market_scenarios.models import (
    RUBRIC_COMPONENT_WEIGHTS,
    HistoricalMarketScenario,
    ScenarioGenerationRun,
    ScenarioObservationMetrics,
    ScenarioOptionRubric,
    ScenarioOutcome,
    ScenarioSubmission,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _scenario_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        exercise_id=uuid4(),
        code="NVDA_2023_RALLY",
        title="NVDA 2023 rally",
        description="A historical decision scenario.",
        scenario_type=MarketScenarioType.MARKET_REPLAY,
        observation_start_at=NOW - timedelta(days=90),
        decision_at=NOW - timedelta(days=30),
        reveal_end_at=NOW,
        interval="1d",
        source_name="yfinance",
        focal_security_id=uuid4(),
        primary_skill_ids=[uuid4()],
        prompt="What would you do?",
        learner_instructions="Review the chart and pick a decision.",
        learning_objectives=["Understand risk-adjusted decision making"],
        minimum_observation_bars=40,
        minimum_reveal_bars=20,
        scenario_version="scenario-v1",
    )
    kwargs.update(overrides)
    return kwargs


def _rubric_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        scenario_id=uuid4(),
        exercise_option_id=uuid4(),
        risk_awareness_score=0.6,
        benchmark_awareness_score=0.6,
        horizon_alignment_score=0.6,
        information_sufficiency_score=0.6,
        uncertainty_awareness_score=0.6,
        expected_direction=ScenarioExpectedDirection.NEUTRAL,
        positive_feedback="Good reasoning.",
        improvement_feedback="Consider the benchmark next time.",
        rubric_version="scenario-rubric-v1",
    )
    kwargs.update(overrides)
    kwargs.setdefault(
        "decision_quality_score",
        sum(kwargs[name] * weight for name, weight in RUBRIC_COMPONENT_WEIGHTS.items()),
    )
    return kwargs


# ---------------------------------------------------------------------------
# HistoricalMarketScenario
# ---------------------------------------------------------------------------


def test_scenario_accepts_valid_fields() -> None:
    scenario = HistoricalMarketScenario(**_scenario_kwargs())
    assert scenario.code == "NVDA_2023_RALLY"


def test_scenario_rejects_bad_timestamp_ordering() -> None:
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(
            **_scenario_kwargs(observation_start_at=NOW, decision_at=NOW - timedelta(days=1))
        )


def test_scenario_requires_at_least_one_primary_skill() -> None:
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(**_scenario_kwargs(primary_skill_ids=[]))


def test_scenario_rejects_duplicate_primary_skills() -> None:
    skill_id = uuid4()
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(**_scenario_kwargs(primary_skill_ids=[skill_id, skill_id]))


def test_scenario_rejects_primary_secondary_skill_overlap() -> None:
    skill_id = uuid4()
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(
            **_scenario_kwargs(primary_skill_ids=[skill_id], secondary_skill_ids=[skill_id])
        )


def test_scenario_rejects_minimum_bars_below_floor() -> None:
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(**_scenario_kwargs(minimum_observation_bars=4))
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(**_scenario_kwargs(minimum_reveal_bars=0))


def test_scenario_requires_scenario_version() -> None:
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(**_scenario_kwargs(scenario_version=""))


def test_scenario_rejects_naive_datetimes() -> None:
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(
            **_scenario_kwargs(decision_at=datetime(2025, 12, 1))  # noqa: DTZ001 - deliberate naive dt
        )


def test_scenario_rejects_matching_focal_and_benchmark_security() -> None:
    security_id = uuid4()
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(
            **_scenario_kwargs(focal_security_id=security_id, benchmark_security_id=security_id)
        )


def test_scenario_rejects_invalid_code_format() -> None:
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(**_scenario_kwargs(code="nvda-2023"))


def test_scenario_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HistoricalMarketScenario(**_scenario_kwargs(), unknown_field="x")


# ---------------------------------------------------------------------------
# ScenarioOptionRubric
# ---------------------------------------------------------------------------


def test_rubric_accepts_valid_weighted_total() -> None:
    rubric = ScenarioOptionRubric(**_rubric_kwargs())
    assert 0 <= rubric.decision_quality_score <= 1


def test_rubric_rejects_score_outside_zero_one() -> None:
    with pytest.raises(ValidationError):
        ScenarioOptionRubric(**_rubric_kwargs(risk_awareness_score=1.5))


def test_rubric_rejects_decision_quality_score_inconsistent_with_weights() -> None:
    with pytest.raises(ValidationError):
        ScenarioOptionRubric(**_rubric_kwargs(decision_quality_score=0.999999))


def test_rubric_rejects_duplicate_feedback_codes() -> None:
    with pytest.raises(ValidationError):
        ScenarioOptionRubric(
            **_rubric_kwargs(
                feedback_codes=[
                    ScenarioFeedbackCode.IDENTIFIED_RISK,
                    ScenarioFeedbackCode.IDENTIFIED_RISK,
                ]
            )
        )


def test_rubric_component_weights_sum_to_one() -> None:
    assert abs(sum(RUBRIC_COMPONENT_WEIGHTS.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# ScenarioObservationMetrics
# ---------------------------------------------------------------------------


def test_observation_metrics_accepts_valid_fields() -> None:
    metrics = ScenarioObservationMetrics(
        data_cutoff_at=NOW,
        observation_bar_count=40,
        start_close=100.0,
        decision_close=110.0,
        observation_return=0.10,
        annualized_volatility=0.2,
        maximum_drawdown=-0.05,
        average_daily_volume=1_000_000.0,
        price_change_percentage=10.0,
        highest_close=112.0,
        lowest_close=98.0,
        calculation_version="scenario-observation-v1",
    )
    assert metrics.observation_bar_count == 40


def test_observation_metrics_rejects_positive_maximum_drawdown() -> None:
    with pytest.raises(ValidationError):
        ScenarioObservationMetrics(
            data_cutoff_at=NOW,
            observation_bar_count=40,
            start_close=100.0,
            decision_close=110.0,
            observation_return=0.10,
            maximum_drawdown=0.05,
            price_change_percentage=10.0,
            highest_close=112.0,
            lowest_close=98.0,
            calculation_version="scenario-observation-v1",
        )


def test_observation_metrics_rejects_highest_below_lowest() -> None:
    with pytest.raises(ValidationError):
        ScenarioObservationMetrics(
            data_cutoff_at=NOW,
            observation_bar_count=40,
            start_close=100.0,
            decision_close=110.0,
            observation_return=0.10,
            price_change_percentage=10.0,
            highest_close=90.0,
            lowest_close=98.0,
            calculation_version="scenario-observation-v1",
        )


# ---------------------------------------------------------------------------
# ScenarioOutcome
# ---------------------------------------------------------------------------


def _outcome_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        scenario_id=uuid4(),
        decision_at=NOW,
        reveal_end_at=NOW + timedelta(days=30),
        focal_start_close=100.0,
        focal_end_close=110.0,
        focal_return=0.10,
        maximum_future_upside=0.15,
        maximum_future_drawdown=-0.05,
        outcome_direction=ScenarioOutcomeDirection.POSITIVE,
        outcome_summary="The focal security rose 10% over the reveal window.",
        calculation_version="scenario-outcome-v1",
    )
    kwargs.update(overrides)
    return kwargs


def test_outcome_accepts_valid_fields() -> None:
    outcome = ScenarioOutcome(**_outcome_kwargs())
    assert outcome.outcome_direction == ScenarioOutcomeDirection.POSITIVE


def test_outcome_rejects_reveal_end_before_decision() -> None:
    with pytest.raises(ValidationError):
        ScenarioOutcome(**_outcome_kwargs(reveal_end_at=NOW - timedelta(days=1)))


def test_outcome_rejects_negative_maximum_upside() -> None:
    with pytest.raises(ValidationError):
        ScenarioOutcome(**_outcome_kwargs(maximum_future_upside=-0.01))


def test_outcome_rejects_positive_maximum_drawdown() -> None:
    with pytest.raises(ValidationError):
        ScenarioOutcome(**_outcome_kwargs(maximum_future_drawdown=0.01))


# ---------------------------------------------------------------------------
# ScenarioSubmission
# ---------------------------------------------------------------------------


def _submission_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        scenario_id=uuid4(),
        learner_id=uuid4(),
        exercise_attempt_id=uuid4(),
        rubric_version="scenario-rubric-v1",
        started_at=NOW,
    )
    kwargs.update(overrides)
    return kwargs


def test_submission_started_accepts_minimal_fields() -> None:
    submission = ScenarioSubmission(**_submission_kwargs())
    assert submission.status == ScenarioSubmissionStatus.STARTED


def test_submission_started_rejects_graded_values() -> None:
    with pytest.raises(ValidationError):
        ScenarioSubmission(
            **_submission_kwargs(
                status=ScenarioSubmissionStatus.STARTED,
                selected_option_id=uuid4(),
            )
        )


def test_submission_graded_requires_grading_fields() -> None:
    with pytest.raises(ValidationError):
        ScenarioSubmission(
            **_submission_kwargs(
                status=ScenarioSubmissionStatus.GRADED,
                selected_option_id=uuid4(),
                submitted_at=NOW,
            )
        )


def test_submission_graded_accepts_complete_fields() -> None:
    submission = ScenarioSubmission(
        **_submission_kwargs(
            status=ScenarioSubmissionStatus.GRADED,
            selected_option_id=uuid4(),
            submitted_at=NOW,
            graded_at=NOW,
            decision_quality_score=0.7,
            decision_quality=ScenarioDecisionQuality.GOOD,
            feedback_text="Solid, risk-aware decision.",
        )
    )
    assert submission.decision_quality == ScenarioDecisionQuality.GOOD


def test_submission_revealed_requires_reveal_fields() -> None:
    with pytest.raises(ValidationError):
        ScenarioSubmission(
            **_submission_kwargs(
                status=ScenarioSubmissionStatus.REVEALED,
                selected_option_id=uuid4(),
                submitted_at=NOW,
                graded_at=NOW,
                decision_quality_score=0.7,
                decision_quality=ScenarioDecisionQuality.GOOD,
                feedback_text="Solid decision.",
            )
        )


def test_submission_rejects_out_of_order_timestamps() -> None:
    with pytest.raises(ValidationError):
        ScenarioSubmission(
            **_submission_kwargs(
                status=ScenarioSubmissionStatus.SUBMITTED,
                selected_option_id=uuid4(),
                submitted_at=NOW - timedelta(days=1),
                started_at=NOW,
            )
        )


def test_submission_accepts_confidence_level_from_learning_enums() -> None:
    submission = ScenarioSubmission(
        **_submission_kwargs(confidence_level=ConfidenceLevel.HIGH)
    )
    assert submission.confidence_level == ConfidenceLevel.HIGH


# ---------------------------------------------------------------------------
# ScenarioGenerationRun
# ---------------------------------------------------------------------------


def _run_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        focal_security_id=uuid4(),
        requested_observation_start_at=NOW - timedelta(days=90),
        requested_decision_at=NOW - timedelta(days=30),
        requested_reveal_end_at=NOW,
        scenario_code="NVDA_2023_RALLY",
        scenario_version="scenario-v1",
        started_at=NOW,
    )
    kwargs.update(overrides)
    return kwargs


def test_generation_run_started_accepts_minimal_fields() -> None:
    run = ScenarioGenerationRun(**_run_kwargs())
    assert run.status == ScenarioGenerationRunStatus.STARTED


def test_generation_run_completed_requires_completed_at() -> None:
    with pytest.raises(ValidationError):
        ScenarioGenerationRun(**_run_kwargs(status=ScenarioGenerationRunStatus.COMPLETED))


def test_generation_run_failed_requires_sanitized_error_fields() -> None:
    with pytest.raises(ValidationError):
        ScenarioGenerationRun(
            **_run_kwargs(status=ScenarioGenerationRunStatus.FAILED, completed_at=NOW)
        )
    run = ScenarioGenerationRun(
        **_run_kwargs(
            status=ScenarioGenerationRunStatus.FAILED,
            completed_at=NOW,
            error_type="InsufficientDataError",
            error_message="Not enough stored bars.",
        )
    )
    assert run.error_type == "InsufficientDataError"


def test_generation_run_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError):
        ScenarioGenerationRun(**_run_kwargs(observation_bars_found=-1))
