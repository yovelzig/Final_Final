"""Request/response DTOs for `/api/v1/operations` (admin-protected
background-job control plane)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.domain.operations.enums import (
    BackgroundJobPriority,
    BackgroundJobStatus,
    BackgroundJobType,
    JobAttemptStatus,
    JobEventType,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import BackgroundJob, BackgroundJobAttempt, BackgroundJobEvent


class CreateJobRequest(ApiSchema):
    job_type: BackgroundJobType
    parameters: dict[str, Any] = Field(default_factory=dict)
    priority: BackgroundJobPriority = BackgroundJobPriority.NORMAL
    idempotency_key: str = Field(min_length=1, max_length=200)
    available_at: datetime | None = None


class BackgroundJobResponse(ApiSchema):
    job_id: UUID
    job_type: BackgroundJobType
    status: BackgroundJobStatus
    priority: BackgroundJobPriority
    trigger_source: JobTriggerSource

    progress_current: int
    progress_total: int | None
    progress_message: str | None

    attempt_count: int
    maximum_attempts: int

    queue_name: str
    task_id: str | None

    available_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None

    result_summary: dict[str, Any] | None

    job_version: str
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_domain(job: BackgroundJob) -> BackgroundJobResponse:
        return BackgroundJobResponse(
            job_id=job.job_id, job_type=job.job_type, status=job.status, priority=job.priority,
            trigger_source=job.trigger_source, progress_current=job.progress_current,
            progress_total=job.progress_total, progress_message=job.progress_message,
            attempt_count=job.attempt_count, maximum_attempts=job.maximum_attempts,
            queue_name=job.queue_name, task_id=job.task_id, available_at=job.available_at,
            started_at=job.started_at, completed_at=job.completed_at, cancelled_at=job.cancelled_at,
            result_summary=job.result_summary, job_version=job.job_version,
            created_at=job.created_at, updated_at=job.updated_at,
        )


class JobAttemptResponse(ApiSchema):
    attempt_id: UUID
    attempt_number: int
    status: JobAttemptStatus
    worker_name: str | None
    started_at: datetime
    completed_at: datetime | None
    error_type: str | None
    error_code: str | None
    error_message: str | None
    retry_delay_seconds: int | None

    @staticmethod
    def from_domain(attempt: BackgroundJobAttempt) -> JobAttemptResponse:
        return JobAttemptResponse(
            attempt_id=attempt.attempt_id, attempt_number=attempt.attempt_number, status=attempt.status,
            worker_name=attempt.worker_name, started_at=attempt.started_at, completed_at=attempt.completed_at,
            error_type=attempt.error_type, error_code=attempt.error_code, error_message=attempt.error_message,
            retry_delay_seconds=attempt.retry_delay_seconds,
        )


class JobEventResponse(ApiSchema):
    event_id: UUID
    event_type: JobEventType
    message: str
    correlation_id: str | None
    created_at: datetime

    @staticmethod
    def from_domain(event: BackgroundJobEvent) -> JobEventResponse:
        return JobEventResponse(
            event_id=event.event_id, event_type=event.event_type, message=event.message,
            correlation_id=event.correlation_id, created_at=event.created_at,
        )


class CreateJobResponse(ApiSchema):
    job: BackgroundJobResponse
    created: bool
    duplicate_of_job_id: UUID | None = None


class JobDetailResponse(ApiSchema):
    job: BackgroundJobResponse
    attempts: list[JobAttemptResponse] = Field(default_factory=list)
    events: list[JobEventResponse] = Field(default_factory=list)


class JobListResponse(ApiSchema):
    items: list[BackgroundJobResponse]
    limit: int
    offset: int
    total: int


class MetricsSummaryResponse(ApiSchema):
    jobs_by_status: dict[str, int]
    jobs_created_last_24h: int
    jobs_failed_last_24h: int
