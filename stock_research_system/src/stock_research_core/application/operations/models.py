"""Job-specific parameter models and application-level result models for
the Phase 11 background-jobs engine.

Every `BackgroundJob.parameters` dict is validated against exactly one
of these models (selected by `job_type` via the job registry) before a
job is ever persisted - arbitrary unvalidated JSON is never accepted.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus
from stock_research_core.domain.models import DomainModel
from stock_research_core.domain.operations.enums import BackgroundJobStatus
from stock_research_core.domain.operations.models import BackgroundJob

_DEFAULT_INTERVAL = "1d"
_DEFAULT_SOURCE_NAME = "yfinance"


class JobParameters(DomainModel):
    """Base class for all job-specific parameter models."""


# -- job-specific parameter models -----------------------------------------------


class TrackedMarketRefreshParameters(JobParameters):
    start_at: datetime | None = None
    end_at: datetime
    incremental: bool = True
    max_concurrency: int = Field(default=4, gt=0, le=32)
    source_name: str = Field(default=_DEFAULT_SOURCE_NAME, min_length=1, max_length=100)
    interval: str = Field(default=_DEFAULT_INTERVAL, min_length=1, max_length=10)


class SecurityMarketRefreshParameters(JobParameters):
    ticker: str = Field(min_length=1, max_length=20)
    start_at: datetime | None = None
    end_at: datetime
    incremental: bool = True
    source_name: str = Field(default=_DEFAULT_SOURCE_NAME, min_length=1, max_length=100)
    interval: str = Field(default=_DEFAULT_INTERVAL, min_length=1, max_length=10)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.upper()


class PortfolioValuationParameters(JobParameters):
    portfolio_id: UUID
    as_of: datetime


class PortfolioBatchValuationParameters(JobParameters):
    portfolio_ids: list[UUID] = Field(default_factory=list)
    as_of: datetime
    max_concurrency: int = Field(default=4, gt=0, le=32)
    all_active_portfolios: bool = False

    @model_validator(mode="after")
    def _validate_selection_mode(self) -> PortfolioBatchValuationParameters:
        if self.all_active_portfolios and self.portfolio_ids:
            raise ValueError(
                "portfolio_ids and all_active_portfolios cannot both be set - choose one selection mode"
            )
        if not self.all_active_portfolios and not self.portfolio_ids:
            raise ValueError("either portfolio_ids or all_active_portfolios=true must be provided")
        return self


class CurriculumKnowledgeRefreshParameters(JobParameters):
    include_lessons: bool = True
    include_exercise_explanations: bool = True
    reembed: bool = False


class LocalDocumentIngestionParameters(JobParameters):
    file_path: str = Field(min_length=1, max_length=1000)
    source_title: str = Field(min_length=1, max_length=200)
    approval_status: KnowledgeApprovalStatus = KnowledgeApprovalStatus.APPROVED
    skill_ids: list[UUID] = Field(default_factory=list)
    available_at: datetime | None = None

    def resolved_file_path(self) -> Path:
        return Path(self.file_path)


class KnowledgeReembedParameters(JobParameters):
    document_ids: list[UUID] | None = None
    embedding_model: str | None = Field(default=None, max_length=200)
    batch_size: int = Field(default=32, gt=0, le=512)


class RetrievalEvaluationParameters(JobParameters):
    evaluation_dataset: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=5, gt=0, le=50)


class KnowledgeGapSummaryParameters(JobParameters):
    minimum_occurrences: int = Field(default=2, gt=0, le=1000)
    limit: int = Field(default=50, gt=0, le=500)


class SystemMaintenanceParameters(JobParameters):
    #: The only supported action today: mark jobs stuck in RUNNING past
    #: their time limit as FAILED so they stop blocking their resource
    #: lock/idempotency scope. Kept as an explicit allow-list (never an
    #: arbitrary command string) so this job type can never be used to
    #: invoke unreviewed behavior.
    action: str = Field(default="expire_stale_running_jobs", pattern=r"^[a-z_]{1,64}$")
    stale_after_minutes: int = Field(default=60, gt=0, le=1440)

    @model_validator(mode="after")
    def _validate_action(self) -> SystemMaintenanceParameters:
        allowed = {"expire_stale_running_jobs"}
        if self.action not in allowed:
            raise ValueError(f"action must be one of {sorted(allowed)}")
        return self


class RagasQualityEvaluationParameters(JobParameters):
    suite_id: UUID
    mode: str = Field(default="DETERMINISTIC", pattern=r"^(DETERMINISTIC|RAGAS|HYBRID)$")
    baseline_id: UUID | None = None
    maximum_cases: int | None = Field(default=None, gt=0, le=10000)
    maximum_concurrency: int = Field(default=4, gt=0, le=32)


class LearningQualityAggregationParameters(JobParameters):
    period_start: datetime
    period_end: datetime
    metric_types: list[str] = Field(min_length=1)
    cohort_dimensions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_period(self) -> LearningQualityAggregationParameters:
        if self.period_start >= self.period_end:
            raise ValueError("period_start must precede period_end")
        return self

    @field_validator("cohort_dimensions")
    @classmethod
    def _validate_cohort_dimensions(cls, value: list[str]) -> list[str]:
        # A closed allow-list, never an arbitrary caller-supplied grouping
        # key - spec section 21: "only approved bounded cohort dimensions".
        allowed = {"skill_category", "difficulty_level", "cohort_start_week"}
        disallowed = set(value) - allowed
        if disallowed:
            raise ValueError(f"cohort_dimensions contains unsupported values: {sorted(disallowed)} (allowed: {sorted(allowed)})")
        return value


class QualityBaselineComparisonParameters(JobParameters):
    run_id: UUID
    baseline_id: UUID


# -- application-level result models -----------------------------------------------


class JobCreationResult(DomainModel):
    job: BackgroundJob
    created: bool
    duplicate_of_job_id: UUID | None = None


class JobExecutionResult(DomainModel):
    job_id: UUID
    status: BackgroundJobStatus
    result_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class BatchJobItemResult(DomainModel):
    item_key: str
    status: str
    summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
