"""Domain models for the FinQuest background-jobs and n8n-integration
engine (Phase 11: production operations).

This module has no knowledge of any infrastructure (databases, queues,
Celery, Redis, HTTP frameworks, orchestration engines, etc.) - the same
rule every other `domain/*` package follows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from stock_research_core.domain.models import DomainModel, utc_now
from stock_research_core.domain.operations.enums import (
    TERMINAL_JOB_STATUSES,
    BackgroundJobPriority,
    BackgroundJobStatus,
    BackgroundJobType,
    IntegrationClientStatus,
    IntegrationRequestStatus,
    JobAttemptStatus,
    JobEventType,
    JobTriggerSource,
)
from stock_research_core.domain.operations.sanitization import (
    contains_credential_leak,
    contains_traceback,
    find_sensitive_keys,
)


def _reject_sensitive_mapping(data: dict[str, Any] | None, *, field_name: str) -> None:
    if data is None:
        return
    sensitive_paths = find_sensitive_keys(data)
    if sensitive_paths:
        raise ValueError(
            f"{field_name} must not contain sensitive fields (found: {', '.join(sensitive_paths)})"
        )
    if contains_traceback(data):
        raise ValueError(f"{field_name} must not contain a raw traceback")


class BackgroundJob(DomainModel):
    """A durable, PostgreSQL-backed record of one background job.

    PostgreSQL is the source of truth for job state - this model is
    never reconstructed from Celery/Redis state, only from a stored row.
    """

    job_id: UUID = Field(default_factory=uuid4)
    job_type: BackgroundJobType
    status: BackgroundJobStatus = BackgroundJobStatus.PENDING
    priority: BackgroundJobPriority = BackgroundJobPriority.NORMAL

    trigger_source: JobTriggerSource
    requested_by_account_id: UUID | None = None
    requested_by_integration_id: UUID | None = None

    idempotency_key: str = Field(min_length=1, max_length=200)
    resource_key: str | None = Field(default=None, max_length=300)

    parameters: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] | None = None

    progress_current: int = Field(default=0, ge=0)
    progress_total: int | None = Field(default=None, gt=0)
    progress_message: str | None = Field(default=None, max_length=500)

    attempt_count: int = Field(default=0, ge=0)
    maximum_attempts: int = Field(default=3, ge=1, le=20)

    queue_name: str = Field(min_length=1, max_length=100)
    task_name: str = Field(min_length=1, max_length=200)
    task_id: str | None = None

    available_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None

    job_version: str = Field(default="1", min_length=1, max_length=20)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("parameters")
    @classmethod
    def _validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="parameters")
        return value

    @field_validator("result_summary")
    @classmethod
    def _validate_result_summary(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        _reject_sensitive_mapping(value, field_name="result_summary")
        return value

    @model_validator(mode="after")
    def _validate_progress(self) -> BackgroundJob:
        if self.progress_total is not None and self.progress_current > self.progress_total:
            raise ValueError("progress_current cannot exceed progress_total")
        return self

    @model_validator(mode="after")
    def _validate_lifecycle_timestamps(self) -> BackgroundJob:
        if self.status == BackgroundJobStatus.RUNNING and self.started_at is None:
            raise ValueError("a RUNNING job requires started_at")
        if self.status in TERMINAL_JOB_STATUSES:
            if self.status == BackgroundJobStatus.CANCELLED:
                if self.completed_at is None and self.cancelled_at is None:
                    raise ValueError("a CANCELLED job requires completed_at or cancelled_at")
            elif self.completed_at is None:
                raise ValueError(f"a {self.status.value} job requires completed_at")
        return self

    @model_validator(mode="after")
    def _validate_succeeded_result(self) -> BackgroundJob:
        if self.status == BackgroundJobStatus.SUCCEEDED and self.result_summary is None:
            raise ValueError("a SUCCEEDED job requires a result_summary")
        return self


class BackgroundJobAttempt(DomainModel):
    """One worker's attempt at executing a `BackgroundJob`."""

    attempt_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    attempt_number: int = Field(gt=0)
    status: JobAttemptStatus = JobAttemptStatus.STARTED

    worker_name: str | None = Field(default=None, max_length=200)
    celery_task_id: str | None = Field(default=None, max_length=200)

    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    error_type: str | None = Field(default=None, max_length=200)
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=2000)
    retry_delay_seconds: int | None = Field(default=None, ge=0)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("error_message")
    @classmethod
    def _validate_error_message(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if contains_traceback(value):
            raise ValueError("error_message must not contain a raw traceback")
        if contains_credential_leak(value):
            raise ValueError("error_message must not contain credential-shaped content")
        return value

    @model_validator(mode="after")
    def _validate_terminal_completion(self) -> BackgroundJobAttempt:
        terminal = {
            JobAttemptStatus.SUCCEEDED,
            JobAttemptStatus.FAILED,
            JobAttemptStatus.RETRYABLE_FAILURE,
            JobAttemptStatus.CANCELLED,
        }
        if self.status in terminal and self.completed_at is None:
            raise ValueError(f"a {self.status.value} attempt requires completed_at")
        return self

    @model_validator(mode="after")
    def _validate_failure_fields(self) -> BackgroundJobAttempt:
        if self.status in {JobAttemptStatus.FAILED, JobAttemptStatus.RETRYABLE_FAILURE}:
            if not self.error_type or not self.error_message:
                raise ValueError(
                    f"a {self.status.value} attempt requires sanitized error_type and error_message"
                )
        return self


class BackgroundJobEvent(DomainModel):
    """An immutable audit event for a `BackgroundJob`."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        protected_namespaces=(),
        frozen=True,
    )

    event_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    attempt_id: UUID | None = None
    event_type: JobEventType

    message: str = Field(min_length=1, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    correlation_id: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        try:
            value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("message must be plain English (ASCII) text") from exc
        if contains_traceback(value) or contains_credential_leak(value):
            raise ValueError("message must not contain a traceback or credential-shaped content")
        return value

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="metadata")
        return value


class IntegrationClient(DomainModel):
    """An n8n (or other automation) client authorized to trigger jobs
    via API key. The raw API key is never stored or represented here -
    only a secure hash."""

    integration_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    key_id: str = Field(min_length=1, max_length=64)
    api_key_hash: str = Field(min_length=32, max_length=128)

    status: IntegrationClientStatus = IntegrationClientStatus.ACTIVE
    allowed_job_types: list[BackgroundJobType] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_used_at: datetime | None = None

    @field_validator("allowed_job_types")
    @classmethod
    def _validate_unique_job_types(cls, value: list[BackgroundJobType]) -> list[BackgroundJobType]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_job_types must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _validate_active_requires_job_types(self) -> IntegrationClient:
        if self.status == IntegrationClientStatus.ACTIVE and not self.allowed_job_types:
            raise ValueError("an ACTIVE integration client requires at least one allowed job type")
        return self


class IntegrationRequest(DomainModel):
    """Replay-protection record for one inbound n8n job-trigger request."""

    request_id: UUID = Field(default_factory=uuid4)
    integration_id: UUID
    external_request_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)

    job_id: UUID | None = None
    status: IntegrationRequestStatus = IntegrationRequestStatus.ACCEPTED

    request_hash: str = Field(min_length=64, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=128)

    received_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @field_validator("request_hash")
    @classmethod
    def _validate_request_hash(cls, value: str) -> str:
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("request_hash must be a lowercase 64-character hex SHA-256 digest")
        return value
