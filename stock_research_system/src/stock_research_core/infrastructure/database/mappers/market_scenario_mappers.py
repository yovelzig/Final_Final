"""Maps between historical-market-scenario ORM rows and domain models.

`HistoricalMarketScenario.focal_security_id`/`benchmark_security_id`,
`primary_skill_ids`/`secondary_skill_ids`, `ScenarioOptionRubric.
feedback_codes`, and `ScenarioSubmission.feedback_codes` all live in
separate association tables, not on the primary ORM row - repositories
query those separately and pass the resulting values into these mapper
functions, the same pattern used throughout `learning_mappers.py` and
`adaptive_learning_mappers.py`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

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
from stock_research_core.domain.market_scenarios.models import (
    HistoricalMarketScenario,
    ScenarioGenerationRun,
    ScenarioOptionRubric,
    ScenarioOutcome,
    ScenarioSecurity,
    ScenarioSubmission,
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


def historical_market_scenario_orm_to_domain(
    row: HistoricalMarketScenarioORM,
    *,
    focal_security_id: UUID,
    benchmark_security_id: UUID | None,
    primary_skill_ids: list[UUID],
    secondary_skill_ids: list[UUID],
) -> HistoricalMarketScenario:
    try:
        return HistoricalMarketScenario(
            scenario_id=row.scenario_id,
            exercise_id=row.exercise_id,
            code=row.code,
            title=row.title,
            description=row.description,
            scenario_type=MarketScenarioType(row.scenario_type),
            status=MarketScenarioStatus(row.status),
            observation_start_at=row.observation_start_at,
            decision_at=row.decision_at,
            reveal_end_at=row.reveal_end_at,
            interval=row.interval,
            source_name=row.source_name,
            focal_security_id=focal_security_id,
            benchmark_security_id=benchmark_security_id,
            primary_skill_ids=primary_skill_ids,
            secondary_skill_ids=secondary_skill_ids,
            prompt=row.prompt,
            learner_instructions=row.learner_instructions,
            learning_objectives=list(row.learning_objectives or []),
            minimum_observation_bars=row.minimum_observation_bars,
            minimum_reveal_bars=row.minimum_reveal_bars,
            scenario_version=row.scenario_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored scenario row '{row.scenario_id}' could not be mapped to a domain "
            "HistoricalMarketScenario."
        ) from exc


def scenario_security_orm_to_domain(row: ScenarioSecurityORM) -> ScenarioSecurity:
    try:
        return ScenarioSecurity(
            scenario_security_id=row.scenario_security_id,
            scenario_id=row.scenario_id,
            security_id=row.security_id,
            role=ScenarioSecurityRole(row.role),
            created_at=row.created_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored scenario security row '{row.scenario_security_id}' could not be mapped to "
            "a domain ScenarioSecurity."
        ) from exc


def scenario_option_rubric_orm_to_domain(
    row: ScenarioOptionRubricORM, feedback_codes: list[str]
) -> ScenarioOptionRubric:
    try:
        return ScenarioOptionRubric(
            rubric_id=row.rubric_id,
            scenario_id=row.scenario_id,
            exercise_option_id=row.exercise_option_id,
            decision_quality_score=float(row.decision_quality_score),
            risk_awareness_score=float(row.risk_awareness_score),
            benchmark_awareness_score=float(row.benchmark_awareness_score),
            horizon_alignment_score=float(row.horizon_alignment_score),
            information_sufficiency_score=float(row.information_sufficiency_score),
            uncertainty_awareness_score=float(row.uncertainty_awareness_score),
            expected_direction=ScenarioExpectedDirection(row.expected_direction),
            feedback_codes=[ScenarioFeedbackCode(code) for code in feedback_codes],
            positive_feedback=row.positive_feedback,
            improvement_feedback=row.improvement_feedback,
            rubric_version=row.rubric_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored rubric row '{row.rubric_id}' could not be mapped to a domain "
            "ScenarioOptionRubric."
        ) from exc


def scenario_outcome_orm_to_domain(row: ScenarioOutcomeORM) -> ScenarioOutcome:
    try:
        return ScenarioOutcome(
            outcome_id=row.outcome_id,
            scenario_id=row.scenario_id,
            decision_at=row.decision_at,
            reveal_end_at=row.reveal_end_at,
            focal_start_close=float(row.focal_start_close),
            focal_end_close=float(row.focal_end_close),
            focal_return=float(row.focal_return),
            maximum_future_upside=float(row.maximum_future_upside),
            maximum_future_drawdown=float(row.maximum_future_drawdown),
            benchmark_return=float(row.benchmark_return) if row.benchmark_return is not None else None,
            excess_return=float(row.excess_return) if row.excess_return is not None else None,
            outcome_direction=ScenarioOutcomeDirection(row.outcome_direction),
            outcome_summary=row.outcome_summary,
            calculation_version=row.calculation_version,
            calculated_at=row.calculated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored outcome row '{row.outcome_id}' could not be mapped to a domain ScenarioOutcome."
        ) from exc


def scenario_submission_orm_to_domain(
    row: ScenarioSubmissionORM, feedback_codes: list[str]
) -> ScenarioSubmission:
    try:
        return ScenarioSubmission(
            submission_id=row.submission_id,
            scenario_id=row.scenario_id,
            learner_id=row.learner_id,
            exercise_attempt_id=row.exercise_attempt_id,
            status=ScenarioSubmissionStatus(row.status),
            selected_option_id=row.selected_option_id,
            confidence_level=row.confidence_level,
            learner_rationale=row.learner_rationale,
            decision_quality_score=(
                float(row.decision_quality_score) if row.decision_quality_score is not None else None
            ),
            outcome_alignment_score=(
                float(row.outcome_alignment_score) if row.outcome_alignment_score is not None else None
            ),
            total_display_score=(
                float(row.total_display_score) if row.total_display_score is not None else None
            ),
            decision_quality=(
                ScenarioDecisionQuality(row.decision_quality) if row.decision_quality else None
            ),
            feedback_codes=[ScenarioFeedbackCode(code) for code in feedback_codes],
            feedback_text=row.feedback_text,
            reveal_status=ScenarioRevealStatus(row.reveal_status),
            started_at=row.started_at,
            submitted_at=row.submitted_at,
            graded_at=row.graded_at,
            revealed_at=row.revealed_at,
            rubric_version=row.rubric_version,
            outcome_calculation_version=row.outcome_calculation_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored submission row '{row.submission_id}' could not be mapped to a domain "
            "ScenarioSubmission."
        ) from exc


def scenario_generation_run_orm_to_domain(row: ScenarioGenerationRunORM) -> ScenarioGenerationRun:
    try:
        return ScenarioGenerationRun(
            run_id=row.run_id,
            status=ScenarioGenerationRunStatus(row.status),
            focal_security_id=row.focal_security_id,
            benchmark_security_id=row.benchmark_security_id,
            requested_observation_start_at=row.requested_observation_start_at,
            requested_decision_at=row.requested_decision_at,
            requested_reveal_end_at=row.requested_reveal_end_at,
            scenario_code=row.scenario_code,
            scenario_version=row.scenario_version,
            observation_bars_found=row.observation_bars_found,
            reveal_bars_found=row.reveal_bars_found,
            benchmark_bars_found=row.benchmark_bars_found,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error_type=row.error_type,
            error_message=row.error_message,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored generation run row '{row.run_id}' could not be mapped to a domain "
            "ScenarioGenerationRun."
        ) from exc
