"""Domain models for the FinQuest quality-evaluation platform (Phase 13).

This module has no knowledge of any infrastructure (databases, RAGAS,
queues, HTTP frameworks, etc.) - the same rule every other `domain/*`
package follows. These are the durable, auditable record of *what was
evaluated and what happened* - never the evaluation logic itself (see
`application.quality_evaluation`) and never a RAGAS type (see
`infrastructure.quality_evaluation.ragas_adapter`).
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from stock_research_core.domain.ai_tutor.enums import TutorContextType, TutorRequestCategory
from stock_research_core.domain.learning_orchestrator.enums import (
    LearningActionType,
    LearningIntent,
    LearningOrchestratorRoute,
)
from stock_research_core.domain.models import DomainModel, utc_now
from stock_research_core.domain.operations.sanitization import (
    contains_credential_leak,
    contains_traceback,
    find_sensitive_keys,
)
from stock_research_core.domain.quality_evaluation.enums import (
    EvaluationCaseContextType,
    LearningOutcomeMetricType,
    QualityEvaluationCaseStatus,
    QualityEvaluationMode,
    QualityEvaluationRunStatus,
    QualityEvaluationSuiteType,
    QualityGateStatus,
    QualityMetricType,
    TERMINAL_QUALITY_EVALUATION_RUN_STATUSES,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UPPER_SNAKE_CASE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _validate_sha256(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a lowercase hexadecimal SHA-256 digest")
    return normalized


def _validate_unique(values: list[Any], *, field_name: str) -> list[Any]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


def _reject_sensitive_mapping(data: dict[str, Any] | None, *, field_name: str) -> None:
    if data is None:
        return
    sensitive_paths = find_sensitive_keys(data)
    if sensitive_paths:
        raise ValueError(f"{field_name} must not contain sensitive fields (found: {', '.join(sensitive_paths)})")
    if contains_traceback(data):
        raise ValueError(f"{field_name} must not contain a raw traceback")


def _reject_secret_text(value: str, *, field_name: str) -> str:
    if contains_traceback(value):
        raise ValueError(f"{field_name} must not contain a raw traceback")
    if contains_credential_leak(value):
        raise ValueError(f"{field_name} must not contain credential-shaped content")
    return value


class QualityEvaluationSuite(DomainModel):
    """A versioned, immutable-once-approved collection of evaluation
    cases. Only an `APPROVED` suite version may back a production
    (release-gate) evaluation run - see spec section 10's review rules."""

    suite_id: UUID = Field(default_factory=uuid4)
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    suite_type: QualityEvaluationSuiteType
    status: QualityEvaluationCaseStatus = QualityEvaluationCaseStatus.DRAFT
    version: str = Field(min_length=1, max_length=50)
    language: str = Field(default="en", min_length=2, max_length=10)
    case_count: int = Field(ge=0)
    dataset_hash: str

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not _UPPER_SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("code must be UPPER_SNAKE_CASE")
        return value

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("dataset_hash")
    @classmethod
    def _validate_dataset_hash(cls, value: str) -> str:
        return _validate_sha256(value, field_name="dataset_hash")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _reject_secret_text(value, field_name="description")

    @property
    def is_production_eligible(self) -> bool:
        """Only an APPROVED suite may run in a production evaluation
        (spec section 8.1). Runs against DRAFT/REVIEWED/ARCHIVED suites
        are still permitted for authoring/review, just never for a
        release-gate decision - the service layer enforces which callers
        may skip this check."""
        return self.status == QualityEvaluationCaseStatus.APPROVED


