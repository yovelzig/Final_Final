"""Unit tests for historical-market-scenario ORM-to-domain mapper functions.

ORM classes are instantiated as plain Python objects (no database
connection, no PostgreSQL required).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
    ScenarioDecisionQuality,
    ScenarioExpectedDirection,
    ScenarioFeedbackCode,
    ScenarioGenerationRunStatus,
    ScenarioOutcomeDirection,
    ScenarioRevealStatus,
    ScenarioSecurityRole,
    ScenarioSubmissionStatus,
)
from stock_research_core.infrastructure.database.mappers.market_scenario_mappers import (
    historical_market_scenario_orm_to_domain,
    scenario_generation_run_orm_to_domain,
    scenario_option_rubric_orm_to_domain,
    scenario_outcome_orm_to_domain,
    scenario_security_orm_to_domain,
    scenario_submission_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.historical_market_scenario import (
    HistoricalMarketScenarioORM,
)
from stock_research_core.infrastructure.database.orm.scenario_generation_run import (
    ScenarioGenerationRunORM,
)
from stock_research_core.infrastructure.database.orm.scenario_option_rubric import (
    ScenarioOptionRubricORM,
)
from stock_research_core.infrastructure.database.orm.scenario_outcome import ScenarioOutcomeORM
from stock_research_core.infrastructure.database.orm.scenario_security import ScenarioSecurityORM
from stock_research_core.infrastructure.database.orm.scenario_submission import ScenarioSubmissionORM

UTC_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_scenario_orm_to_domain_maps_arrays_enums_and_uuids() -> None:
    scenario_id = uuid4()
    exercise_id = uuid4()
    focal_security_id = uuid4()
    benchmark_security_id = uuid4()
    primary_skill_id = uuid4()
    secondary_skill_id = uuid4()

    row = HistoricalMarketScenarioORM(
        scenario_id=scenario_id,
        exercise_id=exercise_id,
        code="NVDA_20230101",
        title="Title",
        description="Description",
        scenario_type=MarketScenarioType.MARKET_REPLAY.value,
        status=MarketScenarioStatus.PUBLISHED.value,
        observation_start_at=UTC_NOW - timedelta(days=60),
        decision_at=UTC_NOW - timedelta(days=20),
        reveal_end_at=UTC_NOW,
        interval="1d",
        source_name="yfinance",
        prompt="Prompt",
        learner_instructions="Instructions",
        learning_objectives=["Objective one"],
        minimum_observation_bars=40,
        minimum_reveal_bars=20,
        scenario_version="scenario-v1",
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    scenario = historical_market_scenario_orm_to_domain(
        row,
        focal_security_id=focal_security_id,
        benchmark_security_id=benchmark_security_id,
        primary_skill_ids=[primary_skill_id],
        secondary_skill_ids=[secondary_skill_id],
    )

    assert scenario.scenario_id == scenario_id
    assert scenario.scenario_type == MarketScenarioType.MARKET_REPLAY
    assert scenario.status == MarketScenarioStatus.PUBLISHED
    assert scenario.focal_security_id == focal_security_id
    assert scenario.benchmark_security_id == benchmark_security_id
    assert scenario.primary_skill_ids == [primary_skill_id]
    assert scenario.secondary_skill_ids == [secondary_skill_id]
    assert scenario.learning_objectives == ["Objective one"]
    assert scenario.created_at.tzinfo is not None


def test_scenario_orm_to_domain_raises_on_invalid_stored_data() -> None:
    row = HistoricalMarketScenarioORM(
        scenario_id=uuid4(),
        exercise_id=uuid4(),
        code="NVDA_20230101",
        title="Title",
        description="Description",
        scenario_type="NOT_A_REAL_TYPE",
        status=MarketScenarioStatus.PUBLISHED.value,
        observation_start_at=UTC_NOW,
        decision_at=UTC_NOW,
        reveal_end_at=UTC_NOW,
        interval="1d",
        source_name="yfinance",
        prompt="Prompt",
        learner_instructions="Instructions",
        learning_objectives=[],
        minimum_observation_bars=40,
        minimum_reveal_bars=20,
        scenario_version="scenario-v1",
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )
    with pytest.raises(DatabaseMappingError):
        historical_market_scenario_orm_to_domain(
            row,
            focal_security_id=uuid4(),
            benchmark_security_id=None,
            primary_skill_ids=[uuid4()],
            secondary_skill_ids=[],
        )


def test_scenario_security_orm_to_domain() -> None:
    row = ScenarioSecurityORM(
        scenario_security_id=uuid4(),
        scenario_id=uuid4(),
        security_id=uuid4(),
        role=ScenarioSecurityRole.FOCAL.value,
        created_at=UTC_NOW,
    )
    security = scenario_security_orm_to_domain(row)
    assert security.role == ScenarioSecurityRole.FOCAL


def test_scenario_option_rubric_orm_to_domain_maps_decimals_and_feedback_codes() -> None:
    row = ScenarioOptionRubricORM(
        rubric_id=uuid4(),
        scenario_id=uuid4(),
        exercise_option_id=uuid4(),
        decision_quality_score=Decimal("0.7000"),
        risk_awareness_score=Decimal("0.7000"),
        benchmark_awareness_score=Decimal("0.7000"),
        horizon_alignment_score=Decimal("0.7000"),
        information_sufficiency_score=Decimal("0.7000"),
        uncertainty_awareness_score=Decimal("0.7000"),
        expected_direction=ScenarioExpectedDirection.NEUTRAL.value,
        positive_feedback="Good.",
        improvement_feedback="Better.",
        rubric_version="scenario-rubric-v1",
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )
    rubric = scenario_option_rubric_orm_to_domain(
        row, [ScenarioFeedbackCode.IDENTIFIED_RISK.value, ScenarioFeedbackCode.CONSIDERED_BENCHMARK.value]
    )
    assert rubric.decision_quality_score == 0.7
    assert isinstance(rubric.decision_quality_score, float)
    assert rubric.feedback_codes == [
        ScenarioFeedbackCode.IDENTIFIED_RISK,
        ScenarioFeedbackCode.CONSIDERED_BENCHMARK,
    ]
    assert rubric.expected_direction == ScenarioExpectedDirection.NEUTRAL


def test_scenario_option_rubric_orm_to_domain_raises_when_inconsistent_with_weights() -> None:
    row = ScenarioOptionRubricORM(
        rubric_id=uuid4(),
        scenario_id=uuid4(),
        exercise_option_id=uuid4(),
        decision_quality_score=Decimal("0.9999"),
        risk_awareness_score=Decimal("0.1000"),
        benchmark_awareness_score=Decimal("0.1000"),
        horizon_alignment_score=Decimal("0.1000"),
        information_sufficiency_score=Decimal("0.1000"),
        uncertainty_awareness_score=Decimal("0.1000"),
        expected_direction=ScenarioExpectedDirection.NEUTRAL.value,
        positive_feedback="Good.",
        improvement_feedback="Better.",
        rubric_version="scenario-rubric-v1",
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )
    with pytest.raises(DatabaseMappingError):
        scenario_option_rubric_orm_to_domain(row, [])


def test_scenario_outcome_orm_to_domain_maps_optional_fields() -> None:
    row = ScenarioOutcomeORM(
        outcome_id=uuid4(),
        scenario_id=uuid4(),
        decision_at=UTC_NOW - timedelta(days=30),
        reveal_end_at=UTC_NOW,
        focal_start_close=Decimal("100.00000000"),
        focal_end_close=Decimal("110.00000000"),
        focal_return=Decimal("0.100000"),
        maximum_future_upside=Decimal("0.150000"),
        maximum_future_drawdown=Decimal("-0.050000"),
        benchmark_return=None,
        excess_return=None,
        outcome_direction=ScenarioOutcomeDirection.POSITIVE.value,
        outcome_summary="It rose.",
        calculation_version="scenario-outcome-v1",
        calculated_at=UTC_NOW,
    )
    outcome = scenario_outcome_orm_to_domain(row)
    assert outcome.benchmark_return is None
    assert outcome.focal_return == 0.10
    assert outcome.outcome_direction == ScenarioOutcomeDirection.POSITIVE


def test_scenario_submission_orm_to_domain_maps_nullable_grading_fields() -> None:
    row = ScenarioSubmissionORM(
        submission_id=uuid4(),
        scenario_id=uuid4(),
        learner_id=uuid4(),
        exercise_attempt_id=uuid4(),
        selected_option_id=None,
        status=ScenarioSubmissionStatus.STARTED.value,
        confidence_level=None,
        learner_rationale=None,
        decision_quality_score=None,
        outcome_alignment_score=None,
        total_display_score=None,
        decision_quality=None,
        feedback_text=None,
        reveal_status=ScenarioRevealStatus.HIDDEN.value,
        started_at=UTC_NOW,
        submitted_at=None,
        graded_at=None,
        revealed_at=None,
        rubric_version="scenario-rubric-v1",
        outcome_calculation_version=None,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )
    submission = scenario_submission_orm_to_domain(row, [])
    assert submission.status == ScenarioSubmissionStatus.STARTED
    assert submission.decision_quality_score is None
    assert submission.decision_quality is None


def test_scenario_submission_orm_to_domain_maps_graded_fields_and_feedback_codes() -> None:
    row = ScenarioSubmissionORM(
        submission_id=uuid4(),
        scenario_id=uuid4(),
        learner_id=uuid4(),
        exercise_attempt_id=uuid4(),
        selected_option_id=uuid4(),
        status=ScenarioSubmissionStatus.GRADED.value,
        confidence_level="HIGH",
        learner_rationale="Because risk.",
        decision_quality_score=Decimal("0.7500"),
        outcome_alignment_score=None,
        total_display_score=None,
        decision_quality=ScenarioDecisionQuality.GOOD.value,
        feedback_text="Well reasoned.",
        reveal_status=ScenarioRevealStatus.AVAILABLE.value,
        started_at=UTC_NOW,
        submitted_at=UTC_NOW,
        graded_at=UTC_NOW,
        revealed_at=None,
        rubric_version="scenario-rubric-v1",
        outcome_calculation_version=None,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )
    submission = scenario_submission_orm_to_domain(row, [ScenarioFeedbackCode.OVERCONFIDENT_DECISION.value])
    assert submission.decision_quality_score == 0.75
    assert submission.decision_quality == ScenarioDecisionQuality.GOOD
    assert submission.feedback_codes == [ScenarioFeedbackCode.OVERCONFIDENT_DECISION]


def test_scenario_generation_run_orm_to_domain_maps_error_fields() -> None:
    row = ScenarioGenerationRunORM(
        run_id=uuid4(),
        status=ScenarioGenerationRunStatus.FAILED.value,
        focal_security_id=uuid4(),
        benchmark_security_id=None,
        requested_observation_start_at=UTC_NOW,
        requested_decision_at=UTC_NOW,
        requested_reveal_end_at=UTC_NOW,
        scenario_code="NVDA_20230101",
        scenario_version="scenario-v1",
        observation_bars_found=10,
        reveal_bars_found=0,
        benchmark_bars_found=0,
        started_at=UTC_NOW,
        completed_at=UTC_NOW,
        error_type="InsufficientScenarioDataError",
        error_message="Not enough bars.",
    )
    run = scenario_generation_run_orm_to_domain(row)
    assert run.status == ScenarioGenerationRunStatus.FAILED
    assert run.error_type == "InsufficientScenarioDataError"
    assert run.benchmark_security_id is None


def test_scenario_generation_run_orm_to_domain_raises_on_invalid_status() -> None:
    row = ScenarioGenerationRunORM(
        run_id=uuid4(),
        status="NOT_A_REAL_STATUS",
        focal_security_id=uuid4(),
        benchmark_security_id=None,
        requested_observation_start_at=UTC_NOW,
        requested_decision_at=UTC_NOW,
        requested_reveal_end_at=UTC_NOW,
        scenario_code="NVDA_20230101",
        scenario_version="scenario-v1",
        observation_bars_found=10,
        reveal_bars_found=5,
        benchmark_bars_found=0,
        started_at=UTC_NOW,
        completed_at=None,
        error_type=None,
        error_message=None,
    )
    with pytest.raises(DatabaseMappingError):
        scenario_generation_run_orm_to_domain(row)
