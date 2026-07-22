"""Application-level Protocol contracts for the Phase 11 background-jobs
and n8n-integration engine.

Pure `Protocol` definitions describing what the operations persistence,
queue, locking, metrics, and tracing layers do, not how. No Celery,
Redis, SQLAlchemy, or Prometheus import is allowed here; concrete
implementations live under `stock_research_core.infrastructure.operations`
and `stock_research_core.infrastructure.database`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Protocol
from uuid import UUID

from stock_research_core.domain.operations.enums import (
    BackgroundJobPriority,
    BackgroundJobStatus,
    BackgroundJobType,
    IntegrationClientStatus,
    IntegrationRequestStatus,
    JobAttemptStatus,
    JobEventType,
)
from stock_research_core.domain.operations.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundJobEvent,
    IntegrationClient,
    IntegrationRequest,
)


class JobListFilter(Protocol):
    job_type: BackgroundJobType | None
    status: BackgroundJobStatus | None
    trigger_source: str | None
    created_after: datetime | None
    created_before: datetime | None


class BackgroundJobRepositoryPort(Protocol):
    """Persists and queries `BackgroundJob` rows. PostgreSQL is the sole
    source of truth for job state - no method here reads Celery/Redis."""

    async def create(self, job: BackgroundJob) -> BackgroundJob: ...

    async def get_by_id(self, job_id: UUID) -> BackgroundJob | None: ...

    async def get_for_update(self, job_id: UUID) -> BackgroundJob | None:
        """Load a job row with a `SELECT ... FOR UPDATE`-equivalent lock,
        so concurrent workers delivering the same job cannot both execute it."""
        ...

    async def get_by_idempotency_key(
        self,
        *,
        job_type: BackgroundJobType,
        trigger_source: str,
        requested_by_account_id: UUID | None,
        requested_by_integration_id: UUID | None,
        idempotency_key: str,
    ) -> BackgroundJob | None:
        """Canonical idempotency scope: `(job_type, trigger_source, requester
        identity, idempotency_key)`, where requester identity is derived
        from `requested_by_account_id`/`requested_by_integration_id` (falling
        back to `trigger_source` itself when both are `None`, e.g. SYSTEM/
        ADMIN_CLI-triggered jobs) - see the concrete repository for the
        exact derivation, applied identically on write and on read."""
        ...

    async def mark_queued(self, job_id: UUID, *, task_id: str) -> BackgroundJob: ...

    async def mark_running(self, job_id: UUID, *, started_at: datetime) -> BackgroundJob: ...

    async def update_progress(
        self,
        job_id: UUID,
        *,
        current: int,
        total: int | None,
        message: str | None,
    ) -> BackgroundJob: ...

    async def mark_succeeded(
        self, job_id: UUID, *, completed_at: datetime, result_summary: dict[str, Any]
    ) -> BackgroundJob: ...

    async def mark_failed(
        self, job_id: UUID, *, completed_at: datetime, result_summary: dict[str, Any] | None
    ) -> BackgroundJob: ...

    async def mark_retry_scheduled(
        self, job_id: UUID, *, available_at: datetime, result_summary: dict[str, Any] | None
    ) -> BackgroundJob: ...

    async def mark_cancelled(self, job_id: UUID, *, cancelled_at: datetime) -> BackgroundJob: ...

    async def list_stale_running_job_ids(self, *, older_than: datetime, limit: int = 1000) -> list[UUID]:
        """Job IDs stuck in RUNNING with `started_at` older than `older_than`
        - used by the `SYSTEM_MAINTENANCE` job to fail jobs that a crashed
        worker never completed."""
        ...

    async def list_jobs(
        self,
        *,
        job_type: BackgroundJobType | None = None,
        status: BackgroundJobStatus | None = None,
        trigger_source: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        requested_by_integration_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BackgroundJob]: ...

    async def count_jobs(
        self,
        *,
        job_type: BackgroundJobType | None = None,
        status: BackgroundJobStatus | None = None,
        trigger_source: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        requested_by_integration_id: UUID | None = None,
    ) -> int: ...


class BackgroundJobAttemptRepositoryPort(Protocol):
    async def create(self, attempt: BackgroundJobAttempt) -> BackgroundJobAttempt: ...

    async def complete(
        self,
        attempt_id: UUID,
        *,
        status: JobAttemptStatus,
        completed_at: datetime,
        error_type: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retry_delay_seconds: int | None = None,
    ) -> BackgroundJobAttempt: ...

    async def list_for_job(self, job_id: UUID) -> list[BackgroundJobAttempt]: ...


class BackgroundJobEventRepositoryPort(Protocol):
    async def append(self, event: BackgroundJobEvent) -> BackgroundJobEvent: ...

    async def list_for_job(self, job_id: UUID) -> list[BackgroundJobEvent]: ...


class IntegrationClientRepositoryPort(Protocol):
    async def create(self, client: IntegrationClient) -> IntegrationClient: ...

    async def get_by_key_id(self, key_id: str) -> IntegrationClient | None: ...

    async def get_by_id(self, integration_id: UUID) -> IntegrationClient | None: ...

    async def update_last_used(self, integration_id: UUID, *, last_used_at: datetime) -> IntegrationClient: ...

    async def set_status(
        self, integration_id: UUID, *, status: IntegrationClientStatus
    ) -> IntegrationClient: ...

    async def list_clients(self) -> list[IntegrationClient]: ...


class IntegrationRequestRepositoryPort(Protocol):
    async def create(self, request: IntegrationRequest) -> IntegrationRequest: ...

    async def get_by_external_request_id(
        self, *, integration_id: UUID, external_request_id: str
    ) -> IntegrationRequest | None: ...

    async def mark_completed(
        self, request_id: UUID, *, job_id: UUID, completed_at: datetime
    ) -> IntegrationRequest: ...

    async def mark_failed(self, request_id: UUID, *, completed_at: datetime) -> IntegrationRequest: ...


class JobQueuePort(Protocol):
    """Delivery mechanism for background jobs. Never the source of truth
    for job state - only responsible for causing a worker to eventually
    call `BackgroundJobService.execute_job` for a given `job_id`."""

    async def enqueue(
        self,
        *,
        job_id: UUID,
        job_type: BackgroundJobType,
        queue_name: str,
        priority: BackgroundJobPriority,
        available_at: datetime,
    ) -> str:
        """Enqueue delivery of `job_id` and return the queue's task ID."""
        ...