class QualityEvaluationCase(DomainModel):
    """One curated (or, if generated, still-`DRAFT`-only) evaluation
    case. `reference_document_ids`/`reference_chunk_ids` are optional and
    best-effort - see the Phase 13 plan's dataset-relevance note: the
    knowledge base's document ids are content-hash-derived and therefore
    not stable to hand-author, so `required_concepts`/forbidden-phrase
    checks are the primary, portable ground truth."""

    case_id: UUID = Field(default_factory=uuid4)
    suite_id: UUID
    external_case_id: str = Field(min_length=1, max_length=200)
    status: QualityEvaluationCaseStatus = QualityEvaluationCaseStatus.DRAFT

    context_type: EvaluationCaseContextType
    user_input: str = Field(min_length=1, max_length=4000)

    reference_answer: str | None = Field(default=None, max_length=8000)
    reference_contexts: list[str] = Field(default_factory=list)
    reference_document_ids: list[UUID] = Field(default_factory=list)
    reference_chunk_ids: list[UUID] = Field(default_factory=list)
    expected_skill_ids: list[UUID] = Field(default_factory=list)

    expected_guardrail_category: TutorRequestCategory | None = None
    expected_refusal: bool = False
    expected_fallback: bool = False
    expected_intent: LearningIntent | None = None
    expected_route: LearningOrchestratorRoute | None = None
    expected_action_type: LearningActionType | None = None
    expected_interrupt: bool | None = None

    forbidden_phrases: list[str] = Field(default_factory=list)
    required_concepts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    case_version: str = Field(min_length=1, max_length=50)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("reference_document_ids")
    @classmethod
    def _validate_unique_reference_documents(cls, value: list[UUID]) -> list[UUID]:
        return _validate_unique(value, field_name="reference_document_ids")

    @field_validator("reference_chunk_ids")
    @classmethod
    def _validate_unique_reference_chunks(cls, value: list[UUID]) -> list[UUID]:
        return _validate_unique(value, field_name="reference_chunk_ids")

    @field_validator("expected_skill_ids")
    @classmethod
    def _validate_unique_skills(cls, value: list[UUID]) -> list[UUID]:
        return _validate_unique(value, field_name="expected_skill_ids")

    @field_validator("forbidden_phrases")
    @classmethod
    def _validate_forbidden_phrases(cls, value: list[str]) -> list[str]:
        normalized = [phrase.strip().lower() for phrase in value if phrase.strip()]
        return _validate_unique(normalized, field_name="forbidden_phrases")

    @field_validator("required_concepts")
    @classmethod
    def _validate_required_concepts(cls, value: list[str]) -> list[str]:
        normalized = [concept.strip().lower() for concept in value if concept.strip()]
        return _validate_unique(normalized, field_name="required_concepts")

    @field_validator("user_input", "reference_answer")
    @classmethod
    def _validate_no_secrets_in_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _reject_secret_text(value, field_name="user_input/reference_answer")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="metadata")
        return value

    @model_validator(mode="after")
    def _validate_interrupt_requires_action_type(self) -> QualityEvaluationCase:
        if self.expected_interrupt and self.expected_action_type is None:
            raise ValueError("expected_interrupt=True requires an expected_action_type")
        return self


