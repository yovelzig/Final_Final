"""Unit tests for `JobExecutionContext` (Phase G2B): its construction at
job-creation time (passed to `resource_key_builder`) and at execution
time (passed to `JobHandlerPort.handle`), using in-memory fakes for
every port (no Redis, no Celery, no PostgreSQL required).
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.operations import handlers as handlers_module
from stock_research_core.application.operations.job_registry import (
    BackgroundJobRegistry,
    JobRegistryEntry,
    NeverRetryPolicy,
)
from stock_research_core.application.operations.models import PortfolioValuationParameters
from stock_research_core.application.operations.ports import HandlerOutcome, JobExecutionContext
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.operations.enums import BackgroundJobStatus, BackgroundJobType, JobTriggerSource

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
        return self._update(job_id, progress_current=current)

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
        updated = self.attempts[attempt_id].model_copy(update={"status": status, "completed_at": completed_at})
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
    def __init__(self) -> None:
        self.enqueued: list = []

    async def enqueue(self, *, job_id, job_type, queue_name, priority, available_at):
        self.enqueued.append(job_id)
        return f"task-{job_id}"


class FakeLock:
    async def acquire(self, *, key, owner_id, ttl_seconds, wait_timeout_seconds):
        return True

    async def release(self, *, key, owner_id):
        return True

    async def extend(self, *, key, owner_id, ttl_seconds):
        return True


class ContextCapturingHandler:
    """Records every `JobExecutionContext` it is invoked with."""

    def __init__(self) -> None:
        self.contexts: list[JobExecutionContext] = []

    async def handle(self, *, context, parameters, progress):
        self.contexts.append(context)
        await progress.report(current=1, total=1)
        return HandlerOutcome(result_summary={"ok": True})


class ResourceKeyCapturingBuilder:
    """Records every `JobExecutionContext` `resource_key_builder` is
    called with, and returns a deterministic key derived from it."""

    def __init__(self) -> None:
        self.contexts: list[JobExecutionContext] = []

    def __call__(self, context: JobExecutionContext, parameters) -> str | None:
        self.contexts.append(context)
        return f"captured:{context.job_id}"


def _build_service(*, handler, resource_key_builder):
    job_repo = FakeJobRepo()
    attempt_repo = FakeAttemptRepo()
    event_repo = FakeEventRepo()
    queue = FakeQueue()
    entries = [
        JobRegistryEntry(
            job_type=job_type, parameter_model=PortfolioValuationParameters, queue_name="finquest.default",
            task_name=f"finquest.{job_type.value.lower()}", handler=handler, maximum_attempts=3,
            retry_policy=NeverRetryPolicy(), time_limit_seconds=60, resource_key_builder=resource_key_builder,
            allowed_trigger_sources=frozenset(JobTriggerSource),
        )
        for job_type in BackgroundJobType
    ]
    registry = BackgroundJobRegistry(entries)

    def _uow_factory():
        return FakeUow(job_repo, attempt_repo, event_repo)

    service = BackgroundJobService(
        unit_of_work_factory=_uow_factory, job_registry=registry, job_queue=queue, lock_port=FakeLock(), clock=lambda: NOW,
    )
    return service, job_repo


class TestCreationTimeContext:
    @pytest.mark.asyncio
    async def test_resource_key_builder_receives_a_context_with_attempt_number_zero(self) -> None:
        handler = ContextCapturingHandler()
        key_builder = ResourceKeyCapturingBuilder()
        service, _job_repo = _build_service(handler=handler, resource_key_builder=key_builder)

        account_id = uuid4()
        result = await service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API, requested_by_account_id=account_id,
            correlation_id="corr-abc",
        )

        assert len(key_builder.contexts) == 1
        creation_context = key_builder.contexts[0]
        assert creation_context.attempt_number == 0
        assert creation_context.requested_by_account_id == account_id
        assert creation_context.idempotency_key == "k1"
        assert creation_context.correlation_id == "corr-abc"
        # The pre-generated job_id must match the persisted job's own id.
        assert creation_context.job_id == result.job.job_id

    @pytest.mark.asyncio
    async def test_pre_generated_job_id_is_persisted_on_the_background_job(self) -> None:
        handler = ContextCapturingHandler()
        key_builder = ResourceKeyCapturingBuilder()
        service, job_repo = _build_service(handler=handler, resource_key_builder=key_builder)

        result = await service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        creation_context = key_builder.contexts[0]
        assert creation_context.job_id in job_repo.jobs
        assert job_repo.jobs[creation_context.job_id].job_id == result.job.job_id


class TestExecutionTimeContext:
    @pytest.mark.asyncio
    async def test_execution_context_attempt_number_is_one_on_first_attempt(self) -> None:
        handler = ContextCapturingHandler()
        service, _job_repo = _build_service(handler=handler, resource_key_builder=lambda context, p: None)
        created = await service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        assert len(handler.contexts) == 1
        assert handler.contexts[0].attempt_number == 1
        assert handler.contexts[0].job_id == created.job.job_id

    @pytest.mark.asyncio
    async def test_correlation_id_is_sourced_from_the_created_event(self) -> None:
        handler = ContextCapturingHandler()
        service, _job_repo = _build_service(handler=handler, resource_key_builder=lambda context, p: None)
        created = await service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API, correlation_id="req-42",
        )
        await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        assert handler.contexts[0].correlation_id == "req-42"

    @pytest.mark.asyncio
    async def test_correlation_id_is_none_when_not_supplied_at_creation(self) -> None:
        handler = ContextCapturingHandler()
        service, _job_repo = _build_service(handler=handler, resource_key_builder=lambda context, p: None)
        created = await service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.API,
        )
        await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        assert handler.contexts[0].correlation_id is None

    @pytest.mark.asyncio
    async def test_trusted_requester_fields_come_from_the_job_row_not_parameters(self) -> None:
        handler = ContextCapturingHandler()
        service, _job_repo = _build_service(handler=handler, resource_key_builder=lambda context, p: None)
        integration_id = uuid4()
        created = await service.create_job(
            job_type=BackgroundJobType.PORTFOLIO_VALUATION, raw_parameters=_valuation_params(),
            idempotency_key="k1", trigger_source=JobTriggerSource.N8N,
            requested_by_integration_id=integration_id,
        )
        await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        context = handler.contexts[0]
        assert context.requested_by_integration_id == integration_id
        assert context.requested_by_account_id is None
        assert context.trigger_source == JobTriggerSource.N8N


class TestAllHandlersAcceptContext:
    """Regression guard for the exact `TypeError` risk this correction
    introduces: `execute_job` always calls `entry.handler.handle(context=...,
    parameters=..., progress=...)`, so every registered handler class's
    `handle` must accept a `context` keyword argument, even the ones that
    ignore it."""

    def _handler_classes(self) -> list[type]:
        return [
            obj for _name, obj in inspect.getmembers(handlers_module, inspect.isclass)
            if obj.__module__ == handlers_module.__name__ and _name.endswith("JobHandler")
        ]

    def test_at_least_fourteen_handlers_are_defined(self) -> None:
        # 13 pre-existing + LiveResearchRunExecutionJobHandler.
        assert len(self._handler_classes()) >= 14

    def test_every_handler_handle_method_accepts_context(self) -> None:
        for handler_cls in self._handler_classes():
            signature = inspect.signature(handler_cls.handle)
            assert "context" in signature.parameters, f"{handler_cls.__name__}.handle has no 'context' parameter"
            assert signature.parameters["context"].kind == inspect.Parameter.KEYWORD_ONLY
