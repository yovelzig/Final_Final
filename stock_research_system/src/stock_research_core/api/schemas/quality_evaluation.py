"""Request/response DTOs for `/api/v1/admin/evaluations` (Phase 13,
ADMIN-only quality-evaluation control plane). Never exposes evaluator
prompts, hidden reasoning, raw learner content, provider keys, database
URLs, or tracebacks (spec section 22)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.domain.quality_evaluation.enums import (
    LearningOutcomeMetricType,
    QualityEvaluationCaseStatus,
    QualityEvaluationMode,
    QualityEvaluationRunStatus,
    QualityEvaluationSuiteType,
    QualityGateStatus,
)
from stock_research_core.domain.quality_evaluation.models import (
    QualityEvaluationBaseline,
    QualityEvaluationRun,
    QualityEvaluationSampleResult,
    QualityEvaluationSuite,
    QualityMetricResult,
)


class QualityEvaluationSuiteResponse(ApiSchema):
    suite_id: UUID
    code: str
    name: str
    description: str
    suite_type: QualityEvaluationSuiteType
    status: QualityEvaluationCaseStatus
    version: str
    language: str
    case_count: int
    dataset_hash: str
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_domain(suite: QualityEvaluationSuite) -> QualityEvaluationSuiteResponse:
        return QualityEvaluationSuiteResponse(
            suite_id=suite.suite_id, code=suite.code, name=suite.name, description=suite.description,
            suite_type=suite.suite_type, status=suite.status, version=suite.version, language=suite.language,
            case_count=suite.case_count, dataset_hash=suite.dataset_hash, created_at=suite.created_at,
            updated_at=suite.updated_at,
        )


class QualityEvaluationSuiteListResponse(ApiSchema):
    items: list[QualityEvaluationSuiteResponse]
    limit: int
    offset: int


class ImportSuiteRequest(ApiSchema):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    suite_type: QualityEvaluationSuiteType
    version: str = Field(min_length=1, max_length=50)


class CreateRunRequest(ApiSchema):
    suite_id: UUID
    mode: QualityEvaluationMode
    idempotency_key: str = Field(min_length=1, max_length=200)
    system_version: str = Field(min_length=1, max_length=100)
    git_commit: str | None = Field(default=None, max_length=64)
    retrieval_policy_version: str = Field(min_length=1, max_length=50)
    embedding_model: str = Field(min_length=1, max_length=100)
    embedding_version: str = Field(min_length=1, max_length=50)
    tutor_policy_version: str = Field(min_length=1, max_length=50)
    prompt_version: str = Field(min_length=1, max_length=50)
    guardrail_version: str = Field(min_length=1, max_length=50)
    graph_version: str | None = Field(default=None, max_length=50)
    maximum_cases: int | None = Field(default=None, gt=0, le=10000)
    maximum_concurrency: int = Field(default=4, gt=0, le=32)


class CreateRunResponse(ApiSchema):
    job_id: UUID
    suite_id: UUID
    mode: QualityEvaluationMode
    status: str = "QUEUED"


class QualityEvaluationRunResponse(ApiSchema):
    run_id: UUID
    suite_id: UUID
    status: QualityEvaluationRunStatus
    mode: QualityEvaluationMode

    system_version: str
    git_commit: str | None
    retrieval_policy_version: str
    embedding_model: str
    embedding_version: str
    tutor_policy_version: str
    prompt_version: str
    guardrail_version: str
    graph_version: str | None

    evaluator_provider: str | None
    evaluator_model: str | None
    ragas_version: str | None

    case_count: int
    completed_case_count: int
    failed_case_count: int
    skipped_case_count: int

    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_domain(run: QualityEvaluationRun) -> QualityEvaluationRunResponse:
        return QualityEvaluationRunResponse(
            run_id=run.run_id, suite_id=run.suite_id, status=run.status, mode=run.mode,
            system_version=run.system_version, git_commit=run.git_commit,
            retrieval_policy_version=run.retrieval_policy_version, embedding_model=run.embedding_model,
            embedding_version=run.embedding_version, tutor_policy_version=run.tutor_policy_version,
            prompt_version=run.prompt_version, guardrail_version=run.guardrail_version,
            graph_version=run.graph_version, evaluator_provider=run.evaluator_provider,
            evaluator_model=run.evaluator_model, ragas_version=run.ragas_version, case_count=run.case_count,
            completed_case_count=run.completed_case_count, failed_case_count=run.failed_case_count,
            skipped_case_count=run.skipped_case_count, started_at=run.started_at, completed_at=run.completed_at,
            created_at=run.created_at, updated_at=run.updated_at,
        )


class QualityEvaluationRunListResponse(ApiSchema):
    items: list[QualityEvaluationRunResponse]
    limit: int
    offset: int


class QualityEvaluationSampleResultResponse(ApiSchema):
    sample_result_id: UUID
    run_id: UUID
    case_id: UUID
    status: QualityGateStatus
    latency_ms: int
    failure_code: str | None
    #: Sanitized only - never the full generated response by default
    #: (spec section 26: "Do not log complete generated answers by
    #: default"). Truncated for the same reason it is not logged.
    generated_response_preview: str | None

    @staticmethod
    def from_domain(sample: QualityEvaluationSampleResult) -> QualityEvaluationSampleResultResponse:
        preview = None
        if sample.generated_response:
            preview = sample.generated_response[:200]
        return QualityEvaluationSampleResultResponse(
            sample_result_id=sample.sample_result_id, run_id=sample.run_id, case_id=sample.case_id,
            status=sample.status, latency_ms=sample.latency_ms, failure_code=sample.failure_code,
            generated_response_preview=preview,
        )


class QualityEvaluationSampleResultListResponse(ApiSchema):
    items: list[QualityEvaluationSampleResultResponse]


class QualityMetricResultResponse(ApiSchema):
    metric_name: str
    metric_type: str
    metric_version: str
    score: float | None
    passed: bool | None
    threshold: float | None
    sample_result_id: UUID | None

    @staticmethod
    def from_domain(metric: QualityMetricResult) -> QualityMetricResultResponse:
        return QualityMetricResultResponse(
            metric_name=metric.metric_name, metric_type=metric.metric_type.value,
            metric_version=metric.metric_version, score=metric.score, passed=metric.passed,
            threshold=metric.threshold, sample_result_id=metric.sample_result_id,
        )


class QualityMetricResultListResponse(ApiSchema):
    items: list[QualityMetricResultResponse]


class CompareRunRequest(ApiSchema):
    baseline_id: UUID


class MetricComparisonResponse(ApiSchema):
    metric_name: str
    baseline_value: float | None
    candidate_value: float | None
    result: str
    detail: str | None


class EvaluationRegressionReportResponse(ApiSchema):
    run_id: UUID
    baseline_id: UUID
    comparable: bool
    overall_result: str
    metric_comparisons: list[MetricComparisonResponse]
    notes: list[str]


class ApproveBaselineRequest(ApiSchema):
    name: str = Field(min_length=1, max_length=200)


class QualityEvaluationBaselineResponse(ApiSchema):
    baseline_id: UUID
    suite_id: UUID
    run_id: UUID
    name: str
    approved: bool
    metric_summary: dict[str, float]
    safety_gate_summary: dict[str, bool]
    created_at: datetime
    approved_at: datetime | None

    @staticmethod
    def from_domain(baseline: QualityEvaluationBaseline) -> QualityEvaluationBaselineResponse:
        return QualityEvaluationBaselineResponse(
            baseline_id=baseline.baseline_id, suite_id=baseline.suite_id, run_id=baseline.run_id,
            name=baseline.name, approved=baseline.approved, metric_summary=baseline.metric_summary,
            safety_gate_summary=baseline.safety_gate_summary, created_at=baseline.created_at,
            approved_at=baseline.approved_at,
        )


class QualityEvaluationBaselineListResponse(ApiSchema):
    items: list[QualityEvaluationBaselineResponse]