class QualityEvaluationRun(DomainModel):
    """One durable execution of a suite under a given evaluation mode,
    with full system/model lineage (spec section 19: what changed
    between two runs is exactly what these fields answer)."""

    run_id: UUID = Field(default_factory=uuid4)
    suite_id: UUID
    status: QualityEvaluationRunStatus = QualityEvaluationRunStatus.CREATED
    mode: QualityEvaluationMode

    requested_by_account_id: UUID | None = None
    background_job_id: UUID | None = None

    system_version: str = Field(min_length=1, max_length=100)
    git_commit: str | None = Field(default=None, max_length=64)

    retrieval_policy_version: str = Field(min_length=1, max_length=50)
    embedding_model: str = Field(min_length=1, max_length=100)
    embedding_version: str = Field(min_length=1, max_length=50)
    tutor_policy_version: str = Field(min_length=1, max_length=50)
    prompt_version: str = Field(min_length=1, max_length=50)
    guardrail_version: str = Field(min_length=1, max_length=50)
    graph_version: str | None = Field(default=None, max_length=50)

    evaluator_provider: str | None = Field(default=None, max_length=100)
    evaluator_model: str | None = Field(default=None, max_length=100)
    ragas_version: str | None = Field(default=None, max_length=50)

    case_count: int = Field(default=0, ge=0)
    completed_case_count: int = Field(default=0, ge=0)
    failed_case_count: int = Field(default=0, ge=0)
    skipped_case_count: int = Field(default=0, ge=0)

    started_at: datetime | None = None
    completed_at: datetime | None = None

    dataset_hash: str
    configuration_hash: str

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("dataset_hash", "configuration_hash")
    @classmethod
    def _validate_hashes(cls, value: str) -> str:
        return _validate_sha256(value, field_name="dataset_hash/configuration_hash")

    @model_validator(mode="after")
    def _validate_case_counts(self) -> QualityEvaluationRun:
        consumed = self.completed_case_count + self.failed_case_count + self.skipped_case_count
        if consumed > self.case_count:
            raise ValueError("completed_case_count + failed_case_count + skipped_case_count cannot exceed case_count")
        return self

    @model_validator(mode="after")
    def _validate_lifecycle_timestamps(self) -> QualityEvaluationRun:
        if self.status == QualityEvaluationRunStatus.RUNNING and self.started_at is None:
            raise ValueError("a RUNNING run requires started_at")
        if self.status in TERMINAL_QUALITY_EVALUATION_RUN_STATUSES and self.completed_at is None:
            raise ValueError(f"a {self.status.value} run requires completed_at")
        return self

    @model_validator(mode="after")
    def _validate_evaluator_lineage(self) -> QualityEvaluationRun:
        if self.mode == QualityEvaluationMode.DETERMINISTIC:
            if self.evaluator_model is not None or self.ragas_version is not None:
                raise ValueError("a DETERMINISTIC run must not claim an evaluator_model or ragas_version")
        else:
            if not self.evaluator_provider or not self.evaluator_model or not self.ragas_version:
                raise ValueError(f"a {self.mode.value} run requires evaluator_provider, evaluator_model, and ragas_version")
        return self


