"""Unit tests for `BackgroundJobService`, using in-memory fakes for every
port (no Redis, no Celery, no PostgreSQL required) - exercises job
creation, idempotency, execution, retry scheduling, and duplicate-delivery
safety end to end at the application layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import InvalidJobParametersError, InvalidJobStateError
from stock_research_core.application.operations.job_registry import (
    BackgroundJobRegistry,
    FixedScheduleRetryPolicy,
    JobRegistryEntry,
    NeverRetryPolicy,
)
from stock_research_core.application.operations.models import PortfolioValuationParameters
from stock_research_core.application.operations.ports import HandlerOutcome
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.operations.enums import (
    BackgroundJobStatus,
    BackgroundJobType,
    JobTriggerSource,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _valuation_params() -> dict:
    return {"portfolio_id": str(uuid4()), "as_of": NOW.isoformat()}


class FakeJobRepo:
    def __init__(self) -> None:
        self.jobs: dict = {}
        self._idem_index: dict = {}

    def _idem_key(self, job_type, trigger_source, account_id, integration_id, idempotency_key):
        requester = f"account:{account_id}" if account_id else (f"integration:{integration_id}" if integration_id else f"source:{trigger_source}")
        return (job_type, trigger_source, requester, idempotency_key)

    async def create(self, job):
        self.jobs[job.job_id] = job
        key = self._idem_key(
            job.job_type, job.trigger_source.value, job.requested_by_account_id, job.requested_by_integration_id,
            job.idempotency_key,
        )
        self._idem_index[key] = job.job_id
        return job

    async def get_by_id(self, job_id):
        return self.jobs.get(job_id)

    async def get_for_update(self, job_id):
        return self.jobs.get(job_id)

    async def get_by_idempotency_key(self, *, job_type, trigger_source, requested_by_account_id, requested_by_integration_id, idempotency_key):
        key = self._idem_key(job_type, trigger_source, requested_by_account_id, requested_by_integration_id, idempotency_key)
        job_id = self._idem_index.get(key)
        return self.jobs.get(job_id) if job_id else None

    def _update(self, job_id, **updates):
        job = self.jobs[job_id].model_copy(update=updates)
        self.jobs[job_id] = job
        return job

    async def mark_queued(self, job_id, *, task_id):
        return self._update(job_id, status=BackgroundJobStatus.QUEUED, task_id=task_id)

    async def mark_running(self, job_id, *, started_at):
        job = self.jobs[job_id]
        return self._update(job_id, status=BackgroundJobStatus.RUNNING, started_at=started_at, attempt_count=job.attempt_count + 1)

    async def update_progress(self, job_id, *, current, total, message):
        updates = {"progress_current": current}
        if total is not None:
            updates["progress_total"] = total
        if message is not None:
            updates["progress_message"] = message
        return self._update(job_id, **updates)

    async def mark_succeeded(self, job_id, *, completed_at, result_summary):
        return self._update(job_id, status=BackgroundJobStatus.SUCCEEDED, completed_at=completed_at, result_summary=result_summary)

    async def mark_failed(self, job_id, *, completed_at, result_summary):
        return self._update(job_id, status=BackgroundJobStatus.FAILED, completed_at=completed_at, result_summary=result_summary)

    async def mark_retry_scheduled(self, job_id, *, available_at, result_summary):
        return self._update(job_id, status=BackgroundJobStatus.RETRY_SCHEDULED, available_at=available_at, result_summary=result_summary)

    async def mark_cancelled(self, job_id, *, cancelled_at):
        return self._update(job_id, status=BackgroundJobStatus.CANCELLED, cancelled_at=cancelled_at, completed_at=cancelled_at)


class FakeAttemptRepo:
    def __init__(self) -> None:
        self.attempts: dict = {}

    async def create(self, attempt):
        self.attempts[attempt.attempt_id] = attempt
        return attempt

    async def complete(self, attempt_id, *, status, completed_at, error_type=None, error_code=None, error_message=None, retry_delay_seconds=None):
        updated = self.attempts[attempt_id].model_copy(update={
            "status": status, "completed_at": completed_at, "error_type": error_type, "error_code": error_code,
            "error_message": error_message, "retry_delay_seconds": retry_delay_seconds,
        })
        self.attempts[attempt_id] = updated
        return updated

    async def list_for_job(self, job_id):
        return [a for a in self.attempts.values() if a.job_id == job_id]


class FakeEventRepo:
    def __init__(self) -> None:
        self.events: list = []

    async def append(self, event):
        self.events.append(event)
        return event

    async def list_for_job(self, job_id):
        return [e for e in self.events if e.job_id == job_id]


class FakeUow:
    def __init__(self, job_repo, attempt_repo, event_repo) -> None:
        self.background_jobs = job_repo
        self.background_job_attempts = attempt_repo
        self.background_job_events = event_repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None:
        pass


class FakeQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.enqueued: list = []

    async def enqueue(self, *, job_id, job_type, queue_name, priority, available_at):
        if self.fail:
            raise ConnectionError("broker unreachable")
        self.enqueued.append(job_id)
        return f"task-{job_id}"


class FakeLock:
    async def acquire(self, *, key, owner_id, ttl_seconds, wait_timeout_seconds):
        return True

    async def release(self, *, key, owner_id):
        return True

    async def extend(self, *, key, owner_id, ttl_seconds):
        return True


class RecordingMetrics:
    def __init__(self) -> None:
        self.counters: list[tuple[str, dict | None]] = []

    def increment_counter(self, name, *, value=1.0, labels=None):
        self.counters.append((name, labels))

    def set_gauge(self, name, value, *, labels=None):
        pass

    def observe_histogram(self, name, value, *, labels=None):
        pass

    def time_operation(self, name, *, labels=None):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()


class OkHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, *, parameters, progress):
        self.calls += 1
        await progress.report(current=1, total=1)
        return HandlerOutcome(result_summary={"ok": True})


class FailingHandler:
    def __init__(self, exception_factory) -> None:
        self._exception_factory = exception_factory
        self.calls = 0

    async def handle(self, *, parameters, progress):
        self.calls += 1
        raise self._exception_factory()


class Harness:
    def __init__(self, *, handler, maximum_attempts: int = 3, retryable_exceptions: tuple = (), queue: FakeQueue | None = None) -> None:
        self.job_repo = FakeJobRepo()
        self.attempt_repo = FakeAttemptRepo()
        self.event_repo = FakeEventRepo()
        self.queue = queue or FakeQueue()
        self.metrics = RecordingMetrics()
        entries = []
        for job_type in BackgroundJobType:
            entries.append(JobRegistryEntry(
                job_type=job_type, parameter_model=PortfolioValuationParameters, queue_name="finquest.default",
                task_name=f"finquest.{job_type.value.lower()}", handler=handler, maximum_attempts=maximum_attempts,
                retry_policy=(
                    FixedScheduleRetryPolicy(maximum_attempts=maximum_attempts, delays_seconds=(10, 30), retryable_exceptions=retryable_exceptions)
                    if retryable_exceptions else NeverRetryPolicy()
                ),
                time_limit_seconds=60, resource_key_builder=lambda p: None, allowed_trigger_sources=frozenset(JobTriggerSource),
            ))
        self.registry = BackgroundJobRegistry(entries)
        self.service = BackgroundJobService(
            unit_of_work_factory=self._uow_factory, job_registry=self.registry, job_queue=self.queue,
            lock_port=FakeLock(), clock=lambda: NOW, metrics=self.metrics,
        )

    def _uow_factory(self):
        return FakeUow(self.job_repo, self.attempt_repo, self.event_repo)


class TestCreateJob:
    @pytest.mark.asyncio
    async def test_invalid_parameters_are_rejected(self) -> None:
        harness = Harness(handler=OkHandler())
        with pytest.raises(InvalidJobParametersError):
            await harness.service.create_job(
                job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters={"not": "valid"},
                idempotency_key="k1", trigger_source=JobTriggerSource.API,
            )

    @pytest.mark.asyncio
    async def test_creates_a_queued_job(self) -> None:
        harness = Harness(handler=OkHandler())
        result = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        assert result.created
        assert result.job.status == BackgroundJobStatus.QUEUED
        assert result.job.job_id in harness.queue.enqueued

    @pytest.mark.asyncio
    async def test_duplicate_idempotency_key_returns_canonical_job(self) -> None:
        harness = Harness(handler=OkHandler())
        first = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="same-key", trigger_source=JobTriggerSource.API,
        )
        second = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="same-key", trigger_source=JobTriggerSource.API,
        )
        assert not second.created
        assert second.duplicate_of_job_id == first.job.job_id
        assert len(harness.queue.enqueued) == 1

    @pytest.mark.asyncio
    async def test_different_idempotency_key_creates_a_new_job(self) -> None:
        harness = Harness(handler=OkHandler())
        first = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="key-1", trigger_source=JobTriggerSource.API,
        )
        second = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="key-2", trigger_source=JobTriggerSource.API,
        )
        assert second.created
        assert second.job.job_id != first.job.job_id

    @pytest.mark.asyncio
    async def test_same_key_different_requester_scope_creates_distinct_jobs(self) -> None:
        harness = Harness(handler=OkHandler())
        account_a, account_b = uuid4(), uuid4()
        first = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="shared-key", trigger_source=JobTriggerSource.API, requested_by_account_id=account_a,
        )
        second = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="shared-key", trigger_source=JobTriggerSource.API, requested_by_account_id=account_b,
        )
        assert second.created
        assert second.job.job_id != first.job.job_id

    @pytest.mark.asyncio
    async def test_queue_failure_preserves_the_durable_job_as_failed(self) -> None:
        harness = Harness(handler=OkHandler(), queue=FakeQueue(fail=True))
        result = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        assert result.created
        assert result.job.status == BackgroundJobStatus.FAILED
        assert result.job.job_id in harness.job_repo.jobs  # never lost

    @pytest.mark.asyncio
    async def test_creation_records_metrics(self) -> None:
        harness = Harness(handler=OkHandler())
        await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        assert any(name == "finquest_jobs_created_total" for name, _ in harness.metrics.counters)


class TestExecuteJob:
    @pytest.mark.asyncio
    async def test_execution_creates_an_attempt_and_succeeds(self) -> None:
        handler = OkHandler()
        harness = Harness(handler=handler)
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        result = await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        assert result.status == BackgroundJobStatus.SUCCEEDED
        assert handler.calls == 1
        attempts = await harness.attempt_repo.list_for_job(created.job.job_id)
        assert len(attempts) == 1
        assert attempts[0].status == "SUCCEEDED"

    @pytest.mark.asyncio
    async def test_events_are_appended_across_the_lifecycle(self) -> None:
        harness = Harness(handler=OkHandler())
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        events = await harness.event_repo.list_for_job(created.job.job_id)
        event_types = [e.event_type.value for e in events]
        assert event_types == ["CREATED", "QUEUED", "STARTED", "SUCCEEDED"]

    @pytest.mark.asyncio
    async def test_already_succeeded_job_is_not_executed_twice(self) -> None:
        handler = OkHandler()
        harness = Harness(handler=handler)
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        second = await harness.service.execute_job(job_id=created.job.job_id, worker_name="w2", celery_task_id="c2")
        assert second.status == BackgroundJobStatus.SUCCEEDED
        assert handler.calls == 1  # not invoked a second time

    @pytest.mark.asyncio
    async def test_cancelled_job_is_not_executed(self) -> None:
        handler = OkHandler()
        harness = Harness(handler=handler)
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        await harness.service.cancel_job(created.job.job_id)
        result = await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        assert result.status == BackgroundJobStatus.CANCELLED
        assert handler.calls == 0

    @pytest.mark.asyncio
    async def test_retryable_failure_schedules_a_retry(self) -> None:
        handler = FailingHandler(lambda: ConnectionError("transient"))
        harness = Harness(handler=handler, maximum_attempts=3, retryable_exceptions=(ConnectionError,))
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        result = await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        # re-enqueued immediately by the service -> ends in QUEUED, not stuck at RETRY_SCHEDULED
        assert result.status == BackgroundJobStatus.QUEUED
        attempts = await harness.attempt_repo.list_for_job(created.job.job_id)
        assert attempts[0].status == "RETRYABLE_FAILURE"

    @pytest.mark.asyncio
    async def test_non_retryable_failure_stops_immediately(self) -> None:
        handler = FailingHandler(lambda: ValueError("bad input"))
        harness = Harness(handler=handler, maximum_attempts=3, retryable_exceptions=(ConnectionError,))
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        result = await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        assert result.status == BackgroundJobStatus.FAILED
        attempts = await harness.attempt_repo.list_for_job(created.job.job_id)
        assert attempts[0].status == "FAILED"

    @pytest.mark.asyncio
    async def test_maximum_attempts_is_never_exceeded(self) -> None:
        handler = FailingHandler(lambda: ConnectionError("transient"))
        harness = Harness(handler=handler, maximum_attempts=2, retryable_exceptions=(ConnectionError,))
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        first = await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        assert first.status == BackgroundJobStatus.QUEUED  # attempt 1 of 2, retried
        second = await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c2")
        assert second.status == BackgroundJobStatus.FAILED  # attempt 2 of 2, exhausted
        assert handler.calls == 2

    @pytest.mark.asyncio
    async def test_failure_error_message_is_sanitized_of_tracebacks(self) -> None:
        def _raise():
            raise ValueError("Traceback (most recent call last):\nfoo bar")

        harness = Harness(handler=FailingHandler(_raise))
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        attempts = await harness.attempt_repo.list_for_job(created.job.job_id)
        assert "Traceback" not in (attempts[0].error_message or "")

    @pytest.mark.asyncio
    async def test_repeated_delivery_of_a_running_job_is_safe(self) -> None:
        harness = Harness(handler=OkHandler())
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        # Simulate the job already being RUNNING (e.g. a duplicate Celery
        # delivery arriving mid-execution) without actually running it twice.
        job = harness.job_repo.jobs[created.job.job_id]
        harness.job_repo.jobs[created.job.job_id] = job.model_copy(update={"status": BackgroundJobStatus.RUNNING, "started_at": NOW})
        result = await harness.service.execute_job(job_id=created.job.job_id, worker_name="w2", celery_task_id="c2")
        assert result.status == BackgroundJobStatus.RUNNING
        assert "duplicate delivery" in result.warnings[0]


class TestCancelAndRequeue:
    @pytest.mark.asyncio
    async def test_cannot_cancel_a_terminal_job(self) -> None:
        harness = Harness(handler=OkHandler())
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        with pytest.raises(InvalidJobStateError):
            await harness.service.cancel_job(created.job.job_id)

    @pytest.mark.asyncio
    async def test_requeue_respects_maximum_attempts(self) -> None:
        handler = FailingHandler(lambda: ValueError("bad"))
        harness = Harness(handler=handler, maximum_attempts=1)
        created = await harness.service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        await harness.service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
        with pytest.raises(InvalidJobStateError, match="exhausted"):
            await harness.service.requeue_job(created.job.job_id)
