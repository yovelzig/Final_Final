"""PostgreSQL integration tests: `LiveResearchRunExecutionJobHandler`
running against the real `SqlAlchemyUnitOfWork`/`ResearchRequestService`
(Phase G2B), with fake `DiscoverySearchProviderPort`/
`OfficialCompanyDataProviderPort` implementations - no real network call
to Perplexity or SEC EDGAR is ever made. Skipped cleanly (via
`tests/integration/conftest.py`) when no test PostgreSQL is reachable.

Most tests call `handler.handle` directly with a trusted
`JobExecutionContext`. The `_build_real_job_service` tests go one layer
further out and drive the real `BackgroundJobService.create_job`/
`execute_job` over the same real PostgreSQL Unit of Work and the real
`build_default_registry` wiring - only the Celery queue and the Redis
lock are faked - to prove the trusted requester survives the whole
chain onto the persisted `ResearchRequest` row.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from stock_research_core.application.exceptions import (
    LiveResearchJobProviderNotConfiguredError,
    LiveResearchProviderTimeoutError,
)
from stock_research_core.application.live_research.provider_models import ExternalEvidenceCandidate, ProviderFetchResult
from stock_research_core.application.live_research.service import ResearchRequestService
from stock_research_core.application.operations.handlers import LiveResearchRunExecutionJobHandler
from stock_research_core.application.operations.job_registry import build_default_registry
from stock_research_core.application.operations.models import LiveResearchRunExecutionParameters
from stock_research_core.application.operations.ports import JobExecutionContext
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.live_research.enums import (
    EvidenceClassification,
    FailureCategory,
    ResearchRunStatus,
    ResearchScope,
    SourceType,
)
from stock_research_core.domain.identity.models import UserAccount
from stock_research_core.domain.operations.enums import BackgroundJobStatus, BackgroundJobType, JobTriggerSource
from stock_research_core.infrastructure.database.orm.research_request import ResearchRequestORM
from stock_research_core.infrastructure.database.orm.research_run import ResearchRunORM

pytestmark = pytest.mark.integration


class _NoopProgress:
    async def report(self, *, current, total=None, message=None):
        pass


class _FakeDiscoveryProvider:
    """No `httpx`, no network - returns pre-built `ProviderFetchResult`s
    or raises a pre-built exception."""

    def __init__(self, *, result: ProviderFetchResult | None = None, exception: Exception | None = None) -> None:
        self._result = result
        self._exception = exception
        self.calls: list = []

    async def search(self, request):
        self.calls.append(request)
        if self._exception is not None:
            raise self._exception
        return self._result


class _FakeOfficialCompanyDataProvider:
    def __init__(
        self, *, submissions_result: ProviderFetchResult | None = None, company_facts_result: ProviderFetchResult | None = None,
    ) -> None:
        self._submissions_result = submissions_result
        self._company_facts_result = company_facts_result
        self.submissions_calls: list = []
        self.company_facts_calls: list = []

    async def fetch_submissions(self, request):
        self.submissions_calls.append(request)
        return self._submissions_result

    async def fetch_company_facts(self, request):
        self.company_facts_calls.append(request)
        return self._company_facts_result


def _discovery_candidate(title: str = "News item") -> ExternalEvidenceCandidate:
    return ExternalEvidenceCandidate(
        source_type=SourceType.DISCOVERY_ONLY, classification=EvidenceClassification.NON_OFFICIAL,
        source_url="https://news.example.com/a", source_title=title, publisher="news.example.com",
        raw_excerpt="Some discovered text.",
    )


def _submissions_candidate(title: str = "10-K filing") -> ExternalEvidenceCandidate:
    return ExternalEvidenceCandidate(
        source_type=SourceType.SEC_OFFICIAL_FILING, classification=EvidenceClassification.OFFICIAL,
        official_identifier="0000320193-24-000001", source_title=title, publisher="SEC EDGAR",
        raw_excerpt="A filing excerpt.",
    )


def _company_facts_candidate(title: str = "Assets fact") -> ExternalEvidenceCandidate:
    return ExternalEvidenceCandidate(
        source_type=SourceType.EXCHANGE_REGULATOR_GOVERNMENT, classification=EvidenceClassification.OFFICIAL,
        official_identifier="0000320193-companyfacts", source_title=title, publisher="SEC EDGAR",
        structured_facts={"Assets": 1000},
    )


def _context(*, idempotency_key: str | None = None) -> JobExecutionContext:
    return JobExecutionContext(
        job_id=uuid4(), job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, trigger_source=JobTriggerSource.ADMIN_CLI,
        requested_by_account_id=uuid4(), requested_by_integration_id=None,
        idempotency_key=idempotency_key or f"key-{uuid4().hex[:8]}", correlation_id=None, attempt_number=1,
    )


def _params(scope: ResearchScope, **overrides) -> LiveResearchRunExecutionParameters:
    fields: dict = {"original_question": "What is happening with Acme Corp?", "scope": scope, "subject_raw_text": "Acme Corp"}
    if scope == ResearchScope.FINANCIAL_FILING_REVIEW:
        fields["sec_cik"] = "320193"
    if scope == ResearchScope.COMPANY_OVERVIEW:
        fields["sec_cik"] = "320193"
        fields["sec_concepts"] = ["Assets"]
    fields.update(overrides)
    return LiveResearchRunExecutionParameters(**fields)


async def test_news_scan_persists_discovery_evidence_as_discovery_only_non_official(uow_factory) -> None:
    service = ResearchRequestService(unit_of_work_factory=uow_factory)
    discovery = _FakeDiscoveryProvider(
        result=ProviderFetchResult(provider_name="perplexity_search", candidates=[_discovery_candidate()])
    )
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=discovery,
        official_company_data_provider=None, jobs_enabled=True,
    )
    context = _context()
    outcome = await handler.handle(context=context, parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

    assert outcome.result_summary["evidence_recorded"] == 1
    assert len(discovery.calls) == 1

    async with uow_factory() as uow:
        request = await uow.research_requests.get(UUID(outcome.result_summary["research_request_id"]))
        run = await uow.research_runs.get(UUID(outcome.result_summary["research_run_id"]))
        evidence_items = await uow.evidence_items.list_for_run(run.run_id)

    assert request is not None
    assert run.status == ResearchRunStatus.COMPLETED
    assert len(evidence_items) == 1
    assert evidence_items[0].source_type == SourceType.DISCOVERY_ONLY
    assert evidence_items[0].classification == EvidenceClassification.NON_OFFICIAL
    assert outcome.result_summary["research_run_status"] == "COMPLETED"
    assert outcome.result_summary["failure_category"] is None


async def test_financial_filing_review_persists_sec_official_filing_official(uow_factory) -> None:
    service = ResearchRequestService(unit_of_work_factory=uow_factory)
    official = _FakeOfficialCompanyDataProvider(
        submissions_result=ProviderFetchResult(provider_name="sec_edgar", candidates=[_submissions_candidate()])
    )
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=None,
        official_company_data_provider=official, jobs_enabled=True,
    )
    context = _context()
    outcome = await handler.handle(
        context=context, parameters=_params(ResearchScope.FINANCIAL_FILING_REVIEW), progress=_NoopProgress()
    )

    assert outcome.result_summary["evidence_recorded"] == 1
    assert official.submissions_calls[0].cik == "0000320193"

    async with uow_factory() as uow:
        run = await uow.research_runs.get(UUID(outcome.result_summary["research_run_id"]))
        evidence_items = await uow.evidence_items.list_for_run(run.run_id)

    assert run.status == ResearchRunStatus.COMPLETED
    assert evidence_items[0].source_type == SourceType.SEC_OFFICIAL_FILING
    assert evidence_items[0].classification == EvidenceClassification.OFFICIAL


async def test_company_overview_persists_company_facts_as_exchange_regulator_government_official(uow_factory) -> None:
    service = ResearchRequestService(unit_of_work_factory=uow_factory)
    official = _FakeOfficialCompanyDataProvider(
        company_facts_result=ProviderFetchResult(provider_name="sec_edgar", candidates=[_company_facts_candidate()])
    )
    discovery = _FakeDiscoveryProvider(result=ProviderFetchResult(provider_name="perplexity_search", candidates=[_discovery_candidate()]))
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=discovery,
        official_company_data_provider=official, jobs_enabled=True,
    )
    context = _context()
    outcome = await handler.handle(
        context=context, parameters=_params(ResearchScope.COMPANY_OVERVIEW), progress=_NoopProgress()
    )

    assert outcome.result_summary["evidence_recorded"] == 2

    async with uow_factory() as uow:
        run = await uow.research_runs.get(UUID(outcome.result_summary["research_run_id"]))
        evidence_items = await uow.evidence_items.list_for_run(run.run_id)

    by_source = {item.source_type: item for item in evidence_items}
    assert by_source[SourceType.EXCHANGE_REGULATOR_GOVERNMENT].classification == EvidenceClassification.OFFICIAL
    assert by_source[SourceType.DISCOVERY_ONLY].classification == EvidenceClassification.NON_OFFICIAL


async def test_duplicate_candidate_within_the_same_run_is_skipped(uow_factory) -> None:
    service = ResearchRequestService(unit_of_work_factory=uow_factory)
    same_candidate = _discovery_candidate(title="Repeated item")
    discovery = _FakeDiscoveryProvider(
        result=ProviderFetchResult(provider_name="perplexity_search", candidates=[same_candidate, same_candidate])
    )
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=discovery,
        official_company_data_provider=None, jobs_enabled=True,
    )
    context = _context()
    outcome = await handler.handle(context=context, parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

    assert outcome.result_summary["evidence_recorded"] == 1
    assert outcome.result_summary["duplicates_skipped"] == 1


async def test_zero_evidence_persists_a_failed_no_evidence_found_run_without_raising(uow_factory) -> None:
    """The amendment's core scenario, proven end to end against real
    PostgreSQL: all required provider calls succeed (zero candidates is
    a legitimate empty result, not an error) - `handle()` returns
    normally (a real `BackgroundJobService` would mark this job
    SUCCEEDED), while the persisted `ResearchRun` and the handler's own
    `result_summary` both unambiguously show FAILED/NO_EVIDENCE_FOUND.
    """
    service = ResearchRequestService(unit_of_work_factory=uow_factory)
    discovery = _FakeDiscoveryProvider(result=ProviderFetchResult(provider_name="perplexity_search", candidates=[]))
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=discovery,
        official_company_data_provider=None, jobs_enabled=True,
    )
    context = _context()
    # No exception - this is what allows a real BackgroundJobService to
    # mark the job SUCCEEDED despite the run having failed.
    outcome = await handler.handle(context=context, parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

    assert outcome.result_summary["evidence_recorded"] == 0
    assert outcome.result_summary["research_run_status"] == "FAILED"
    assert outcome.result_summary["failure_category"] == "NO_EVIDENCE_FOUND"

    async with uow_factory() as uow:
        run = await uow.research_runs.get(UUID(outcome.result_summary["research_run_id"]))
        evidence_items = await uow.evidence_items.list_for_run(run.run_id)

    assert run.status == ResearchRunStatus.FAILED
    assert run.failure_category == FailureCategory.NO_EVIDENCE_FOUND
    assert run.retryable is False
    assert evidence_items == []


async def test_provider_failure_creates_a_failed_research_run(uow_factory) -> None:
    service = ResearchRequestService(unit_of_work_factory=uow_factory)
    discovery = _FakeDiscoveryProvider(exception=LiveResearchProviderTimeoutError("upstream timed out"))
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=discovery,
        official_company_data_provider=None, jobs_enabled=True,
    )
    context = _context()
    with pytest.raises(LiveResearchProviderTimeoutError):
        await handler.handle(context=context, parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

    async with uow_factory() as uow:
        request = await uow.research_requests.get_by_idempotency_key(
            requester_key=f"account:{context.requested_by_account_id}", idempotency_key=context.idempotency_key,
        )
        runs = await uow.research_runs.list_for_request(request.request_id)

    assert len(runs) == 1
    assert runs[0].status == ResearchRunStatus.FAILED
    assert runs[0].failure_category == FailureCategory.TIMEOUT
    assert runs[0].retryable is True


async def test_a_retry_after_a_transient_failure_creates_a_new_research_run_attempt(uow_factory) -> None:
    """Mirrors what `BackgroundJobService`'s job-level retry does: it
    calls `handle()` again with the same trusted context - since the
    prior `ResearchRun` is now terminal (FAILED), `submit_request` is
    idempotent (same request row) but `create_next_run` creates a *new*
    run with the next `attempt_number`, never reactivating the failed one.
    """
    service = ResearchRequestService(unit_of_work_factory=uow_factory)
    context = _context()
    parameters = _params(ResearchScope.NEWS_SCAN)

    failing_discovery = _FakeDiscoveryProvider(exception=LiveResearchProviderTimeoutError("transient"))
    failing_handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=failing_discovery,
        official_company_data_provider=None, jobs_enabled=True,
    )
    with pytest.raises(LiveResearchProviderTimeoutError):
        await failing_handler.handle(context=context, parameters=parameters, progress=_NoopProgress())

    succeeding_discovery = _FakeDiscoveryProvider(
        result=ProviderFetchResult(provider_name="perplexity_search", candidates=[_discovery_candidate()])
    )
    retry_handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=succeeding_discovery,
        official_company_data_provider=None, jobs_enabled=True,
    )
    outcome = await retry_handler.handle(context=context, parameters=parameters, progress=_NoopProgress())
    assert outcome.result_summary["research_attempt_number"] == 2

    async with uow_factory() as uow:
        request = await uow.research_requests.get_by_idempotency_key(
            requester_key=f"account:{context.requested_by_account_id}", idempotency_key=context.idempotency_key,
        )
        runs = await uow.research_runs.list_for_request(request.request_id)

    assert len(runs) == 2
    statuses = {run.attempt_number: run.status for run in runs}
    assert statuses[1] == ResearchRunStatus.FAILED
    assert statuses[2] == ResearchRunStatus.COMPLETED


class _FakeQueue:
    """No Celery: records the delivery that would have happened."""

    def __init__(self) -> None:
        self.enqueued: list = []

    async def enqueue(self, *, job_id, job_type, queue_name, priority, available_at):
        self.enqueued.append(job_id)
        return f"task-{job_id}"


class _FakeLock:
    """No Redis: the resource lock always succeeds, which is what a
    single-worker test needs. Lock behavior itself is covered by
    `tests/unit/test_live_research_locking.py` and
    `tests/integration/test_job_concurrency.py`."""

    async def acquire(self, *, key, owner_id, ttl_seconds, wait_timeout_seconds):
        return True

    async def release(self, *, key, owner_id):
        return True

    async def extend(self, *, key, owner_id, ttl_seconds):
        return True


async def _create_real_account(uow_factory) -> UUID:
    """`background_jobs.requested_by_account_id` carries a real foreign key
    to `user_accounts` (unlike `research_requests.requested_by_account_id`,
    which does not), so a job created with an account requester needs a
    genuine account row - which also makes this a truer end-to-end test
    than a bare `uuid4()` would be."""
    async with uow_factory() as uow:
        email = f"live-research-requester-{uuid4().hex[:10]}@example.com"
        account = await uow.user_accounts.create_account(
            account=UserAccount(email=email, normalized_email=email, display_name="Live Research Requester"),
            password_hash="not-a-real-hash",
        )
        await uow.commit()
    return account.account_id


def _build_real_job_service(uow_factory, *, live_research_handler):
    """A real `BackgroundJobService` on the real PostgreSQL Unit of Work,
    wired through the real `build_default_registry` (so the registered
    parameter model, queue, retry policy and resource-key builder are the
    production ones) with only the queue and lock faked out."""
    handlers: dict = {job_type: object() for job_type in BackgroundJobType}
    handlers[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION] = live_research_handler
    return BackgroundJobService(
        unit_of_work_factory=uow_factory, job_registry=build_default_registry(handlers),
        job_queue=_FakeQueue(), lock_port=_FakeLock(),
    )


async def test_a_real_background_job_execution_persists_the_trusted_requester_on_the_research_request(
    uow_factory,
) -> None:
    """G2B Correction V3, item 3: the whole chain, no fakes except the
    provider/queue/lock - real `BackgroundJobService.create_job` +
    `execute_job`, real registry, real `LiveResearchRunExecutionJobHandler`,
    real `ResearchRequestService`, real PostgreSQL. The trusted requester
    `create_job` was given must arrive at `submit_request` and be
    persisted on the `ResearchRequest` row.
    """
    account_id = await _create_real_account(uow_factory)
    discovery = _FakeDiscoveryProvider(
        result=ProviderFetchResult(provider_name="perplexity_search", candidates=[_discovery_candidate()])
    )
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=ResearchRequestService(unit_of_work_factory=uow_factory),
        discovery_search_provider=discovery, official_company_data_provider=None, jobs_enabled=True,
    )
    service = _build_real_job_service(uow_factory, live_research_handler=handler)

    created = await service.create_job(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        raw_parameters={
            "original_question": "What is happening with Acme Corp?", "scope": "NEWS_SCAN",
            "subject_raw_text": "Acme Corp",
        },
        idempotency_key="job-key-1", trigger_source=JobTriggerSource.ADMIN_CLI,
        requested_by_account_id=account_id,
    )
    # The identity is never carried in the (untrusted) job parameters.
    assert "requested_by_account_id" not in created.job.parameters
    assert "requested_by_integration_id" not in created.job.parameters

    result = await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
    assert result.status == BackgroundJobStatus.SUCCEEDED
    assert result.result_summary["evidence_recorded"] == 1
    assert result.result_summary["research_run_status"] == "COMPLETED"

    async with uow_factory() as uow:
        request = await uow.research_requests.get(UUID(result.result_summary["research_request_id"]))
        run = await uow.research_runs.get(UUID(result.result_summary["research_run_id"]))
        evidence_items = await uow.evidence_items.list_for_run(run.run_id)
        # The same requester also identifies the request in its own
        # idempotency scope, under the shared `account:{id}` convention.
        by_requester = await uow.research_requests.get_by_idempotency_key(
            requester_key=f"account:{account_id}", idempotency_key=created.job.idempotency_key,
        )

    assert request.requested_by_account_id == account_id
    assert request.requested_by_integration_id is None
    assert by_requester is not None
    assert by_requester.request_id == request.request_id
    assert run.status == ResearchRunStatus.COMPLETED
    assert len(evidence_items) == 1


async def test_a_real_background_job_execution_persists_an_integration_requester(uow_factory) -> None:
    integration_id = uuid4()
    discovery = _FakeDiscoveryProvider(
        result=ProviderFetchResult(provider_name="perplexity_search", candidates=[_discovery_candidate()])
    )
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=ResearchRequestService(unit_of_work_factory=uow_factory),
        discovery_search_provider=discovery, official_company_data_provider=None, jobs_enabled=True,
    )
    service = _build_real_job_service(uow_factory, live_research_handler=handler)

    created = await service.create_job(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        raw_parameters={
            "original_question": "What is happening with Acme Corp?", "scope": "NEWS_SCAN",
            "subject_raw_text": "Acme Corp",
        },
        idempotency_key="job-key-2", trigger_source=JobTriggerSource.ADMIN_CLI,
        requested_by_integration_id=integration_id,
    )
    result = await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")
    assert result.status == BackgroundJobStatus.SUCCEEDED

    async with uow_factory() as uow:
        request = await uow.research_requests.get(UUID(result.result_summary["research_request_id"]))

    assert request.requested_by_integration_id == integration_id
    assert request.requested_by_account_id is None


async def test_a_real_background_job_execution_without_a_requester_persists_no_research_request(uow_factory) -> None:
    """The other half of item 3: `create_job` itself is generic across all
    job types and permits a requester-less job, so the handler is what
    must stop it - non-retryably, before any `ResearchRequest` or
    `ResearchRun` row exists, and before the provider is called.
    """
    discovery = _FakeDiscoveryProvider(
        result=ProviderFetchResult(provider_name="perplexity_search", candidates=[_discovery_candidate()])
    )
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=ResearchRequestService(unit_of_work_factory=uow_factory),
        discovery_search_provider=discovery, official_company_data_provider=None, jobs_enabled=True,
    )
    service = _build_real_job_service(uow_factory, live_research_handler=handler)

    created = await service.create_job(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        raw_parameters={
            "original_question": "What is happening with Acme Corp?", "scope": "NEWS_SCAN",
            "subject_raw_text": "Acme Corp",
        },
        idempotency_key="job-key-3", trigger_source=JobTriggerSource.SYSTEM,
    )
    result = await service.execute_job(job_id=created.job.job_id, worker_name="w1", celery_task_id="c1")

    assert result.status == BackgroundJobStatus.FAILED
    assert result.result_summary["error_type"] == "LiveResearchRequesterContextError"
    assert discovery.calls == []

    # `ResearchRequestRepositoryPort` exposes only id/idempotency lookups
    # (by design - there is no "list every request" production use case),
    # so this counts the rows directly: the assertion is that *no*
    # request was created at all, not that one particular key is absent.
    async with uow_factory() as uow:
        request_count = await uow._session.scalar(  # noqa: SLF001 - test-only introspection
            select(func.count()).select_from(ResearchRequestORM)
        )
        run_count = await uow._session.scalar(  # noqa: SLF001 - test-only introspection
            select(func.count()).select_from(ResearchRunORM)
        )
    assert request_count == 0
    assert run_count == 0


async def test_no_provider_configured_fails_before_creating_evidence(uow_factory) -> None:
    service = ResearchRequestService(unit_of_work_factory=uow_factory)
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=None,
        official_company_data_provider=None, jobs_enabled=True,
    )
    context = _context()
    with pytest.raises(LiveResearchJobProviderNotConfiguredError):
        await handler.handle(context=context, parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

    async with uow_factory() as uow:
        request = await uow.research_requests.get_by_idempotency_key(
            requester_key=f"account:{context.requested_by_account_id}", idempotency_key=context.idempotency_key,
        )
        runs = await uow.research_runs.list_for_request(request.request_id)
        evidence = await uow.evidence_items.list_for_run(runs[0].run_id)

    assert runs[0].status == ResearchRunStatus.FAILED
    assert evidence == []
