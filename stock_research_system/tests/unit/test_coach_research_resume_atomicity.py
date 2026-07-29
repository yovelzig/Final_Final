"""Unit tests for the terminal-to-resume-job atomicity hook and the
reconciliation sweep (spec G2D2 section 13) - in-memory fakes only, no
real PostgreSQL/Redis/Celery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import LockAcquisitionError
from stock_research_core.application.operations.job_registry import (
    BackgroundJobRegistry,
    FixedScheduleRetryPolicy,
    JobRegistryEntry,
    NeverRetryPolicy,
)
from stock_research_core.application.operations.models import (
    CoachResearchResumeParameters,
    JobParameters,
    LiveResearchRunExecutionParameters,
)
from stock_research_core.application.operations.ports import HandlerOutcome
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus
from stock_research_core.domain.learning_orchestrator.models import LearningOrchestratorRun
from stock_research_core.domain.operations.enums import BackgroundJobStatus, BackgroundJobType, JobTriggerSource

from tests.unit.learning_orchestrator_fakes import FakeRunRepo

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


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

    async def mark_retry_scheduled(self, job_id, *, available_at, result_summary):
        updates = {"status": BackgroundJobStatus.RETRY_SCHEDULED, "available_at": available_at}
        if result_summary is not None:
            updates["result_summary"] = result_summary
        return self._update(job_id, **updates)

    async def mark_running(self, job_id, *, started_at):
        job = self.jobs[job_id]
        return self._update(job_id, status=BackgroundJobStatus.RUNNING, started_at=started_at, attempt_count=job.attempt_count + 1)

    async def mark_succeeded(self, job_id, *, completed_at, result_summary):
        return self._update(job_id, status=BackgroundJobStatus.SUCCEEDED, completed_at=completed_at, result_summary=result_summary)

    async def mark_failed(self, job_id, *, completed_at, result_summary):
        return self._update(job_id, status=BackgroundJobStatus.FAILED, completed_at=completed_at, result_summary=result_summary)

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
    def __init__(self, *, job_repo, attempt_repo, event_repo, run_repo) -> None:
        self.background_jobs = job_repo
        self.background_job_attempts = attempt_repo
        self.background_job_events = event_repo
        self.learning_orchestrator_runs = run_repo
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None:
        self.commit_count += 1



class FakeAccountLimiter:
    def __init__(self, *, uow, fail=False):
        self.uow = uow
        self.fail = fail
        self.releases: list[tuple] = []

    async def release(self, *, account_id, reservation_id):
        assert self.uow.commit_count > 0
        self.releases.append((account_id, reservation_id))
        if self.fail:
            raise RuntimeError("redis unavailable")

class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list = []

    async def enqueue(self, *, job_id, job_type, queue_name, priority, available_at):
        self.enqueued.append(job_id)
        return f"task-{job_id}"


class FakeLock:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.acquired_keys: list[str] = []

    async def acquire(self, *, key, owner_id, ttl_seconds, wait_timeout_seconds):
        if self.available:
            self.acquired_keys.append(key)
        return self.available

    async def release(self, *, key, owner_id):
        return True

    async def extend(self, *, key, owner_id, ttl_seconds):
        return True


class NoOpMetrics:
    def increment_counter(self, name, *, value=1.0, labels=None):
        pass

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


class OkLiveResearchHandler:
    """Always succeeds - the caller controls `result_summary` per test."""

    def __init__(self, *, result_summary: dict) -> None:
        self.result_summary = result_summary

    async def handle(self, *, context, parameters, progress):
        return HandlerOutcome(result_summary=self.result_summary)


class FailingLiveResearchHandler:
    async def handle(self, *, context, parameters, progress):
        raise RuntimeError("provider unreachable")


class NeverCalledResumeHandler:
    async def handle(self, *, context, parameters, progress):
        raise AssertionError("COACH_RESEARCH_RESUME should never be executed in these tests")


class _UnusedHandler:
    """Placeholder for every `BackgroundJobType` other than the two these
    tests actually exercise - `BackgroundJobRegistry` requires an entry
    for every job type to construct at all, but none of these are ever
    invoked in this file."""

    async def handle(self, *, context, parameters, progress):
        raise AssertionError("This job type is not exercised by these tests.")


def _build_service(*, live_research_handler, run_repo, lock=None, limiter_factory=None):
    job_repo, attempt_repo, event_repo = FakeJobRepo(), FakeAttemptRepo(), FakeEventRepo()
    uow = FakeUow(job_repo=job_repo, attempt_repo=attempt_repo, event_repo=event_repo, run_repo=run_repo)
    entries = [
        JobRegistryEntry(
            job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, parameter_model=LiveResearchRunExecutionParameters,
            queue_name="finquest.research", task_name="finquest.live_research_run_execution",
            handler=live_research_handler, maximum_attempts=1, retry_policy=NeverRetryPolicy(),
            time_limit_seconds=180, resource_key_builder=lambda _c, _p: None,
            allowed_trigger_sources=frozenset({JobTriggerSource.SYSTEM}),
        ),
        JobRegistryEntry(
            job_type=BackgroundJobType.COACH_RESEARCH_RESUME, parameter_model=CoachResearchResumeParameters,
            queue_name="finquest.coach", task_name="finquest.coach_research_resume",
            handler=NeverCalledResumeHandler(), maximum_attempts=3,
            retry_policy=FixedScheduleRetryPolicy(maximum_attempts=3, delays_seconds=(10,), retryable_exceptions=()),
            time_limit_seconds=120, resource_key_builder=lambda _c, p: f"coach-research-resume:{p.coach_run_id}",
            allowed_trigger_sources=frozenset({JobTriggerSource.SYSTEM}),
        ),
    ]
    for job_type in BackgroundJobType:
        if job_type in (BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, BackgroundJobType.COACH_RESEARCH_RESUME):
            continue
        entries.append(
            JobRegistryEntry(
                job_type=job_type, parameter_model=JobParameters, queue_name="finquest.default",
                task_name=f"finquest.{job_type.value.lower()}", handler=_UnusedHandler(), maximum_attempts=1,
                retry_policy=NeverRetryPolicy(), time_limit_seconds=60, resource_key_builder=lambda _c, _p: None,
                allowed_trigger_sources=frozenset({JobTriggerSource.SYSTEM}),
            )
        )
    registry = BackgroundJobRegistry(entries)
    queue = FakeQueue()
    limiter = limiter_factory(uow) if limiter_factory else None
    service = BackgroundJobService(
        unit_of_work_factory=lambda: uow, job_registry=registry, job_queue=queue,
        lock_port=lock or FakeLock(), metrics=NoOpMetrics(), clock=lambda: NOW,
        account_research_rate_limiter=limiter,
    )
    return service, job_repo, uow, queue


def _waiting_run(*, research_job_id) -> LearningOrchestratorRun:
    return LearningOrchestratorRun(
        thread_id=uuid4(), learner_id=uuid4(), trusted_account_id=uuid4(), idempotency_key=f"key-{uuid4()}",
        correlation_id=str(uuid4()), graph_version="learning-coach-graph-v1",
        status=LearningOrchestratorRunStatus.WAITING_FOR_RESEARCH, waiting_at=NOW, research_job_id=research_job_id,
    )


def _waiting_run_repo(*, research_job_id) -> tuple[FakeRunRepo, LearningOrchestratorRun]:
    run_repo = FakeRunRepo()
    run = _waiting_run(research_job_id=research_job_id)
    run_repo.runs[run.run_id] = run
    return run_repo, run


async def test_evidence_found_success_creates_and_enqueues_a_resume_job() -> None:
    """End to end through the real `execute_job` -> `_record_success` ->
    atomicity-hook path (not a direct unit call to the private hook) -
    the run's `research_job_id` is only known once `create_job` has
    generated it, so the waiting run is seeded with that real id before
    `execute_job` runs, exactly as production ordering requires."""
    account_id = uuid4()
    run_repo = FakeRunRepo()
    handler = OkLiveResearchHandler(
        result_summary={
            "research_run_status": "COMPLETED", "failure_category": None, "evidence_recorded": 2,
            "research_request_id": str(uuid4()), "research_run_id": str(uuid4()),
        }
    )
    service, job_repo, _uow, queue = _build_service(live_research_handler=handler, run_repo=run_repo)
    creation = await service.create_job(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        raw_parameters={
            "original_question": "What happened to Nvidia this week?", "scope": "NEWS_SCAN",
            "subject_raw_text": "Nvidia",
        },
        idempotency_key=f"key-{uuid4()}", trigger_source=JobTriggerSource.SYSTEM, requested_by_account_id=account_id,
    )
    job_id = creation.job.job_id
    run = _waiting_run(research_job_id=job_id)
    run_repo.runs[run.run_id] = run

    await service.execute_job(job_id=job_id, worker_name="w1", celery_task_id="c1")

    resume_jobs = [j for j in job_repo.jobs.values() if j.job_type == BackgroundJobType.COACH_RESEARCH_RESUME]
    assert len(resume_jobs) == 1
    parameters = CoachResearchResumeParameters.model_validate(resume_jobs[0].parameters)
    assert parameters.coach_run_id == run.run_id
    assert parameters.research_job_id == job_id
    # Enqueued after commit (spec section 13's "queue delivery may happen
    # after commit through the existing delivery pattern").
    assert resume_jobs[0].job_id in queue.enqueued


async def test_no_coach_run_waiting_creates_nothing() -> None:
    run_repo = FakeRunRepo()  # empty - no run waits on anything
    handler = OkLiveResearchHandler(
        result_summary={
            "research_run_status": "FAILED", "failure_category": "NO_EVIDENCE_FOUND", "evidence_recorded": 0,
        }
    )
    service, job_repo, _uow, _queue = _build_service(live_research_handler=handler, run_repo=run_repo)
    creation = await service.create_job(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        raw_parameters={
            "original_question": "What happened to Nvidia this week?", "scope": "NEWS_SCAN",
            "subject_raw_text": "Nvidia",
        },
        idempotency_key=f"key-{uuid4()}", trigger_source=JobTriggerSource.SYSTEM, requested_by_account_id=uuid4(),
    )
    await service.execute_job(job_id=creation.job.job_id, worker_name="w1", celery_task_id="c1")

    resume_jobs = [j for j in job_repo.jobs.values() if j.job_type == BackgroundJobType.COACH_RESEARCH_RESUME]
    assert resume_jobs == []


async def test_provider_failure_still_creates_a_resume_job() -> None:
    account_id = uuid4()
    run_repo = FakeRunRepo()
    service, job_repo, _uow, _queue = _build_service(live_research_handler=FailingLiveResearchHandler(), run_repo=run_repo)
    creation = await service.create_job(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        raw_parameters={
            "original_question": "What happened to Nvidia this week?", "scope": "NEWS_SCAN",
            "subject_raw_text": "Nvidia",
        },
        idempotency_key=f"key-{uuid4()}", trigger_source=JobTriggerSource.SYSTEM, requested_by_account_id=account_id,
    )
    job_id = creation.job.job_id
    run = _waiting_run(research_job_id=job_id)
    run_repo.runs[run.run_id] = run

    await service.execute_job(job_id=job_id, worker_name="w1", celery_task_id="c1")

    job = job_repo.jobs[job_id]
    assert job.status == BackgroundJobStatus.FAILED
    resume_jobs = [j for j in job_repo.jobs.values() if j.job_type == BackgroundJobType.COACH_RESEARCH_RESUME]
    assert len(resume_jobs) == 1


async def test_duplicate_completion_does_not_create_a_second_resume_job() -> None:
    account_id = uuid4()
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    handler = OkLiveResearchHandler(result_summary={"placeholder": True})
    service, job_repo, uow, _queue = _build_service(live_research_handler=handler, run_repo=run_repo)

    async with uow as active_uow:
        job = await active_uow.background_jobs.create(
            (await _fake_terminal_job(research_job_id, account_id))
        )
        first = await service._maybe_create_coach_resume_job(active_uow, job)  # noqa: SLF001
        second = await service._maybe_create_coach_resume_job(active_uow, job)  # noqa: SLF001
    assert first is not None
    assert second is None  # idempotent no-op on the second call


async def _fake_terminal_job(research_job_id, account_id):
    from stock_research_core.domain.operations.models import BackgroundJob

    return BackgroundJob(
        job_id=research_job_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        status=BackgroundJobStatus.SUCCEEDED, trigger_source=JobTriggerSource.SYSTEM,
        requested_by_account_id=account_id, idempotency_key=f"key-{research_job_id}",
        queue_name="finquest.research", task_name="finquest.live_research_run_execution", started_at=NOW,
        completed_at=NOW, result_summary={"placeholder": True},
    )


async def test_reconcile_creates_missing_resume_job_for_stuck_run() -> None:
    account_id = uuid4()
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    service, job_repo, uow, _queue = _build_service(live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo)
    async with uow as active_uow:
        await active_uow.background_jobs.create(await _fake_terminal_job(research_job_id, account_id))

    created_count = await service.reconcile_waiting_coach_runs(batch_size=10)

    assert created_count == 1
    resume_jobs = [j for j in job_repo.jobs.values() if j.job_type == BackgroundJobType.COACH_RESEARCH_RESUME]
    assert len(resume_jobs) == 1


async def test_reconcile_is_idempotent() -> None:
    account_id = uuid4()
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    service, job_repo, uow, _queue = _build_service(live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo)
    async with uow as active_uow:
        await active_uow.background_jobs.create(await _fake_terminal_job(research_job_id, account_id))

    first_count = await service.reconcile_waiting_coach_runs(batch_size=10)
    second_count = await service.reconcile_waiting_coach_runs(batch_size=10)

    assert first_count == 1
    assert second_count == 0
    resume_jobs = [j for j in job_repo.jobs.values() if j.job_type == BackgroundJobType.COACH_RESEARCH_RESUME]
    assert len(resume_jobs) == 1


async def test_reconcile_skips_runs_whose_research_job_is_not_yet_terminal() -> None:
    account_id = uuid4()
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    service, job_repo, uow, _queue = _build_service(live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo)
    from stock_research_core.domain.operations.models import BackgroundJob

    async with uow as active_uow:
        await active_uow.background_jobs.create(
            BackgroundJob(
                job_id=research_job_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
                status=BackgroundJobStatus.RUNNING, trigger_source=JobTriggerSource.SYSTEM,
                requested_by_account_id=account_id, idempotency_key=f"key-{research_job_id}",
                queue_name="finquest.research", task_name="finquest.live_research_run_execution", started_at=NOW,
            )
        )

    created_count = await service.reconcile_waiting_coach_runs(batch_size=10)
    assert created_count == 0


async def test_reconcile_returns_zero_when_lock_unavailable() -> None:
    account_id = uuid4()
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    lock = FakeLock(available=False)
    service, job_repo, uow, _queue = _build_service(live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo, lock=lock)
    async with uow as active_uow:
        await active_uow.background_jobs.create(await _fake_terminal_job(research_job_id, account_id))

    created_count = await service.reconcile_waiting_coach_runs(batch_size=10)
    assert created_count == 0
    resume_jobs = [j for j in job_repo.jobs.values() if j.job_type == BackgroundJobType.COACH_RESEARCH_RESUME]
    assert resume_jobs == []


# -- G2D2/H1 correction pass, section 9: recovering a resume job that already exists but never reached the queue -----------------------------------------------


async def _fake_resume_job(*, run_id, research_job_id, status, result_summary=None):
    from stock_research_core.domain.operations.models import BackgroundJob

    completed_at = NOW if status == BackgroundJobStatus.FAILED else None
    return BackgroundJob(
        job_id=uuid4(), job_type=BackgroundJobType.COACH_RESEARCH_RESUME, status=status,
        trigger_source=JobTriggerSource.SYSTEM,
        idempotency_key=f"coach-research-resume:{run_id}:{research_job_id}",
        queue_name="finquest.coach", task_name="finquest.coach_research_resume", available_at=NOW,
        maximum_attempts=3, result_summary=result_summary, completed_at=completed_at,
    )


async def test_reconcile_enqueues_a_pending_resume_job_that_was_never_queued() -> None:
    """Scenario 2: a resume job row exists (created by an earlier sweep
    or the terminal-transaction hook) but the process crashed before it
    ever reached the queue - the sweep must enqueue the existing row,
    never create a second one."""
    account_id = uuid4()
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    service, job_repo, uow, queue = _build_service(
        live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo,
    )
    async with uow as active_uow:
        await active_uow.background_jobs.create(await _fake_terminal_job(research_job_id, account_id))
        pending_resume_job = await active_uow.background_jobs.create(
            await _fake_resume_job(run_id=run.run_id, research_job_id=research_job_id, status=BackgroundJobStatus.PENDING)
        )

    recovered_count = await service.reconcile_waiting_coach_runs(batch_size=10)

    assert recovered_count == 1
    resume_jobs = [j for j in job_repo.jobs.values() if j.job_type == BackgroundJobType.COACH_RESEARCH_RESUME]
    assert len(resume_jobs) == 1  # never created a second one
    assert job_repo.jobs[pending_resume_job.job_id].status == BackgroundJobStatus.QUEUED
    assert pending_resume_job.job_id in queue.enqueued


async def test_reconcile_requeues_an_enqueue_failed_resume_job() -> None:
    """Scenario 3: a resume job whose own queue publication failed
    (status FAILED, error_code ENQUEUE_FAILED) is safely requeued."""
    account_id = uuid4()
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    service, job_repo, uow, queue = _build_service(
        live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo,
    )
    async with uow as active_uow:
        await active_uow.background_jobs.create(await _fake_terminal_job(research_job_id, account_id))
        failed_resume_job = await active_uow.background_jobs.create(
            await _fake_resume_job(
                run_id=run.run_id, research_job_id=research_job_id, status=BackgroundJobStatus.FAILED,
                result_summary={"error_code": "ENQUEUE_FAILED"},
            )
        )

    recovered_count = await service.reconcile_waiting_coach_runs(batch_size=10)

    assert recovered_count == 1
    assert job_repo.jobs[failed_resume_job.job_id].status == BackgroundJobStatus.QUEUED
    assert failed_resume_job.job_id in queue.enqueued


async def test_reconcile_never_requeues_a_resume_job_failed_for_a_different_reason() -> None:
    """A `FAILED` resume job whose failure was a genuine business
    decision (e.g. an ownership mismatch) must never be automatically
    retried - only an `ENQUEUE_FAILED` failure is safely automatic."""
    account_id = uuid4()
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    service, job_repo, uow, queue = _build_service(
        live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo,
    )
    async with uow as active_uow:
        await active_uow.background_jobs.create(await _fake_terminal_job(research_job_id, account_id))
        failed_resume_job = await active_uow.background_jobs.create(
            await _fake_resume_job(
                run_id=run.run_id, research_job_id=research_job_id, status=BackgroundJobStatus.FAILED,
                result_summary={"error_code": "OWNERSHIP_MISMATCH"},
            )
        )

    recovered_count = await service.reconcile_waiting_coach_runs(batch_size=10)

    assert recovered_count == 0
    assert job_repo.jobs[failed_resume_job.job_id].status == BackgroundJobStatus.FAILED
    assert queue.enqueued == []


# -- G2D2/H1 correction pass, section 9: expiring a WAITING_FOR_RESEARCH run past its own deadline -----------------------------------------------


def _waiting_run_with_deadline(*, research_job_id, research_deadline_at) -> tuple[FakeRunRepo, LearningOrchestratorRun]:
    run_repo = FakeRunRepo()
    run = LearningOrchestratorRun(
        thread_id=uuid4(), learner_id=uuid4(), trusted_account_id=uuid4(), idempotency_key=f"key-{uuid4()}",
        correlation_id=str(uuid4()), graph_version="learning-coach-graph-v1",
        status=LearningOrchestratorRunStatus.WAITING_FOR_RESEARCH, waiting_at=NOW, research_job_id=research_job_id,
        research_deadline_at=research_deadline_at,
    )
    run_repo.runs[run.run_id] = run
    return run_repo, run


async def test_expires_a_waiting_for_research_run_past_its_deadline() -> None:
    from datetime import timedelta

    run_repo, run = _waiting_run_with_deadline(research_job_id=uuid4(), research_deadline_at=NOW - timedelta(seconds=1))
    service, _job_repo, _uow, _queue = _build_service(
        live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo,
    )

    expired_count = await service.expire_stale_waiting_for_research_runs(batch_size=10)

    assert expired_count == 1
    assert run_repo.runs[run.run_id].status == LearningOrchestratorRunStatus.EXPIRED
    assert run_repo.runs[run.run_id].completed_at == NOW


async def test_does_not_expire_a_waiting_for_research_run_still_within_its_deadline() -> None:
    from datetime import timedelta

    run_repo, run = _waiting_run_with_deadline(research_job_id=uuid4(), research_deadline_at=NOW + timedelta(seconds=60))
    service, _job_repo, _uow, _queue = _build_service(
        live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo,
    )

    expired_count = await service.expire_stale_waiting_for_research_runs(batch_size=10)

    assert expired_count == 0
    assert run_repo.runs[run.run_id].status == LearningOrchestratorRunStatus.WAITING_FOR_RESEARCH


async def test_expire_stale_waiting_for_research_returns_zero_when_lock_unavailable() -> None:
    from datetime import timedelta

    run_repo, run = _waiting_run_with_deadline(research_job_id=uuid4(), research_deadline_at=NOW - timedelta(seconds=1))
    lock = FakeLock(available=False)
    service, _job_repo, _uow, _queue = _build_service(
        live_research_handler=OkLiveResearchHandler(result_summary={}), run_repo=run_repo, lock=lock,
    )

    expired_count = await service.expire_stale_waiting_for_research_runs(batch_size=10)

    assert expired_count == 0
    assert run_repo.runs[run.run_id].status == LearningOrchestratorRunStatus.WAITING_FOR_RESEARCH


async def test_terminal_commit_and_resume_survive_redis_release_failure() -> None:
    run_repo = FakeRunRepo()
    limiters = []
    def limiter_factory(uow):
        limiter = FakeAccountLimiter(uow=uow, fail=True)
        limiters.append(limiter)
        return limiter
    service, job_repo, _uow, _queue = _build_service(
        live_research_handler=OkLiveResearchHandler(result_summary={"research_run_status": "COMPLETED"}),
        run_repo=run_repo, limiter_factory=limiter_factory,
    )
    creation = await service.create_job(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        raw_parameters={"original_question": "question", "scope": "NEWS_SCAN", "subject_raw_text": "question"},
        idempotency_key=f"key-{uuid4()}", trigger_source=JobTriggerSource.SYSTEM,
        requested_by_account_id=uuid4(),
    )
    run = _waiting_run(research_job_id=creation.job.job_id)
    run_repo.runs[run.run_id] = run

    result = await service.execute_job(job_id=creation.job.job_id, worker_name="w", celery_task_id="c")

    assert result.status == BackgroundJobStatus.SUCCEEDED
    assert job_repo.jobs[creation.job.job_id].status == BackgroundJobStatus.SUCCEEDED
    assert len([j for j in job_repo.jobs.values() if j.job_type == BackgroundJobType.COACH_RESEARCH_RESUME]) == 1
    assert len(limiters[0].releases) == 1


@pytest.mark.parametrize("handler", [
    OkLiveResearchHandler(result_summary={"research_run_status": "COMPLETED"}),
    FailingLiveResearchHandler(),
])
async def test_success_and_provider_failure_release_after_commit(handler) -> None:
    run_repo = FakeRunRepo()
    limiters = []
    def limiter_factory(uow):
        limiter = FakeAccountLimiter(uow=uow)
        limiters.append(limiter)
        return limiter
    service, _jobs, _uow, _queue = _build_service(
        live_research_handler=handler, run_repo=run_repo, limiter_factory=limiter_factory,
    )
    creation = await service.create_job(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        raw_parameters={"original_question": "question", "scope": "NEWS_SCAN", "subject_raw_text": "question"},
        idempotency_key=f"key-{uuid4()}", trigger_source=JobTriggerSource.SYSTEM,
        requested_by_account_id=uuid4(),
    )
    run = _waiting_run(research_job_id=creation.job.job_id)
    run_repo.runs[run.run_id] = run
    await service.execute_job(job_id=creation.job.job_id, worker_name="w", celery_task_id="c")
    assert limiters[0].releases == [(run.trusted_account_id, str(run.run_id))]


async def test_cancellation_releases_and_duplicate_release_is_harmless() -> None:
    research_job_id = uuid4()
    run_repo, run = _waiting_run_repo(research_job_id=research_job_id)
    limiters = []
    def limiter_factory(uow):
        limiter = FakeAccountLimiter(uow=uow)
        limiters.append(limiter)
        return limiter
    service, _jobs, uow, _queue = _build_service(
        live_research_handler=OkLiveResearchHandler(result_summary={}),
        run_repo=run_repo, limiter_factory=limiter_factory,
    )
    from stock_research_core.domain.operations.models import BackgroundJob
    async with uow as active_uow:
        await active_uow.background_jobs.create(BackgroundJob(
            job_id=research_job_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
            status=BackgroundJobStatus.QUEUED, trigger_source=JobTriggerSource.SYSTEM,
            requested_by_account_id=run.trusted_account_id, idempotency_key=f"key-{research_job_id}",
            queue_name="finquest.research", task_name="finquest.live_research_run_execution",
        ))
        await active_uow.commit()

    cancelled = await service.cancel_job(research_job_id)
    await service._release_terminal_reservation_after_commit(cancelled)  # noqa: SLF001

    assert cancelled.status == BackgroundJobStatus.CANCELLED
    assert len(limiters[0].releases) == 2