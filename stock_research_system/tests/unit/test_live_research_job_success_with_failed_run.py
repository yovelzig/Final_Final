"""Proof (Phase G2B amendment): a `LIVE_RESEARCH_RUN_EXECUTION`
`BackgroundJob` can be technically `SUCCEEDED` while its own
`ResearchRun` is unambiguously `FAILED`/`NO_EVIDENCE_FOUND` - and that
this is discoverable purely from `HandlerOutcome.result_summary` (which
`BackgroundJobService._record_success` stores verbatim as
`BackgroundJob.result_summary`), without needing to separately query the
Live Research domain tables.

Runs the real `LiveResearchRunExecutionJobHandler` through the real
`BackgroundJobService.create_job`/`execute_job` (no Redis/Celery/
PostgreSQL - in-memory fakes for every port, same style as
`test_job_service.py`/`test_job_execution_context.py`), with a fake
`ResearchRequestService` and a fake discovery provider that returns zero
candidates. The job type's real registered retry policy is used, so
"fails non-retryably" is a statement about production wiring.

Every job created here carries a trusted requester identity, since the
handler rejects a requester-less context outright (G2B Correction V3,
item 1) - that rejection has its own tests at the bottom of this file,
proven through the same real `BackgroundJobService`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from stock_research_core.application.live_research.provider_models import ProviderFetchResult
from stock_research_core.application.operations.handlers import LiveResearchRunExecutionJobHandler
from stock_research_core.application.operations.job_registry import (
    BackgroundJobRegistry,
    JobRegistryEntry,
    NeverRetryPolicy,
    build_default_retry_policies,
)
from stock_research_core.application.operations.models import (
    LiveResearchRunExecutionParameters,
    PortfolioValuationParameters,
)
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.operations.enums import BackgroundJobStatus, BackgroundJobType, JobTriggerSource

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# -- minimal in-memory fakes for BackgroundJobService (mirrors test_job_service.py) -----------------------------------------------


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


# -- fakes for the Live Research domain service + provider (mirrors test_live_research_run_execution_handler.py) -----------------------------------------------


class FakeResearchRequestService:
    def __init__(self) -> None:
        self.fail_run_calls: list[dict] = []
        self.complete_run_calls: list = []
        self.submit_calls: list[dict] = []
        self.request_id = uuid4()
        self.run_id = uuid4()

    async def submit_request(self, *, account_id, integration_id, idempotency_key, original_question, scope, subject_security_id, subject_raw_text):
        self.submit_calls.append({"account_id": account_id, "integration_id": integration_id, "idempotency_key": idempotency_key})
        return SimpleNamespace(request=SimpleNamespace(request_id=self.request_id), created=True)

    async def create_next_run(self, request_id):
        return SimpleNamespace(run_id=self.run_id, attempt_number=1)

    async def start_run(self, run_id):
        return SimpleNamespace(run_id=run_id, attempt_number=1)

    async def record_evidence(self, run_id, **kwargs):
        raise AssertionError("no candidate should ever be recorded in this scenario")

    async def complete_run(self, run_id):
        self.complete_run_calls.append(run_id)
        return SimpleNamespace()

    async def fail_run(self, run_id, *, failure_category, message, retryable):
        self.fail_run_calls.append(
            {"run_id": run_id, "failure_category": failure_category, "message": message, "retryable": retryable}
        )
        return SimpleNamespace()


class FakeDiscoveryProviderWithNoResults:
    """Both required provider calls "succeed" - they just return zero
    candidates, which is the scenario this amendment concerns."""

    async def search(self, request):
        return ProviderFetchResult(provider_name="perplexity_search", candidates=[])


def _build_service_with_live_research_handler():
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=FakeResearchRequestService(),
        discovery_search_provider=FakeDiscoveryProviderWithNoResults(),
        official_company_data_provider=None,
        jobs_enabled=True,
    )
    # BackgroundJobRegistry requires every BackgroundJobType to resolve to
    # an entry - only LIVE_RESEARCH_RUN_EXECUTION's entry matters here.
    entries = []
    # The real registered retry policy, so "fails non-retryably" is a
    # claim about production wiring rather than about a test-only
    # NeverRetryPolicy.
    live_research_retry_policy = build_default_retry_policies()[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
    for job_type in BackgroundJobType:
        if job_type == BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION:
            entries.append(
                JobRegistryEntry(
                    job_type=job_type, parameter_model=LiveResearchRunExecutionParameters, queue_name="finquest.research",
                    task_name="finquest.live_research_run_execution", handler=handler, maximum_attempts=4,
                    retry_policy=live_research_retry_policy, time_limit_seconds=180,
                    resource_key_builder=lambda context, p: None,
                    allowed_trigger_sources=frozenset(JobTriggerSource),
                )
            )
        else:
            entries.append(
                JobRegistryEntry(
                    job_type=job_type, parameter_model=PortfolioValuationParameters, queue_name="finquest.default",
                    task_name=f"finquest.{job_type.value.lower()}", handler=object(), maximum_attempts=3,
                    retry_policy=NeverRetryPolicy(), time_limit_seconds=60, resource_key_builder=lambda context, p: None,
                    allowed_trigger_sources=frozenset(JobTriggerSource),
                )
            )
    registry = BackgroundJobRegistry(entries)

    job_repo, attempt_repo, event_repo, queue = FakeJobRepo(), FakeAttemptRepo(), FakeEventRepo(), FakeQueue()

    def _uow_factory():
        return FakeUow(job_repo, attempt_repo, event_repo)

    service = BackgroundJobService(
        unit_of_work_factory=_uow_factory, job_registry=registry, job_queue=queue, lock_port=FakeLock(), clock=lambda: NOW,
    )
    return service, handler


_NEWS_SCAN_PARAMETERS = {
    "original_question": "Any recent news on Acme Corp?",
    "scope": "NEWS_SCAN",
    "subject_raw_text": "Acme Corp",
}


class TestSucceededJobExposesFailedNoEvidenceFoundRun:
    """The literal proof requested: a technically `SUCCEEDED`
    `BackgroundJob` unambiguously exposes `research_run_status=FAILED`,
    `failure_category=NO_EVIDENCE_FOUND` in its own `result_summary`.

    Every job here is created with a trusted requester identity (G2B
    Correction V3, item 3): the proof must hold for a job the handler
    would actually accept, not for a requester-less context that the
    handler now rejects outright.
    """

    @pytest.mark.asyncio
    async def test_job_succeeds_while_result_summary_shows_a_failed_no_evidence_found_run(self) -> None:
        service, handler = _build_service_with_live_research_handler()
        account_id = uuid4()

        created = await service.create_job(
            job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
            raw_parameters=dict(_NEWS_SCAN_PARAMETERS),
            idempotency_key="k1",
            trigger_source=JobTriggerSource.ADMIN_CLI,
            requested_by_account_id=account_id,
        )
        result = await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        # The BackgroundJob is technically SUCCEEDED ...
        assert result.status == BackgroundJobStatus.SUCCEEDED

        # ... yet its own result_summary unambiguously exposes a FAILED,
        # NO_EVIDENCE_FOUND ResearchRun - this is not a contradiction, it
        # is the documented, intended outcome for this scenario.
        assert result.result_summary["research_run_status"] == "FAILED"
        assert result.result_summary["failure_category"] == "NO_EVIDENCE_FOUND"
        assert result.result_summary["evidence_recorded"] == 0

    @pytest.mark.asyncio
    async def test_the_underlying_research_request_service_actually_failed_the_run(self) -> None:
        """Cross-checks the same fact from the other side: the fake
        `ResearchRequestService.fail_run` (not `complete_run`) was the
        one actually invoked, with the exact category/retryable pair."""
        service, handler = _build_service_with_live_research_handler()
        research_service: FakeResearchRequestService = handler._research_request_service  # noqa: SLF001 - test introspection
        account_id = uuid4()

        created = await service.create_job(
            job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
            raw_parameters=dict(_NEWS_SCAN_PARAMETERS),
            idempotency_key="k2", trigger_source=JobTriggerSource.ADMIN_CLI,
            requested_by_account_id=account_id,
        )
        result = await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        assert result.status == BackgroundJobStatus.SUCCEEDED
        assert research_service.complete_run_calls == []
        assert len(research_service.fail_run_calls) == 1
        assert research_service.fail_run_calls[0]["failure_category"].value == "NO_EVIDENCE_FOUND"
        assert research_service.fail_run_calls[0]["retryable"] is False

    @pytest.mark.asyncio
    async def test_the_trusted_requester_reached_the_research_request_service(self) -> None:
        """The proof above is only meaningful for an accepted requester,
        so this pins down that the identity `create_job` was given (never
        anything from `raw_parameters`) is what `submit_request` received."""
        service, handler = _build_service_with_live_research_handler()
        research_service: FakeResearchRequestService = handler._research_request_service  # noqa: SLF001 - test introspection
        account_id = uuid4()

        created = await service.create_job(
            job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
            raw_parameters=dict(_NEWS_SCAN_PARAMETERS),
            idempotency_key="k3", trigger_source=JobTriggerSource.ADMIN_CLI,
            requested_by_account_id=account_id,
        )
        await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        assert len(research_service.submit_calls) == 1
        assert research_service.submit_calls[0]["account_id"] == account_id
        assert research_service.submit_calls[0]["integration_id"] is None
        assert research_service.submit_calls[0]["idempotency_key"] == "k3"
        assert "requested_by_account_id" not in created.job.parameters

    @pytest.mark.asyncio
    async def test_an_integration_requester_is_equally_accepted(self) -> None:
        service, handler = _build_service_with_live_research_handler()
        research_service: FakeResearchRequestService = handler._research_request_service  # noqa: SLF001 - test introspection
        integration_id = uuid4()

        created = await service.create_job(
            job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
            raw_parameters=dict(_NEWS_SCAN_PARAMETERS),
            idempotency_key="k4", trigger_source=JobTriggerSource.ADMIN_CLI,
            requested_by_integration_id=integration_id,
        )
        result = await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        assert result.status == BackgroundJobStatus.SUCCEEDED
        assert research_service.submit_calls[0]["account_id"] is None
        assert research_service.submit_calls[0]["integration_id"] == integration_id


class TestRequesterLessJobFailsNonRetryablyThroughTheRealService:
    """G2B Correction V3, item 1, proven through the real
    `BackgroundJobService`: a `LIVE_RESEARCH_RUN_EXECUTION` job created
    with no requester identity at all (which `create_job` itself permits,
    since it is generic across all 14 job types) is rejected by the
    handler, fails the job non-retryably, and never reaches the domain
    service or the provider."""

    @pytest.mark.asyncio
    async def test_no_requester_identity_fails_the_job_before_any_domain_call(self) -> None:
        service, handler = _build_service_with_live_research_handler()
        research_service: FakeResearchRequestService = handler._research_request_service  # noqa: SLF001 - test introspection

        created = await service.create_job(
            job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
            raw_parameters=dict(_NEWS_SCAN_PARAMETERS),
            idempotency_key="k5", trigger_source=JobTriggerSource.SYSTEM,
        )
        result = await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        # FAILED, not RETRY_SCHEDULED: retrying cannot add an identity.
        assert result.status == BackgroundJobStatus.FAILED
        assert result.result_summary["error_type"] == "LiveResearchRequesterContextError"
        assert research_service.submit_calls == []
        assert research_service.complete_run_calls == []
        assert research_service.fail_run_calls == []

    @pytest.mark.asyncio
    async def test_both_requester_identities_fail_the_job_before_any_domain_call(self) -> None:
        service, handler = _build_service_with_live_research_handler()
        research_service: FakeResearchRequestService = handler._research_request_service  # noqa: SLF001 - test introspection

        created = await service.create_job(
            job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
            raw_parameters=dict(_NEWS_SCAN_PARAMETERS),
            idempotency_key="k6", trigger_source=JobTriggerSource.SYSTEM,
            requested_by_account_id=uuid4(), requested_by_integration_id=uuid4(),
        )
        result = await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

        assert result.status == BackgroundJobStatus.FAILED
        assert result.result_summary["error_type"] == "LiveResearchRequesterContextError"
        assert research_service.submit_calls == []
