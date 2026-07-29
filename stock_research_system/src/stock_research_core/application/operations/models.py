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

from stock_research_core.application.live_research.provider_models import (
    DiscoverySearchRequest,
    SecCompanyFactsRequest,
    SecSubmissionsRequest,
)
from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus
from stock_research_core.domain.live_research.enums import ResearchScope
from stock_research_core.domain.live_research.hashing import normalize_query
from stock_research_core.domain.live_research.models import ResearchRequest
from stock_research_core.domain.models import DomainModel
from stock_research_core.domain.operations.enums import BackgroundJobStatus
from stock_research_core.domain.operations.models import BackgroundJob

_DEFAULT_INTERVAL = "1d"
_DEFAULT_SOURCE_NAME = "yfinance"


def _declared_max_length(model: type[DomainModel], field_name: str) -> int:
    """Reads a string field's declared `max_length` off the model that owns
    it, so a boundary check elsewhere reuses the canonical declaration
    instead of hard-coding a second copy of the number that could later
    drift from it."""
    for constraint in model.model_fields[field_name].metadata:
        max_length = getattr(constraint, "max_length", None)
        if max_length is not None:
            return int(max_length)
    raise RuntimeError(f"{model.__name__}.{field_name} declares no max_length")


#: `ResearchRequest.normalized_query`'s own declared bound (2000). Every
#: `LIVE_RESEARCH_RUN_EXECUTION` job eventually persists a
#: `ResearchRequest` whose `normalized_query` is `normalize_query(
#: original_question)`, so this is a domain boundary that applies to
#: *every* scope - see `LiveResearchRunExecutionParameters.
#: _validate_normalized_query_length`.
_NORMALIZED_QUERY_MAX_LENGTH = _declared_max_length(ResearchRequest, "normalized_query")


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
    #: invoke unreviewed behavior. The Coach-research reconciliation
    #: sweep (spec G2D2 section 13) is deliberately *not* routed through
    #: this job type - `BackgroundJobService.reconcile_waiting_coach_runs`
    #: is invoked directly (by the admin CLI today), since routing it
    #: through SYSTEM_MAINTENANCE would require `SystemMaintenanceJobHandler`
    #: to depend on the very `BackgroundJobService` instance that
    #: constructs it via the job registry - a circular composition
    #: dependency this phase avoids rather than works around.
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


