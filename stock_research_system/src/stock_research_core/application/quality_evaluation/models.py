"""Application-layer DTOs for the Phase 13 quality-evaluation platform.

These are the *only* shapes that cross the boundary between the runner/
service and the metric adapters (deterministic + RAGAS) - the RAGAS
adapter converts `RagasSingleTurnInput`/`RagasMultiTurnInput` to its own
`SingleTurnSample`/`MultiTurnSample` internally (see
`infrastructure.quality_evaluation.ragas_adapter`); nothing here is a
RAGAS type.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from stock_research_core.domain.ai_tutor.enums import TutorContextType, TutorRequestCategory
from stock_research_core.domain.learning_orchestrator.enums import LearningActionType, LearningIntent, LearningOrchestratorRoute
from stock_research_core.domain.models import DomainModel
from stock_research_core.domain.quality_evaluation.enums import (
    EvaluationCaseContextType,
    EvaluationComparisonResult,
    LearningOutcomeMetricType,
    QualityEvaluationMode,
    QualityEvaluationRunStatus,
    QualityGateStatus,
)


class EvaluationConfiguration(DomainModel):
    """System/model lineage + evaluation-run knobs supplied by the
    caller (API/CLI/n8n job) to `QualityEvaluationService.create_run`.
    Persisted verbatim onto the resulting `QualityEvaluationRun` (spec
    section 17, step 3: "Record system lineage")."""

    system_version: str
    git_commit: str | None = None
    retrieval_policy_version: str
    embedding_model: str
    embedding_version: str
    tutor_policy_version: str
    prompt_version: str
    guardrail_version: str
    graph_version: str | None = None

    ragas_metric_names: list[str] = Field(default_factory=list)
    maximum_concurrency: int = Field(default=4, gt=0, le=32)
    maximum_cases: int | None = Field(default=None, gt=0)


class EvaluationCaseExecutionInput(DomainModel):
    """Everything an `EvaluationCaseExecutorPort` needs to execute one
    case - always derived from a curated `QualityEvaluationCase`, never
    from real learner data."""

    case_id: UUID
    context_type: EvaluationCaseContextType
    user_input: str
    context_references: dict[str, str] = Field(default_factory=dict)


class EvaluationCaseExecutionResult(DomainModel):
    """The observed outcome of executing one case - the source both
    deterministic metrics and (optionally) RAGAS samples are built from."""

    case_id: UUID
    generated_response: str | None = None
    retrieved_context_ids: list[UUID] = Field(default_factory=list)
    retrieved_document_ids: list[UUID] = Field(default_factory=list)
    retrieved_context_texts: list[str] = Field(default_factory=list)
    citation_chunk_ids: list[UUID] = Field(default_factory=list)

    observed_guardrail_category: TutorRequestCategory | None = None
    observed_intent: LearningIntent | None = None
    observed_route: LearningOrchestratorRoute | None = None
    observed_action_type: LearningActionType | None = None
    observed_interrupt: bool | None = None
    action_executed: bool = False

    latency_ms: int = 0
    retrieval_latency_ms: int | None = None
    generation_latency_ms: int | None = None
    input_token_count: int | None = None
    output_token_count: int | None = None
    estimated_cost: float | None = None

    failure_code: str | None = None
    failure_message: str | None = None


class DeterministicMetricResult(DomainModel):
    """One deterministic metric's outcome for one sample or the run
    aggregate - `passed`/`score` mirror `QualityMetricResult`'s own
    "not every metric is 0-1" rule."""

    metric_name: str
    score: float | None = None
    passed: bool | None = None
    threshold: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    gate_status: QualityGateStatus = QualityGateStatus.NOT_EVALUATED
    is_hard_gate: bool = False


class RagasSingleTurnInput(DomainModel):
    """Application-layer analogue of a RAGAS `SingleTurnSample` - built
    from curated case + executed-case data, converted to the real RAGAS
    type only inside the infrastructure adapter."""

    case_id: UUID
    user_input: str
    response: str
    retrieved_contexts: list[str] = Field(default_factory=list)
    reference: str | None = None
    reference_contexts: list[str] = Field(default_factory=list)


class RagasMultiTurnInput(DomainModel):
    """Application-layer analogue of a RAGAS `MultiTurnSample` - one
    Coach conversation's turns, each `{"role": ..., "content": ...}`."""

    case_id: UUID
    turns: list[dict[str, str]] = Field(default_factory=list)
    reference: str | None = None


class RagasMetricRequest(DomainModel):
    """A request to score a batch of already-executed cases against a
    named set of RAGAS metrics."""

    metric_names: list[str]
    single_turn_samples: list[RagasSingleTurnInput] = Field(default_factory=list)
    multi_turn_samples: list[RagasMultiTurnInput] = Field(default_factory=list)


class RagasSampleResult(DomainModel):
    """One case's per-metric RAGAS scores, plus whichever requested
    metrics had to be skipped for that case and why (spec section 12:
    "Skip unsupported case/metric combinations explicitly")."""

    case_id: UUID
    scores: dict[str, float] = Field(default_factory=dict)
    skipped_metrics: dict[str, str] = Field(default_factory=dict)
    token_usage: dict[str, int] | None = None
    estimated_cost: float | None = None


class RagasMetricResult(DomainModel):
    """Run-level summary of one RAGAS metric across every sample it was
    computed for."""

    metric_name: str
    mean_score: float | None = None
    sample_count: int = 0
    skipped_count: int = 0
    skip_reason: str | None = None


class QualityGateDecision(DomainModel):
    """The release-gate verdict for one run: deterministic hard-gate
    failures always win over averaged RAGAS scores (spec section 13)."""

    overall_status: QualityGateStatus
    hard_gate_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvaluationRunSummary(DomainModel):
    """The report returned from `QualityEvaluationService.execute_run`."""

    run_id: UUID
    status: QualityEvaluationRunStatus
    mode: QualityEvaluationMode
    case_count: int
    completed_case_count: int
    failed_case_count: int
    skipped_case_count: int
    gate_decision: QualityGateDecision
    deterministic_metric_summary: dict[str, float] = Field(default_factory=dict)
    ragas_metric_summary: dict[str, float] = Field(default_factory=dict)
    skipped_ragas_metrics: dict[str, str] = Field(default_factory=dict)


class MetricComparison(DomainModel):
    metric_name: str
    baseline_value: float | None = None
    candidate_value: float | None = None
    result: EvaluationComparisonResult
    detail: str | None = None


class EvaluationRegressionReport(DomainModel):
    """The report returned from `QualityEvaluationService.compare_with_baseline`."""

    run_id: UUID
    baseline_id: UUID
    comparable: bool
    overall_result: EvaluationComparisonResult
    metric_comparisons: list[MetricComparison] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LearningQualityReport(DomainModel):
    """A privacy-safe summary of one or more `LearningQualityAggregate`
    rows - never exposed below the configured minimum cohort size."""

    metric_type: LearningOutcomeMetricType
    cohort_key: str
    cohort_size: int
    value: float
    sample_count: int
    calculation_version: str
    is_observational: bool = True