class QualityEvaluationSampleResult(DomainModel):
    """The observed outcome of executing one case within one run - never
    real learner content, only curated-case-derived output (spec section
    16: evaluation is side-effect-safe and does not read/write production
    learner records through this model)."""

    sample_result_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    case_id: UUID

    status: QualityGateStatus = QualityGateStatus.NOT_EVALUATED

    generated_response: str | None = Field(default=None, max_length=8000)
    retrieved_context_ids: list[UUID] = Field(default_factory=list)
    retrieved_document_ids: list[UUID] = Field(default_factory=list)
    citation_chunk_ids: list[UUID] = Field(default_factory=list)

    observed_guardrail_category: TutorRequestCategory | None = None
    observed_intent: LearningIntent | None = None
    observed_route: LearningOrchestratorRoute | None = None
    observed_action_type: LearningActionType | None = None
    observed_interrupt: bool | None = None

    latency_ms: int = Field(default=0, ge=0)
    retrieval_latency_ms: int | None = Field(default=None, ge=0)
    generation_latency_ms: int | None = Field(default=None, ge=0)

    input_token_count: int | None = Field(default=None, ge=0)
    output_token_count: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)

    failure_code: str | None = Field(default=None, max_length=100)
    failure_message: str | None = Field(default=None, max_length=1000)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_response")
    @classmethod
    def _validate_generated_response(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _reject_secret_text(value, field_name="generated_response")

    @field_validator("failure_message")
    @classmethod
    def _validate_failure_message(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _reject_secret_text(value, field_name="failure_message")

    @field_validator("estimated_cost")
    @classmethod
    def _validate_finite_cost(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("estimated_cost must be a finite number")
        return value


class QualityMetricResult(DomainModel):
    """One metric's score for one run (aggregate) or one run+sample
    (per-case). Numeric scores are metric-contract-scaled - not assumed
    0-1 - and `threshold` (when present) always shares that scale."""

    metric_result_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sample_result_id: UUID | None = None

    metric_name: str = Field(min_length=1, max_length=100)
    metric_type: QualityMetricType
    metric_version: str = Field(min_length=1, max_length=50)

    score: float | None = None
    passed: bool | None = None
    threshold: float | None = None

    details: dict[str, Any] = Field(default_factory=dict)
    evaluator_provider: str | None = Field(default=None, max_length=100)
    evaluator_model: str | None = Field(default=None, max_length=100)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("score", "threshold")
    @classmethod
    def _validate_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("score/threshold must be finite numbers")
        return value

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="details")
        return value

    @model_validator(mode="after")
    def _validate_ragas_lineage(self) -> QualityMetricResult:
        if self.metric_type == QualityMetricType.RAGAS and not self.evaluator_model:
            raise ValueError("a RAGAS metric result requires evaluator_model")
        if self.metric_type in (QualityMetricType.DETERMINISTIC, QualityMetricType.SAFETY_GATE):
            if self.evaluator_model is not None:
                raise ValueError(f"a {self.metric_type.value} metric result must not claim an evaluator_model")
        return self


class QualityEvaluationBaseline(DomainModel):
    """An admin-approved reference point for regression comparison.
    Never created or approved automatically - see spec section 17's
    `approve_baseline` (ADMIN-only) and section 18's regression rules."""

    baseline_id: UUID = Field(default_factory=uuid4)
    suite_id: UUID
    run_id: UUID
    name: str = Field(min_length=1, max_length=200)
    approved: bool = False
    approved_by_account_id: UUID | None = None

    metric_summary: dict[str, float] = Field(default_factory=dict)
    safety_gate_summary: dict[str, bool] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utc_now)
    approved_at: datetime | None = None

    @field_validator("metric_summary")
    @classmethod
    def _validate_metric_summary_finite(cls, value: dict[str, float]) -> dict[str, float]:
        for name, score in value.items():
            if not math.isfinite(score):
                raise ValueError(f"metric_summary['{name}'] must be finite")
        return value

    @model_validator(mode="after")
    def _validate_approval(self) -> QualityEvaluationBaseline:
        if self.approved and (self.approved_by_account_id is None or self.approved_at is None):
            raise ValueError("an approved baseline requires approved_by_account_id and approved_at")
        if not self.approved and (self.approved_by_account_id is not None or self.approved_at is not None):
            raise ValueError("an unapproved baseline must not carry approval metadata")
        return self


class LearningQualityAggregate(DomainModel):
    """A descriptive (never causal, unless a controlled experiment says
    otherwise) learning-outcome aggregate over a cohort and period. Never
    carries a learner id - `cohort_key`/`filters` must stay bucket-level
    (spec section 27's privacy rules, enforced again at the repository
    and API layers)."""

    aggregate_id: UUID = Field(default_factory=uuid4)
    metric_type: LearningOutcomeMetricType

    period_start: datetime
    period_end: datetime

    cohort_key: str = Field(min_length=1, max_length=200)
    cohort_size: int = Field(ge=0)

    value: float
    sample_count: int = Field(ge=0)

    calculation_version: str = Field(min_length=1, max_length=50)
    filters: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("value")
    @classmethod
    def _validate_finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        return value

    @field_validator("filters")
    @classmethod
    def _validate_filters(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="filters")
        disallowed = {"learner_id", "account_id", "email", "user_id"}
        present = disallowed & {str(key).strip().lower() for key in value.keys()}
        if present:
            raise ValueError(f"filters must not expose learner identity fields: {sorted(present)}")
        return value

    @model_validator(mode="after")
    def _validate_period(self) -> LearningQualityAggregate:
        if self.period_start >= self.period_end:
            raise ValueError("period_start must precede period_end")
        return self