class LiveResearchRunExecutionParameters(JobParameters):
    """Phase G2B: parameters for `LIVE_RESEARCH_RUN_EXECUTION`.

    Deliberately carries no requester identity, idempotency key, or
    provider credential/configuration - those are either sourced from the
    trusted `JobExecutionContext` (identity, idempotency key) at
    execution time, or reused unchanged from G2A1's own
    `PerplexitySearchSettings`/`SecEdgarSettings` (provider configuration),
    never re-declared here where an untrusted caller-supplied request
    body could set them.
    """

    original_question: str = Field(min_length=3, max_length=5000)
    scope: ResearchScope
    subject_security_id: UUID | None = None
    subject_raw_text: str | None = Field(default=None, max_length=250)
    sec_cik: str | None = None
    sec_concepts: list[str] | None = None

    @field_validator("original_question")
    @classmethod
    def _strip_original_question(cls, value: str) -> str:
        # G2B Correction V4, item 3: a whitespace-only question is
        # already rejected here without any extra check of our own -
        # `DomainModel.model_config` sets `str_strip_whitespace=True`, so
        # Pydantic strips the raw value *before* checking this field's
        # `Field(min_length=3, ...)` constraint, and a whitespace-only
        # string strips down to "" (0 characters). This `.strip()` call
        # is therefore idempotent with Pydantic's own pre-strip; kept so
        # the field's value is explicitly normalized here regardless of
        # base-class configuration.
        return value.strip()

    @field_validator("subject_raw_text")
    @classmethod
    def _normalize_subject_raw_text(cls, value: str | None) -> str | None:
        # G2B Correction V4, item 2: a blank/whitespace-only
        # subject_raw_text is normalized to None *before*
        # `_validate_subject` runs, so that validator can rely on
        # `is not None` alone rather than a second `bool(...)`/truthiness
        # check duplicating this same normalization.
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _validate_subject(self) -> LiveResearchRunExecutionParameters:
        # G2B Correction V4, item 1: GENERAL_QUESTION must carry neither
        # subject field at all - it is the one accepted scope with no
        # subject concept. Every other accepted scope (MARKET_DATA_SNAPSHOT
        # is rejected outright by `_reject_market_data_snapshot`) requires
        # exactly one of the two subject fields.
        has_security = self.subject_security_id is not None
        has_raw_text = self.subject_raw_text is not None
        if self.scope == ResearchScope.GENERAL_QUESTION:
            if has_security:
                raise ValueError("subject_security_id must not be set when scope is GENERAL_QUESTION")
            if has_raw_text:
                raise ValueError("subject_raw_text must not be set when scope is GENERAL_QUESTION")
            return self
        if has_security and has_raw_text:
            raise ValueError("subject_security_id and subject_raw_text must not both be set")
        if not has_security and not has_raw_text:
            raise ValueError("exactly one of subject_security_id or subject_raw_text is required")
        return self

    @model_validator(mode="after")
    def _reject_market_data_snapshot(self) -> LiveResearchRunExecutionParameters:
        if self.scope == ResearchScope.MARKET_DATA_SNAPSHOT:
            raise ValueError(
                "MARKET_DATA_SNAPSHOT is not supported by LIVE_RESEARCH_RUN_EXECUTION - no provider port exists for it"
            )
        return self

    @model_validator(mode="after")
    def _validate_sec_fields(self) -> LiveResearchRunExecutionParameters:
        # Reuses G2A1's own `SecSubmissionsRequest`/`SecCompanyFactsRequest`
        # as the canonical CIK/concepts validation-and-normalization
        # boundary - never a second, weaker, duplicated check here.
        #
        # Writes the normalized values back via `object.__setattr__`
        # rather than a plain `self.sec_cik = ...`: `DomainModel.model_config`
        # sets `validate_assignment=True`, so a normal attribute assignment
        # here would re-run every model_validator (including this one) on
        # assignment, recursing indefinitely. `object.__setattr__` stores
        # the value directly without re-triggering validation - safe here
        # because the value being stored was already validated by the
        # canonical G2A1 model construction immediately above it.
        if self.scope == ResearchScope.FINANCIAL_FILING_REVIEW:
            if self.sec_cik is None:
                raise ValueError("sec_cik is required when scope is FINANCIAL_FILING_REVIEW")
            if self.sec_concepts is not None:
                raise ValueError("sec_concepts must not be set when scope is FINANCIAL_FILING_REVIEW")
            normalized_cik = SecSubmissionsRequest(cik=self.sec_cik).cik
            object.__setattr__(self, "sec_cik", normalized_cik)
        elif self.scope == ResearchScope.COMPANY_OVERVIEW:
            if self.sec_cik is None:
                raise ValueError("sec_cik is required when scope is COMPANY_OVERVIEW")
            if not self.sec_concepts:
                raise ValueError("sec_concepts is required and must be a non-empty list when scope is COMPANY_OVERVIEW")
            canonical = SecCompanyFactsRequest(cik=self.sec_cik, concepts=self.sec_concepts)
            object.__setattr__(self, "sec_cik", canonical.cik)
            object.__setattr__(self, "sec_concepts", canonical.concepts)
        elif self.sec_cik is not None or self.sec_concepts is not None:
            raise ValueError(f"sec_cik and sec_concepts must not be set when scope is {self.scope.value}")
        return self

    @model_validator(mode="after")
    def _validate_normalized_query_length(self) -> LiveResearchRunExecutionParameters:
        # G2B Correction V3, item 4: every scope - FINANCIAL_FILING_REVIEW
        # included - eventually persists a `ResearchRequest` whose
        # `normalized_query` is `normalize_query(original_question)`, and
        # that column/field is bounded at 2000 characters. So this is a
        # domain boundary no scope is exempt from, independent of whether
        # the scope also calls discovery search. Checked here, at
        # job-parameter-parsing time, so an over-long question is
        # rejected before enqueue rather than surfacing as a
        # `submit_request` ValidationError after a job row already exists.
        #
        # `normalize_query` (the exact function the service itself uses)
        # lowercases and collapses whitespace runs, so the normalized
        # length can be *shorter* than the transmitted question - which
        # is why this check and the discovery-query check below are
        # genuinely two different boundaries, not one duplicated bound.
        normalized = normalize_query(self.original_question)
        if len(normalized) > _NORMALIZED_QUERY_MAX_LENGTH:
            raise ValueError(
                "normalized research question exceeds ResearchRequest.normalized_query's "
                f"{_NORMALIZED_QUERY_MAX_LENGTH}-character boundary (normalized length {len(normalized)})"
            )
        return self

    @model_validator(mode="after")
    def _validate_discovery_question_length(self) -> LiveResearchRunExecutionParameters:
        # G2B Correction V2, item 4 (kept unchanged, and still needed
        # alongside `_validate_normalized_query_length` above): the query
        # actually transmitted to the discovery provider is the
        # *un-normalized* `original_question`, which has its own
        # 2000-character boundary on `DiscoverySearchRequest.query`. A
        # question can therefore pass the normalized boundary and still
        # be too long to transmit. Reuses DiscoverySearchRequest's own
        # canonical validation - never a second, weaker, duplicated
        # bound - for the scopes that actually call discovery search.
        # MARKET_DATA_SNAPSHOT is excluded defensively too, even though
        # `_reject_market_data_snapshot` already rejects it, so this
        # validator's correctness never depends on model_validator
        # execution order.
        if self.scope not in (ResearchScope.FINANCIAL_FILING_REVIEW, ResearchScope.MARKET_DATA_SNAPSHOT):
            DiscoverySearchRequest(query=self.original_question)
        return self


class CoachResearchResumeParameters(JobParameters):
    """Internal-only (spec G2D2 section 12) parameters for
    `COACH_RESEARCH_RESUME`. Carries only the three identifiers the
    handler needs to look up and re-verify everything else from
    PostgreSQL (section 16) - never a resume decision, never evidence,
    never any value sourced from a resume payload or model output.
    Only `SYSTEM` may trigger this job type (see `job_registry.py`)."""

    coach_run_id: UUID
    coach_thread_id: UUID
    research_job_id: UUID


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
