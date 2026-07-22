"""Maps ORM rows to Phase 13 quality-evaluation domain models.

The normalized junction tables (`quality_evaluation_case_reference_*`,
`quality_evaluation_sample_retrieved_*`, `quality_evaluation_sample_citations`)
have no domain model of their own - each mapper that needs them accepts
the already-queried id lists as plain arguments, so repositories own the
JOIN/order-by and these functions stay pure."""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.quality_evaluation.models import (
    LearningQualityAggregate,
    QualityEvaluationBaseline,
    QualityEvaluationCase,
    QualityEvaluationRun,
    QualityEvaluationSampleResult,
    QualityEvaluationSuite,
    QualityMetricResult,
)
from stock_research_core.infrastructure.database.orm.learning_quality_aggregate import LearningQualityAggregateORM
from stock_research_core.infrastructure.database.orm.quality_evaluation_baseline import QualityEvaluationBaselineORM
from stock_research_core.infrastructure.database.orm.quality_evaluation_case import QualityEvaluationCaseORM
from stock_research_core.infrastructure.database.orm.quality_evaluation_run import QualityEvaluationRunORM
from stock_research_core.infrastructure.database.orm.quality_evaluation_sample_result import (
    QualityEvaluationSampleResultORM,
)
from stock_research_core.infrastructure.database.orm.quality_evaluation_suite import QualityEvaluationSuiteORM
from stock_research_core.infrastructure.database.orm.quality_metric_result import QualityMetricResultORM


