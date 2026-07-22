"""`BackgroundJobService`: the sole entry point for creating and executing
background jobs.

PostgreSQL (via `unit_of_work_factory`) is the source of truth for job
state throughout - `create_job` durably persists a job *before* ever
touching the queue, and `execute_job` always reloads the canonical job
from PostgreSQL rather than trusting anything carried on the Celery
message. See the Phase 11 README section for the full state-machine
diagram.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from stock_research_core.application.exceptions import (
    BackgroundJobNotFoundError,
    InvalidJobParametersError,
    InvalidJobStateError,
    JobTypeNotAllowedError,
    LockAcquisitionError,
    StockResearchError,
)
from stock_research_core.application.operations.job_registry import BackgroundJobRegistry, JobRegistryEntry
from stock_research_core.application.operations.locking import held_lock
from stock_research_core.application.operations.models import JobCreationResult, JobExecutionResult
from stock_research_core.application.operations.ports import (
    DistributedLockPort,
    JobQueuePort,
    MetricsPort,
    ProgressReporterPort,
    TracingPort,
)
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.models import utc_now
from stock_research_core.domain.operations.enums import (
    TERMINAL_JOB_STATUSES,
    BackgroundJobPriority,
    BackgroundJobStatus,
    JobAttemptStatus,
    JobEventType,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import BackgroundJob, BackgroundJobAttempt, BackgroundJobEvent
from stock_research_core.domain.operations.sanitization import redact

Clock = Callable[[], datetime]

_LOCK_RETRY_DELAY_SECONDS = 15
_JOB_VERSION = "1"


class _NoOpMetrics:
    def increment_counter(self, name: str, *, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        pass

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        pass

    def observe_histogram(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        pass

    def time_operation(self, name: str, *, labels: dict[str, str] | None = None) -> Any:
        from contextlib import nullcontext

        return nullcontext()


class _NoOpTracing:
    def start_span(self, name: str, *, attributes: dict[str, Any] | None = None) -> Any:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _span() -> Any:
            yield

        return _span()


class _RepositoryProgressReporter(ProgressReporterPort):
    """Persists every progress update in its own short transaction, so a
    long-running handler's progress is visible to API pollers immediately -
    never buffered behind the handler's eventual commit."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWorkPort], job_id: UUID) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._job_id = job_id

    async def report(self, *, current: int, total: int | None = None, message: str | None = None) -> None:
        async with self._unit_of_work_factory() as uow:
            await uow.background_jobs.update_progress(self._job_id, current=current, total=total, message=message)
            await uow.commit()


def _sanitized_error_summary(exc: Exception, *, error_code: str) -> dict[str, Any]:
    return {"error_code": error_code, "error_type": type(exc).__name__, "error_message": str(exc)[:1000]}