class DistributedLockPort(Protocol):
    """Owner-safe distributed lock. A lock acquired by one owner can only
    be extended or released by that same owner."""

    async def acquire(
        self,
        *,
        key: str,
        owner_id: str,
        ttl_seconds: int,
        wait_timeout_seconds: int,
    ) -> bool: ...

    async def extend(self, *, key: str, owner_id: str, ttl_seconds: int) -> bool: ...

    async def release(self, *, key: str, owner_id: str) -> bool: ...


class MetricsPort(Protocol):
    """Application-layer metrics contract, independent of Prometheus."""

    def increment_counter(
        self, name: str, *, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None: ...

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None: ...

    def observe_histogram(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None: ...

    def time_operation(self, name: str, *, labels: dict[str, str] | None = None) -> Any:
        """A context manager (sync or async) recording a histogram of the
        wrapped block's duration in seconds."""
        ...


class TracingPort(Protocol):
    """No-op-safe application-layer tracing contract, independent of OpenTelemetry."""

    def start_span(
        self, name: str, *, attributes: dict[str, str | int | float | bool] | None = None
    ) -> AsyncIterator[None]:
        """An async context manager for a traced block. Must be a safe
        no-op when tracing is disabled - never raises, never requires a
        collector to be reachable."""
        ...


class Clock(Protocol):
    def __call__(self) -> datetime: ...


class ProgressReporterPort(Protocol):
    """Passed to a job handler so it can report progress without knowing
    anything about how (or whether) that progress gets persisted."""

    async def report(self, *, current: int, total: int | None = None, message: str | None = None) -> None: ...


@dataclass(frozen=True)
class HandlerOutcome:
    """What a job handler returns on success. Never includes a raw
    traceback or credentials - `result_summary` is stored verbatim (after
    the domain model's own sanitization check) as the job's public,
    learner/admin-visible result."""

    result_summary: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


class JobHandlerPort(Protocol):
    """A thin orchestration object that invokes an existing FinQuest
    application service. Handlers never implement business logic
    themselves - only translate validated job parameters into calls
    against services already used elsewhere in the system."""

    async def handle(self, *, parameters: Any, progress: ProgressReporterPort) -> HandlerOutcome: ...