def quality_evaluation_suite_orm_to_domain(row: QualityEvaluationSuiteORM) -> QualityEvaluationSuite:
    try:
        return QualityEvaluationSuite(
            suite_id=row.suite_id, code=row.code, name=row.name, description=row.description,
            suite_type=row.suite_type, status=row.status, version=row.version, language=row.language,
            case_count=row.case_count, dataset_hash=row.dataset_hash, created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored quality-evaluation-suite row '{row.suite_id}' could not be mapped.") from exc


def quality_evaluation_case_orm_to_domain(
    row: QualityEvaluationCaseORM, *,
    reference_document_ids: list[UUID], reference_chunk_ids: list[UUID], expected_skill_ids: list[UUID],
) -> QualityEvaluationCase:
    try:
        return QualityEvaluationCase(
            case_id=row.case_id, suite_id=row.suite_id, external_case_id=row.external_case_id, status=row.status,
            context_type=row.context_type, user_input=row.user_input, reference_answer=row.reference_answer,
            reference_contexts=list(row.reference_contexts or []),
            reference_document_ids=reference_document_ids, reference_chunk_ids=reference_chunk_ids,
            expected_skill_ids=expected_skill_ids,
            expected_guardrail_category=row.expected_guardrail_category, expected_refusal=row.expected_refusal,
            expected_fallback=row.expected_fallback, expected_intent=row.expected_intent,
            expected_route=row.expected_route, expected_action_type=row.expected_action_type,
            expected_interrupt=row.expected_interrupt, forbidden_phrases=list(row.forbidden_phrases or []),
            required_concepts=list(row.required_concepts or []), metadata=dict(row.case_metadata or {}),
            case_version=row.case_version, created_at=row.created_at, updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored quality-evaluation-case row '{row.case_id}' could not be mapped.") from exc


def quality_evaluation_run_orm_to_domain(row: QualityEvaluationRunORM) -> QualityEvaluationRun:
    try:
        return QualityEvaluationRun(
            run_id=row.run_id, suite_id=row.suite_id, status=row.status, mode=row.mode,
            requested_by_account_id=row.requested_by_account_id, background_job_id=row.background_job_id,
            system_version=row.system_version, git_commit=row.git_commit,
            retrieval_policy_version=row.retrieval_policy_version, embedding_model=row.embedding_model,
            embedding_version=row.embedding_version, tutor_policy_version=row.tutor_policy_version,
            prompt_version=row.prompt_version, guardrail_version=row.guardrail_version,
            graph_version=row.graph_version, evaluator_provider=row.evaluator_provider,
            evaluator_model=row.evaluator_model, ragas_version=row.ragas_version, case_count=row.case_count,
            completed_case_count=row.completed_case_count, failed_case_count=row.failed_case_count,
            skipped_case_count=row.skipped_case_count, started_at=row.started_at, completed_at=row.completed_at,
            dataset_hash=row.dataset_hash, configuration_hash=row.configuration_hash,
            created_at=row.created_at, updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored quality-evaluation-run row '{row.run_id}' could not be mapped.") from exc


def quality_evaluation_sample_result_orm_to_domain(
    row: QualityEvaluationSampleResultORM, *,
    retrieved_context_ids: list[UUID], retrieved_document_ids: list[UUID], citation_chunk_ids: list[UUID],
) -> QualityEvaluationSampleResult:
    try:
        return QualityEvaluationSampleResult(
            sample_result_id=row.sample_result_id, run_id=row.run_id, case_id=row.case_id, status=row.status,
            generated_response=row.generated_response, retrieved_context_ids=retrieved_context_ids,
            retrieved_document_ids=retrieved_document_ids, citation_chunk_ids=citation_chunk_ids,
            observed_guardrail_category=row.observed_guardrail_category, observed_intent=row.observed_intent,
            observed_route=row.observed_route, observed_action_type=row.observed_action_type,
            observed_interrupt=row.observed_interrupt, latency_ms=row.latency_ms,
            retrieval_latency_ms=row.retrieval_latency_ms, generation_latency_ms=row.generation_latency_ms,
            input_token_count=row.input_token_count, output_token_count=row.output_token_count,
            estimated_cost=float(row.estimated_cost) if row.estimated_cost is not None else None,
            failure_code=row.failure_code, failure_message=row.failure_message, created_at=row.created_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored quality-evaluation-sample-result row '{row.sample_result_id}' could not be mapped."
        ) from exc


def quality_metric_result_orm_to_domain(row: QualityMetricResultORM) -> QualityMetricResult:
    try:
        return QualityMetricResult(
            metric_result_id=row.metric_result_id, run_id=row.run_id, sample_result_id=row.sample_result_id,
            metric_name=row.metric_name, metric_type=row.metric_type, metric_version=row.metric_version,
            score=row.score, passed=row.passed, threshold=row.threshold, details=dict(row.details or {}),
            evaluator_provider=row.evaluator_provider, evaluator_model=row.evaluator_model,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored quality-metric-result row '{row.metric_result_id}' could not be mapped."
        ) from exc


def quality_evaluation_baseline_orm_to_domain(row: QualityEvaluationBaselineORM) -> QualityEvaluationBaseline:
    try:
        return QualityEvaluationBaseline(
            baseline_id=row.baseline_id, suite_id=row.suite_id, run_id=row.run_id, name=row.name,
            approved=row.approved, approved_by_account_id=row.approved_by_account_id,
            metric_summary=dict(row.metric_summary or {}), safety_gate_summary=dict(row.safety_gate_summary or {}),
            created_at=row.created_at, approved_at=row.approved_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored quality-evaluation-baseline row '{row.baseline_id}' could not be mapped."
        ) from exc


def learning_quality_aggregate_orm_to_domain(row: LearningQualityAggregateORM) -> LearningQualityAggregate:
    try:
        return LearningQualityAggregate(
            aggregate_id=row.aggregate_id, metric_type=row.metric_type, period_start=row.period_start,
            period_end=row.period_end, cohort_key=row.cohort_key, cohort_size=row.cohort_size, value=row.value,
            sample_count=row.sample_count, calculation_version=row.calculation_version,
            filters=dict(row.filters or {}), created_at=row.created_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored learning-quality-aggregate row '{row.aggregate_id}' could not be mapped."
        ) from exc