class BackgroundJobService:
    """Creates and executes `BackgroundJob`s. Constructed once per process
    (API or worker) from the same `build_default_registry(...)` wiring, so
    job-type configuration never drifts between the two."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        job_registry: BackgroundJobRegistry,
        job_queue: JobQueuePort,
        lock_port: DistributedLockPort,
        clock: Clock = utc_now,
        metrics: MetricsPort | None = None,
        tracing: TracingPort | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._job_registry = job_registry
        self._job_queue = job_queue
        self._lock_port = lock_port
        self._clock = clock
        self._metrics = metrics or _NoOpMetrics()
        self._tracing = tracing or _NoOpTracing()

    # -- creation -----------------------------------------------

    async def create_job(
        self,
        *,
        job_type: Any,
        raw_parameters: dict[str, Any],
        idempotency_key: str,
        trigger_source: JobTriggerSource,
        requested_by_account_id: UUID | None = None,
        requested_by_integration_id: UUID | None = None,
        priority: BackgroundJobPriority = BackgroundJobPriority.NORMAL,
        available_at: datetime | None = None,
        correlation_id: str | None = None,
    ) -> JobCreationResult:
        entry = self._job_registry.get(job_type)
        if trigger_source not in entry.allowed_trigger_sources:
            raise JobTypeNotAllowedError(f"Job type {job_type.value} cannot be triggered from {trigger_source.value}.")

        try:
            parameters = entry.parse_parameters(raw_parameters)
        except ValidationError as exc:
            raise InvalidJobParametersError(f"Invalid parameters for job type {job_type.value}: {exc}") from exc

        resource_key = entry.resource_key_builder(parameters)
        resolved_available_at = available_at or self._clock()

        async with self._unit_of_work_factory() as uow:
            existing = await uow.background_jobs.get_by_idempotency_key(
                job_type=job_type,
                trigger_source=trigger_source.value,
                requested_by_account_id=requested_by_account_id,
                requested_by_integration_id=requested_by_integration_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return JobCreationResult(job=existing, created=False, duplicate_of_job_id=existing.job_id)

            job = BackgroundJob(
                job_type=job_type,
                status=BackgroundJobStatus.PENDING,
                priority=priority,
                trigger_source=trigger_source,
                requested_by_account_id=requested_by_account_id,
                requested_by_integration_id=requested_by_integration_id,
                idempotency_key=idempotency_key,
                resource_key=resource_key,
                parameters=parameters.model_dump(mode="json"),
                attempt_count=0,
                maximum_attempts=entry.maximum_attempts,
                queue_name=entry.queue_name,
                task_name=entry.task_name,
                available_at=resolved_available_at,
                job_version=_JOB_VERSION,
            )
            created = await uow.background_jobs.create(job)
            await uow.background_job_events.append(
                BackgroundJobEvent(
                    job_id=created.job_id,
                    event_type=JobEventType.CREATED,
                    message="Job created.",
                    correlation_id=correlation_id,
                )
            )
            await uow.commit()

        self._metrics.increment_counter(
            "finquest_jobs_created_total", labels={"job_type": job_type.value, "queue": entry.queue_name}
        )

        try:
            task_id = await self._job_queue.enqueue(
                job_id=created.job_id,
                job_type=job_type,
                queue_name=entry.queue_name,
                priority=priority,
                available_at=resolved_available_at,
            )
        except Exception as exc:  # noqa: BLE001 - queue delivery failures are infrastructure-shaped and varied
            async with self._unit_of_work_factory() as uow:
                failed = await uow.background_jobs.mark_failed(
                    created.job_id,
                    completed_at=self._clock(),
                    result_summary=_sanitized_error_summary(exc, error_code="ENQUEUE_FAILED"),
                )
                await uow.background_job_events.append(
                    BackgroundJobEvent(
                        job_id=created.job_id,
                        event_type=JobEventType.FAILED,
                        message="Enqueue failed; job preserved for administrative requeue.",
                        correlation_id=correlation_id,
                    )
                )
                await uow.commit()
            return JobCreationResult(job=failed, created=True, duplicate_of_job_id=None)

        async with self._unit_of_work_factory() as uow:
            queued = await uow.background_jobs.mark_queued(created.job_id, task_id=task_id)
            await uow.background_job_events.append(
                BackgroundJobEvent(
                    job_id=created.job_id,
                    event_type=JobEventType.QUEUED,
                    message="Job queued for delivery.",
                    correlation_id=correlation_id,
                )
            )
            await uow.commit()

        return JobCreationResult(job=queued, created=True, duplicate_of_job_id=None)

    # -- execution (called only from within a Celery worker task) -----------------------------------------------

    async def execute_job(self, *, job_id: UUID, worker_name: str, celery_task_id: str) -> JobExecutionResult:
        async with self._unit_of_work_factory() as uow:
            job = await uow.background_jobs.get_for_update(job_id)
            if job is None:
                raise BackgroundJobNotFoundError(f"No background job found with id '{job_id}'.")

            if job.status == BackgroundJobStatus.SUCCEEDED:
                await uow.commit()
                return JobExecutionResult(
                    job_id=job_id, status=job.status, result_summary=job.result_summary or {},
                    warnings=["Job already succeeded; duplicate delivery skipped."],
                )
            if job.status in (BackgroundJobStatus.CANCELLED, BackgroundJobStatus.SKIPPED, BackgroundJobStatus.RUNNING):
                await uow.commit()
                return JobExecutionResult(
                    job_id=job_id, status=job.status, result_summary={},
                    warnings=[f"Job is {job.status.value}; execution skipped (duplicate delivery is safe)."],
                )
            if job.status not in (
                BackgroundJobStatus.PENDING,
                BackgroundJobStatus.QUEUED,
                BackgroundJobStatus.RETRY_SCHEDULED,
            ):
                await uow.commit()
                raise InvalidJobStateError(f"Job {job_id} is in status {job.status.value} and cannot be executed.")

            entry = self._job_registry.get(job.job_type)
            attempt_number = job.attempt_count + 1
            started_at = self._clock()
            job = await uow.background_jobs.mark_running(job_id, started_at=started_at)
            attempt = await uow.background_job_attempts.create(
                BackgroundJobAttempt(
                    job_id=job_id,
                    attempt_number=attempt_number,
                    status=JobAttemptStatus.STARTED,
                    worker_name=worker_name,
                    celery_task_id=celery_task_id,
                    started_at=started_at,
                )
            )
            await uow.background_job_events.append(
                BackgroundJobEvent(
                    job_id=job_id,
                    attempt_id=attempt.attempt_id,
                    event_type=JobEventType.STARTED,
                    message=f"Attempt {attempt_number} started.",
                )
            )
            await uow.commit()

        parameters = entry.parse_parameters(job.parameters)
        progress = _RepositoryProgressReporter(unit_of_work_factory=self._unit_of_work_factory, job_id=job_id)
        owner_id = f"{worker_name}:{celery_task_id}"

        self._metrics.increment_counter("finquest_jobs_in_progress", labels={"job_type": job.job_type.value})
        try:
            async with self._tracing.start_span(
                "job.execute", attributes={"job_type": job.job_type.value, "attempt_number": attempt_number}
            ):
                async with held_lock(self._lock_port, key=job.resource_key, owner_id=owner_id, metrics=self._metrics):
                    with self._metrics.time_operation("finquest_job_duration_seconds", labels={"job_type": job.job_type.value}):
                        outcome = await entry.handler.handle(parameters=parameters, progress=progress)
        except LockAcquisitionError as exc:
            await self._record_lock_not_acquired(job_id=job_id, attempt=attempt)
            return await self._schedule_retry_or_fail(
                job_id=job_id, attempt=attempt, entry=entry, attempt_number=attempt_number,
                exception=exc, error_code="LOCK_NOT_ACQUIRED", delay_seconds=_LOCK_RETRY_DELAY_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - classification happens via the job type's retry policy
            decision = entry.retry_policy.classify(exc, attempt_number=attempt_number)
            return await self._schedule_retry_or_fail(
                job_id=job_id, attempt=attempt, entry=entry, attempt_number=attempt_number,
                exception=exc, error_code=decision.error_code,
                delay_seconds=decision.delay_seconds if decision.retryable else None,
            )
        finally:
            self._metrics.increment_counter("finquest_jobs_in_progress", value=-1, labels={"job_type": job.job_type.value})

        return await self._record_success(job_id=job_id, attempt=attempt, entry=entry, outcome=outcome)

    async def _record_lock_not_acquired(self, *, job_id: UUID, attempt: BackgroundJobAttempt) -> None:
        async with self._unit_of_work_factory() as uow:
            await uow.background_job_events.append(
                BackgroundJobEvent(
                    job_id=job_id, attempt_id=attempt.attempt_id, event_type=JobEventType.LOCK_NOT_ACQUIRED,
                    message="Could not acquire the resource lock for this job; another job is using the same resource.",
                )
            )
            await uow.commit()
        self._metrics.increment_counter("finquest_job_lock_failures_total")

    async def _record_success(
        self, *, job_id: UUID, attempt: BackgroundJobAttempt, entry: JobRegistryEntry, outcome: Any
    ) -> JobExecutionResult:
        completed_at = self._clock()
        async with self._unit_of_work_factory() as uow:
            job = await uow.background_jobs.mark_succeeded(
                job_id, completed_at=completed_at, result_summary=outcome.result_summary
            )
            await uow.background_job_attempts.complete(
                attempt.attempt_id, status=JobAttemptStatus.SUCCEEDED, completed_at=completed_at
            )
            await uow.background_job_events.append(
                BackgroundJobEvent(
                    job_id=job_id, attempt_id=attempt.attempt_id, event_type=JobEventType.SUCCEEDED,
                    message="Job succeeded.",
                )
            )
            await uow.commit()
        self._metrics.increment_counter(
            "finquest_jobs_completed_total", labels={"job_type": entry.job_type.value, "queue": entry.queue_name}
        )
        return JobExecutionResult(
            job_id=job_id, status=job.status, result_summary=job.result_summary or {}, warnings=outcome.warnings
        )

    async def _schedule_retry_or_fail(
        self,
        *,
        job_id: UUID,
        attempt: BackgroundJobAttempt,
        entry: JobRegistryEntry,
        attempt_number: int,
        exception: Exception,
        error_code: str,
        delay_seconds: int | None,
    ) -> JobExecutionResult:
        completed_at = self._clock()
        sanitized_message = redact(str(exception))
        error_summary = {
            "error_code": error_code, "error_type": type(exception).__name__, "error_message": str(sanitized_message)[:1000],
        }
        retryable = delay_seconds is not None and attempt_number < entry.maximum_attempts

        async with self._unit_of_work_factory() as uow:
            await uow.background_job_attempts.complete(
                attempt.attempt_id,
                status=JobAttemptStatus.RETRYABLE_FAILURE if retryable else JobAttemptStatus.FAILED,
                completed_at=completed_at,
                error_type=type(exception).__name__,
                error_code=error_code,
                error_message=str(sanitized_message)[:2000],
                retry_delay_seconds=delay_seconds if retryable else None,
            )
            if retryable:
                available_at = completed_at + timedelta(seconds=delay_seconds)
                job = await uow.background_jobs.mark_retry_scheduled(
                    job_id, available_at=available_at, result_summary=error_summary
                )
                await uow.background_job_events.append(
                    BackgroundJobEvent(
                        job_id=job_id, attempt_id=attempt.attempt_id, event_type=JobEventType.RETRY_SCHEDULED,
                        message=f"Attempt {attempt_number} failed; retry scheduled in {delay_seconds}s.",
                    )
                )
                await uow.commit()
                try:
                    task_id = await self._job_queue.enqueue(
                        job_id=job_id, job_type=job.job_type, queue_name=entry.queue_name,
                        priority=job.priority, available_at=available_at,
                    )
                    async with self._unit_of_work_factory() as requeue_uow:
                        job = await requeue_uow.background_jobs.mark_queued(job_id, task_id=task_id)
                        await requeue_uow.commit()
                except Exception:  # noqa: BLE001 - the job remains durably RETRY_SCHEDULED; a maintenance sweep can requeue it
                    pass
                self._metrics.increment_counter(
                    "finquest_job_retries_total", labels={"job_type": entry.job_type.value, "queue": entry.queue_name}
                )
            else:
                job = await uow.background_jobs.mark_failed(job_id, completed_at=completed_at, result_summary=error_summary)
                await uow.background_job_events.append(
                    BackgroundJobEvent(
                        job_id=job_id, attempt_id=attempt.attempt_id, event_type=JobEventType.FAILED,
                        message=f"Attempt {attempt_number} failed non-retryably ({error_code}).",
                    )
                )
                await uow.commit()
                self._metrics.increment_counter(
                    "finquest_jobs_failed_total", labels={"job_type": entry.job_type.value, "queue": entry.queue_name}
                )

        return JobExecutionResult(job_id=job_id, status=job.status, result_summary=job.result_summary or {}, warnings=[])

    # -- administration -----------------------------------------------

    async def get_job(self, job_id: UUID) -> BackgroundJob:
        async with self._unit_of_work_factory() as uow:
            job = await uow.background_jobs.get_by_id(job_id)
        if job is None:
            raise BackgroundJobNotFoundError(f"No background job found with id '{job_id}'.")
        return job

    async def list_jobs(self, **filters: Any) -> list[BackgroundJob]:
        async with self._unit_of_work_factory() as uow:
            return await uow.background_jobs.list_jobs(**filters)

    async def count_jobs(self, **filters: Any) -> int:
        async with self._unit_of_work_factory() as uow:
            return await uow.background_jobs.count_jobs(**filters)

    async def list_attempts(self, job_id: UUID) -> list[BackgroundJobAttempt]:
        async with self._unit_of_work_factory() as uow:
            return await uow.background_job_attempts.list_for_job(job_id)

    async def list_events(self, job_id: UUID) -> list[BackgroundJobEvent]:
        async with self._unit_of_work_factory() as uow:
            return await uow.background_job_events.list_for_job(job_id)

    async def cancel_job(self, job_id: UUID) -> BackgroundJob:
        async with self._unit_of_work_factory() as uow:
            job = await uow.background_jobs.get_for_update(job_id)
            if job is None:
                raise BackgroundJobNotFoundError(f"No background job found with id '{job_id}'.")
            if job.status in TERMINAL_JOB_STATUSES:
                await uow.commit()
                raise InvalidJobStateError(f"Job {job_id} is already {job.status.value} and cannot be cancelled.")
            cancelled = await uow.background_jobs.mark_cancelled(job_id, cancelled_at=self._clock())
            await uow.background_job_events.append(
                BackgroundJobEvent(
                    job_id=job_id, event_type=JobEventType.CANCELLED,
                    message="Job cancelled by administrator. Cancellation of already-running work is cooperative.",
                )
            )
            await uow.commit()
        return cancelled

    async def requeue_job(self, job_id: UUID) -> BackgroundJob:
        async with self._unit_of_work_factory() as uow:
            job = await uow.background_jobs.get_for_update(job_id)
            if job is None:
                raise BackgroundJobNotFoundError(f"No background job found with id '{job_id}'.")
            if job.status not in (BackgroundJobStatus.FAILED, BackgroundJobStatus.RETRY_SCHEDULED):
                await uow.commit()
                raise InvalidJobStateError(f"Job {job_id} is {job.status.value} and cannot be requeued.")
            if job.attempt_count >= job.maximum_attempts:
                await uow.commit()
                raise InvalidJobStateError(f"Job {job_id} has exhausted its maximum attempts ({job.maximum_attempts}).")
            entry = self._job_registry.get(job.job_type)
            available_at = self._clock()
            requeued = await uow.background_jobs.mark_retry_scheduled(
                job_id, available_at=available_at, result_summary=job.result_summary
            )
            await uow.commit()

        task_id = await self._job_queue.enqueue(
            job_id=job_id, job_type=requeued.job_type, queue_name=entry.queue_name,
            priority=requeued.priority, available_at=available_at,
        )
        async with self._unit_of_work_factory() as uow:
            queued = await uow.background_jobs.mark_queued(job_id, task_id=task_id)
            await uow.background_job_events.append(
                BackgroundJobEvent(job_id=job_id, event_type=JobEventType.QUEUED, message="Job manually requeued by administrator.")
            )
            await uow.commit()
        return queued
