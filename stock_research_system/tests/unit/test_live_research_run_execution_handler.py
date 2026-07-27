"""Unit tests for `LiveResearchRunExecutionJobHandler` (Phase G2B).

Uses a fake, duck-typed `ResearchRequestService` (recording every call)
and fake provider ports - no real UoW/PostgreSQL/network. The real
`candidate_to_evidence_kwargs` mapping function is used unmodified, so
the disallowed-pair behavior is exercised for real, not mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import (
    DuplicateEvidenceError,
    LiveResearchJobProviderNotConfiguredError,
    LiveResearchProviderAccessError,
    LiveResearchProviderConfigurationError,
    LiveResearchProviderRateLimitError,
    LiveResearchProviderResponseError,
    LiveResearchProviderTimeoutError,
    LiveResearchRequesterContextError,
    TransientInfrastructureError,
)
from stock_research_core.application.live_research.provider_models import ExternalEvidenceCandidate, ProviderFetchResult
from stock_research_core.application.operations.handlers import LiveResearchRunExecutionJobHandler
from stock_research_core.application.operations.job_registry import build_default_retry_policies
from stock_research_core.application.operations.models import LiveResearchRunExecutionParameters
from stock_research_core.application.operations.ports import JobExecutionContext
from stock_research_core.domain.live_research.enums import EvidenceClassification, FailureCategory, ResearchScope, SourceType
from stock_research_core.domain.operations.enums import BackgroundJobType, JobTriggerSource


class _NoopProgress:
    async def report(self, *, current, total=None, message=None):
        pass


class _CountingProgress:
    """Counts `report()` calls, so a test can prove a rejection happened
    *before* the handler's very first progress report."""

    def __init__(self) -> None:
        self.calls = 0

    async def report(self, *, current, total=None, message=None):
        self.calls += 1


class _FailingNthProgress:
    """Raises on the N-th (1-indexed) `report()` call - used to prove a
    failure in the final progress report never leaves the run RUNNING
    (G2B Correction V2, item 2/7)."""

    def __init__(self, *, fail_on_call: int, exception: Exception) -> None:
        self._fail_on_call = fail_on_call
        self._exception = exception
        self.calls = 0

    async def report(self, *, current, total=None, message=None):
        self.calls += 1
        if self.calls == self._fail_on_call:
            raise self._exception


class FakeResearchRequestService:
    """Duck-typed stand-in for `ResearchRequestService`, recording every
    call the handler makes so tests can assert on exact sequencing/args
    without a real UoW/PostgreSQL."""

    def __init__(
        self, *, duplicate_titles: frozenset[str] = frozenset(),
        start_run_exception: Exception | None = None, complete_run_exception: Exception | None = None,
        record_evidence_exception: Exception | None = None, fail_run_exception_on_call: int | None = None,
        fail_run_exception: Exception | None = None,
    ) -> None:
        self.submit_calls: list[dict] = []
        self.create_next_run_calls: list = []
        self.start_run_calls: list = []
        self.record_evidence_calls: list[dict] = []
        self.complete_run_calls: list = []
        self.fail_run_calls: list[dict] = []
        #: Every service method name in invocation order - lets a test
        #: assert that nothing at all was invoked after terminalization.
        self.call_order: list[str] = []
        self._duplicate_titles = duplicate_titles
        self._start_run_exception = start_run_exception
        self._complete_run_exception = complete_run_exception
        self._record_evidence_exception = record_evidence_exception
        self._fail_run_exception_on_call = fail_run_exception_on_call
        self._fail_run_exception = fail_run_exception
        self.request_id = uuid4()
        self.run_id = uuid4()

    async def submit_request(self, *, account_id, integration_id, idempotency_key, original_question, scope, subject_security_id, subject_raw_text):
        self.submit_calls.append(locals())
        self.call_order.append("submit_request")
        return SimpleNamespace(request=SimpleNamespace(request_id=self.request_id), created=True)

    async def create_next_run(self, request_id):
        self.create_next_run_calls.append(request_id)
        self.call_order.append("create_next_run")
        return SimpleNamespace(run_id=self.run_id, attempt_number=1)

    async def start_run(self, run_id):
        self.start_run_calls.append(run_id)
        self.call_order.append("start_run")
        if self._start_run_exception is not None:
            raise self._start_run_exception
        return SimpleNamespace(run_id=run_id, attempt_number=1)

    async def record_evidence(self, run_id, **kwargs):
        self.call_order.append("record_evidence")
        if kwargs.get("source_title") in self._duplicate_titles:
            raise DuplicateEvidenceError("duplicate")
        if self._record_evidence_exception is not None:
            raise self._record_evidence_exception
        self.record_evidence_calls.append(kwargs)
        return SimpleNamespace()

    async def complete_run(self, run_id):
        self.complete_run_calls.append(run_id)
        self.call_order.append("complete_run")
        if self._complete_run_exception is not None:
            raise self._complete_run_exception
        return SimpleNamespace()

    async def fail_run(self, run_id, *, failure_category, message, retryable):
        # Recorded *before* any configured raise, so a test can count
        # attempted fail_run calls, not just successful ones.
        self.fail_run_calls.append(
            {"run_id": run_id, "failure_category": failure_category, "message": message, "retryable": retryable}
        )
        self.call_order.append("fail_run")
        if self._fail_run_exception_on_call is not None and len(self.fail_run_calls) == self._fail_run_exception_on_call:
            assert self._fail_run_exception is not None
            raise self._fail_run_exception
        return SimpleNamespace()


class FakeDiscoveryProvider:
    def __init__(self, *, result: ProviderFetchResult | None = None, exception: Exception | None = None) -> None:
        self._result = result
        self._exception = exception
        self.calls: list = []

    async def search(self, request):
        self.calls.append(request)
        if self._exception is not None:
            raise self._exception
        return self._result


class FakeOfficialCompanyDataProvider:
    def __init__(
        self, *, submissions_result=None, company_facts_result=None,
        submissions_exception=None, company_facts_exception=None,
    ) -> None:
        self._submissions_result = submissions_result
        self._company_facts_result = company_facts_result
        self._submissions_exception = submissions_exception
        self._company_facts_exception = company_facts_exception
        self.submissions_calls: list = []
        self.company_facts_calls: list = []

    async def fetch_submissions(self, request):
        self.submissions_calls.append(request)
        if self._submissions_exception is not None:
            raise self._submissions_exception
        return self._submissions_result

    async def fetch_company_facts(self, request):
        self.company_facts_calls.append(request)
        if self._company_facts_exception is not None:
            raise self._company_facts_exception
        return self._company_facts_result


def _candidate(
    *, source_type=SourceType.DISCOVERY_ONLY, classification=EvidenceClassification.NON_OFFICIAL, title="Title"
) -> ExternalEvidenceCandidate:
    return ExternalEvidenceCandidate(
        source_type=source_type, classification=classification, source_url="https://example.com/a",
        source_title=title, publisher="example.com", raw_excerpt="Some excerpt.",
    )


def _fetch_result(provider_name, *, candidates=None, provider_request_id=None) -> ProviderFetchResult:
    return ProviderFetchResult(provider_name=provider_name, provider_request_id=provider_request_id, candidates=candidates or [])


def _params(scope: ResearchScope, **overrides) -> LiveResearchRunExecutionParameters:
    fields: dict = {"original_question": "What about Acme?", "scope": scope}
    if scope != ResearchScope.GENERAL_QUESTION:
        fields["subject_raw_text"] = "Acme Corp"
    if scope == ResearchScope.FINANCIAL_FILING_REVIEW:
        fields["sec_cik"] = "320193"
    if scope == ResearchScope.COMPANY_OVERVIEW:
        fields["sec_cik"] = "320193"
        fields["sec_concepts"] = ["Assets"]
    fields.update(overrides)
    return LiveResearchRunExecutionParameters(**fields)


def _context(**overrides) -> JobExecutionContext:
    """The default test context carries exactly one trusted requester
    (an account), because that is the only shape the handler accepts -
    see `TestTrustedRequesterIdentity` and G2B Correction V3, item 1.
    Tests that need a rejected shape pass it explicitly."""
    fields = dict(
        job_id=uuid4(), job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, trigger_source=JobTriggerSource.ADMIN_CLI,
        requested_by_account_id=uuid4(), requested_by_integration_id=None, idempotency_key="k1", correlation_id=None,
        attempt_number=1,
    )
    fields.update(overrides)
    return JobExecutionContext(**fields)


def _handler(*, discovery=None, official=None, jobs_enabled=True, service=None, discovery_max_results=10):
    service = service if service is not None else FakeResearchRequestService()
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=discovery,
        official_company_data_provider=official, jobs_enabled=jobs_enabled,
        discovery_max_results=discovery_max_results,
    )
    return handler, service


class TestDisabledOrchestration:
    @pytest.mark.asyncio
    async def test_disabled_jobs_switch_makes_no_domain_or_provider_call(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search"))
        handler, service = _handler(discovery=discovery, jobs_enabled=False)
        with pytest.raises(LiveResearchJobProviderNotConfiguredError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        assert service.submit_calls == []
        assert service.create_next_run_calls == []
        assert service.start_run_calls == []
        assert service.fail_run_calls == []
        assert discovery.calls == []


class TestTrustedRequesterIdentity:
    """G2B Correction V3, item 1: the handler enforces exactly one
    trusted requester itself. `operations_admin.py`'s own check only
    covers CLI-created jobs - SYSTEM/RETRY triggers and any programmatic
    `create_job` caller reach this registered job type directly - so a
    missing or ambiguous identity must be rejected here too, before the
    first progress report, before `submit_request`, and before any
    provider call."""

    @pytest.mark.asyncio
    async def test_no_requester_raises_before_progress_submit_or_provider_call(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, service = _handler(discovery=discovery)
        progress = _CountingProgress()

        with pytest.raises(LiveResearchRequesterContextError, match="neither"):
            await handler.handle(
                context=_context(requested_by_account_id=None, requested_by_integration_id=None),
                parameters=_params(ResearchScope.NEWS_SCAN), progress=progress,
            )

        assert progress.calls == 0
        assert service.submit_calls == []
        assert service.create_next_run_calls == []
        assert service.start_run_calls == []
        assert service.record_evidence_calls == []
        # No ResearchRun exists, so there is nothing to fail.
        assert service.fail_run_calls == []
        assert discovery.calls == []

    @pytest.mark.asyncio
    async def test_both_requesters_raise_before_progress_submit_or_provider_call(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, service = _handler(discovery=discovery)
        progress = _CountingProgress()

        with pytest.raises(LiveResearchRequesterContextError, match="both"):
            await handler.handle(
                context=_context(requested_by_account_id=uuid4(), requested_by_integration_id=uuid4()),
                parameters=_params(ResearchScope.NEWS_SCAN), progress=progress,
            )

        assert progress.calls == 0
        assert service.submit_calls == []
        assert service.create_next_run_calls == []
        assert service.start_run_calls == []
        assert service.record_evidence_calls == []
        assert service.fail_run_calls == []
        assert discovery.calls == []

    @pytest.mark.asyncio
    async def test_the_error_is_not_in_the_job_types_retryable_exception_list(self) -> None:
        # Non-retryability is a property of the registry's own retry
        # policy, not of the handler - asserted against the real policy
        # so the two can never drift apart.
        policy = build_default_retry_policies()[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        decision = policy.classify(LiveResearchRequesterContextError("no identity"), attempt_number=1)
        assert decision.retryable is False

    @pytest.mark.asyncio
    async def test_disabled_orchestration_is_still_checked_before_requester_identity(self) -> None:
        # Ordering guarantee: the top-level feature switch stays the
        # outermost gate, so a disabled deployment reports "disabled"
        # rather than an identity complaint.
        handler, service = _handler(jobs_enabled=False)
        with pytest.raises(LiveResearchJobProviderNotConfiguredError):
            await handler.handle(
                context=_context(requested_by_account_id=None, requested_by_integration_id=None),
                parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress(),
            )
        assert service.submit_calls == []

    @pytest.mark.asyncio
    async def test_an_integration_identity_alone_is_accepted_and_forwarded(self) -> None:
        integration_id = uuid4()
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, service = _handler(discovery=discovery)
        await handler.handle(
            context=_context(requested_by_account_id=None, requested_by_integration_id=integration_id),
            parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress(),
        )
        assert service.submit_calls[0]["account_id"] is None
        assert service.submit_calls[0]["integration_id"] == integration_id

    @pytest.mark.asyncio
    async def test_an_account_identity_alone_is_accepted_and_forwarded(self) -> None:
        account_id = uuid4()
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, service = _handler(discovery=discovery)
        await handler.handle(
            context=_context(requested_by_account_id=account_id),
            parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress(),
        )
        assert service.submit_calls[0]["account_id"] == account_id
        assert service.submit_calls[0]["integration_id"] is None


class TestMissingRequiredProvider:
    @pytest.mark.asyncio
    async def test_missing_provider_fails_before_any_provider_call(self) -> None:
        handler, service = _handler(discovery=None, official=None, jobs_enabled=True)
        with pytest.raises(LiveResearchJobProviderNotConfiguredError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        # A ResearchRun was created and started (this is a run-level
        # failure, not a pre-run rejection), but no provider was ever called.
        assert len(service.start_run_calls) == 1
        assert len(service.fail_run_calls) == 1
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.PROVIDER_ERROR
        assert service.fail_run_calls[0]["retryable"] is False

    @pytest.mark.asyncio
    async def test_company_overview_missing_either_provider_fails(self) -> None:
        official = FakeOfficialCompanyDataProvider(company_facts_result=_fetch_result("sec_edgar"))
        handler, service = _handler(discovery=None, official=official, jobs_enabled=True)
        with pytest.raises(LiveResearchJobProviderNotConfiguredError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.COMPANY_OVERVIEW), progress=_NoopProgress())
        assert official.company_facts_calls == []


class TestPerScopeRouting:
    @pytest.mark.asyncio
    async def test_financial_filing_review_calls_fetch_submissions_only(self) -> None:
        official = FakeOfficialCompanyDataProvider(submissions_result=_fetch_result("sec_edgar"))
        handler, service = _handler(official=official)
        await handler.handle(context=_context(), parameters=_params(ResearchScope.FINANCIAL_FILING_REVIEW), progress=_NoopProgress())
        assert len(official.submissions_calls) == 1
        assert official.submissions_calls[0].cik == "0000320193"
        assert official.company_facts_calls == []

    @pytest.mark.asyncio
    async def test_company_overview_calls_both_providers(self) -> None:
        official = FakeOfficialCompanyDataProvider(
            company_facts_result=_fetch_result("sec_edgar", candidates=[_candidate(
                source_type=SourceType.EXCHANGE_REGULATOR_GOVERNMENT, classification=EvidenceClassification.OFFICIAL,
            )])
        )
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search"))
        handler, service = _handler(discovery=discovery, official=official)
        await handler.handle(context=_context(), parameters=_params(ResearchScope.COMPANY_OVERVIEW), progress=_NoopProgress())
        assert len(official.company_facts_calls) == 1
        assert official.company_facts_calls[0].cik == "0000320193"
        assert official.company_facts_calls[0].concepts == ["Assets"]
        assert len(discovery.calls) == 1

    @pytest.mark.parametrize("scope", [ResearchScope.NEWS_SCAN, ResearchScope.ANALYST_SENTIMENT, ResearchScope.GENERAL_QUESTION])
    @pytest.mark.asyncio
    async def test_discovery_only_scopes_call_search_only(self, scope: ResearchScope) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search"))
        handler, service = _handler(discovery=discovery)
        await handler.handle(context=_context(), parameters=_params(scope), progress=_NoopProgress())
        assert len(discovery.calls) == 1


class TestNoPartialPersistence:
    @pytest.mark.asyncio
    async def test_company_overview_second_call_failing_persists_nothing_from_the_first(self) -> None:
        official = FakeOfficialCompanyDataProvider(
            company_facts_result=_fetch_result("sec_edgar", candidates=[_candidate(
                source_type=SourceType.EXCHANGE_REGULATOR_GOVERNMENT, classification=EvidenceClassification.OFFICIAL,
            )])
        )
        discovery = FakeDiscoveryProvider(exception=LiveResearchProviderTimeoutError("timed out"))
        handler, service = _handler(discovery=discovery, official=official)
        with pytest.raises(LiveResearchProviderTimeoutError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.COMPANY_OVERVIEW), progress=_NoopProgress())
        assert service.record_evidence_calls == []
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.TIMEOUT
        assert service.fail_run_calls[0]["retryable"] is True


class TestDuplicateEvidence:
    @pytest.mark.asyncio
    async def test_duplicate_evidence_is_non_fatal_and_counted(self) -> None:
        candidates = [_candidate(title="dup"), _candidate(title="unique")]
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=candidates))
        service = FakeResearchRequestService(duplicate_titles=frozenset({"dup"}))
        handler, _ = _handler(discovery=discovery, service=service)
        outcome = await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())
        assert outcome.result_summary["duplicates_skipped"] == 1
        assert outcome.result_summary["evidence_recorded"] == 1
        assert service.complete_run_calls == [service.run_id]
        assert outcome.result_summary["research_run_status"] == "COMPLETED"
        assert outcome.result_summary["failure_category"] is None


class TestDisallowedPair:
    @pytest.mark.asyncio
    async def test_disallowed_pair_fails_the_run_and_propagates(self) -> None:
        bad_candidate = _candidate(source_type=SourceType.SEC_OFFICIAL_FILING, classification=EvidenceClassification.NON_OFFICIAL)
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[bad_candidate]))
        handler, service = _handler(discovery=discovery)
        with pytest.raises(LiveResearchProviderResponseError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())
        assert service.record_evidence_calls == []
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.PROVIDER_ERROR
        assert service.fail_run_calls[0]["retryable"] is False


class TestZeroEvidence:
    @pytest.mark.asyncio
    async def test_zero_evidence_after_success_yields_no_evidence_found_but_returns_normally(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[]))
        handler, service = _handler(discovery=discovery)
        outcome = await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())
        # The handler returns normally (BackgroundJob succeeds) - no exception.
        assert outcome.result_summary["evidence_recorded"] == 0
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.NO_EVIDENCE_FOUND
        assert service.fail_run_calls[0]["retryable"] is False
        assert service.complete_run_calls == []
        # The amendment: result_summary must unambiguously expose the
        # FAILED/NO_EVIDENCE_FOUND run even though handle() itself
        # returned normally (the BackgroundJob will be marked SUCCEEDED).
        assert outcome.result_summary["research_run_status"] == "FAILED"
        assert outcome.result_summary["failure_category"] == "NO_EVIDENCE_FOUND"


class TestFailureMapping:
    @pytest.mark.parametrize(
        "exception,expected_category,expected_retryable",
        [
            (LiveResearchProviderTimeoutError("x"), FailureCategory.TIMEOUT, True),
            (LiveResearchProviderRateLimitError("x"), FailureCategory.RATE_LIMITED, True),
            (LiveResearchProviderAccessError("x"), FailureCategory.PROVIDER_ERROR, False),
            (LiveResearchProviderResponseError("x"), FailureCategory.PROVIDER_ERROR, False),
            (LiveResearchProviderConfigurationError("x"), FailureCategory.PROVIDER_ERROR, False),
            (TransientInfrastructureError("x"), FailureCategory.INTERNAL_ERROR, True),
            (RuntimeError("unexpected bug"), FailureCategory.INTERNAL_ERROR, False),
        ],
    )
    @pytest.mark.asyncio
    async def test_exception_maps_to_the_documented_category(
        self, exception: Exception, expected_category: FailureCategory, expected_retryable: bool
    ) -> None:
        discovery = FakeDiscoveryProvider(exception=exception)
        handler, service = _handler(discovery=discovery)
        with pytest.raises(type(exception)):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())
        assert len(service.fail_run_calls) == 1
        assert service.fail_run_calls[0]["failure_category"] == expected_category
        assert service.fail_run_calls[0]["retryable"] is expected_retryable
        # Never left RUNNING: fail_run was always called before the
        # exception propagated out of handle().
        assert service.complete_run_calls == []


class TestResultSummaryBounds:
    @pytest.mark.asyncio
    async def test_result_summary_contains_only_bounded_documented_fields(self) -> None:
        candidate = _candidate()
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[candidate], provider_request_id="req-123"))
        handler, service = _handler(discovery=discovery)
        outcome = await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        expected_keys = {
            "scope", "providers_called", "provider_request_ids", "candidates_received",
            "evidence_recorded", "duplicates_skipped", "research_request_id", "research_run_id",
            "research_attempt_number", "research_run_status", "failure_category",
        }
        assert set(outcome.result_summary) == expected_keys
        assert outcome.result_summary["providers_called"] == ["perplexity_search"]
        assert outcome.result_summary["provider_request_ids"] == {"perplexity_search": "req-123"}
        assert len(outcome.result_summary["providers_called"]) <= 2
        assert len(outcome.result_summary["provider_request_ids"]) <= 2
        assert "provider_metadata" not in str(outcome.result_summary)
        assert outcome.result_summary["research_run_status"] == "COMPLETED"
        assert outcome.result_summary["failure_category"] is None
        # No evidence bodies/raw excerpts/structured facts/credentials -
        # only the bounded scalar/summary fields above are ever present.
        summary_text = str(outcome.result_summary).lower()
        for forbidden in ("raw_excerpt", "structured_facts", "source_url", "api_key", "authorization"):
            assert forbidden not in summary_text


class TestNoEvidencePersistedBeforeRouteMismatch:
    """G2B Correction V2, item 1/7: validation happens for *every*
    candidate in the batch before *any* `record_evidence` call - a
    mismatch anywhere in the batch means nothing from that batch is ever
    persisted, even candidates that appear earlier and would themselves
    have validated cleanly."""

    @pytest.mark.asyncio
    async def test_a_later_mismatched_candidate_prevents_persisting_earlier_valid_ones(self) -> None:
        good_first = _candidate(title="good-first")
        bad_second = _candidate(
            source_type=SourceType.SEC_OFFICIAL_FILING, classification=EvidenceClassification.OFFICIAL,
            title="bad-second",
        )
        discovery = FakeDiscoveryProvider(
            result=_fetch_result("perplexity_search", candidates=[good_first, bad_second])
        )
        handler, service = _handler(discovery=discovery)
        with pytest.raises(LiveResearchProviderResponseError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        # Nothing was persisted - not even the first, individually-valid candidate.
        assert service.record_evidence_calls == []
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.PROVIDER_ERROR
        assert service.fail_run_calls[0]["retryable"] is False

    @pytest.mark.asyncio
    async def test_mismatch_in_the_second_provider_call_prevents_persisting_the_first_calls_candidates(self) -> None:
        official = FakeOfficialCompanyDataProvider(
            company_facts_result=_fetch_result("sec_edgar", candidates=[_candidate(
                source_type=SourceType.EXCHANGE_REGULATOR_GOVERNMENT, classification=EvidenceClassification.OFFICIAL,
                title="good-company-fact",
            )])
        )
        # The discovery call (second, for COMPANY_OVERVIEW) returns a
        # candidate claiming to be an official SEC pairing - must be
        # rejected by discovery_candidate_to_evidence_kwargs, and must
        # prevent the already-fetched, individually-valid company-facts
        # candidate from being persisted too.
        discovery = FakeDiscoveryProvider(
            result=_fetch_result("perplexity_search", candidates=[_candidate(
                source_type=SourceType.SEC_OFFICIAL_FILING, classification=EvidenceClassification.OFFICIAL,
                title="mismatched-discovery",
            )])
        )
        handler, service = _handler(discovery=discovery, official=official)
        with pytest.raises(LiveResearchProviderResponseError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.COMPANY_OVERVIEW), progress=_NoopProgress())
        assert service.record_evidence_calls == []


class TestFailureBoundaryCoverage:
    """G2B Correction V2, item 2/7: every await after `create_next_run`
    is inside the failure boundary - start_run, complete_run, and the
    final progress report all get a fail_run attempt on failure, and the
    run never stays active/RUNNING."""

    @pytest.mark.asyncio
    async def test_start_run_failure_does_not_leave_an_active_run(self) -> None:
        service = FakeResearchRequestService(start_run_exception=TransientInfrastructureError("db blip"))
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery, service=service)

        with pytest.raises(TransientInfrastructureError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        # start_run was attempted, failed, and fail_run was called for
        # the same run_id - the run is never left QUEUED/active forever,
        # and no provider was ever called since start_run failed first.
        assert len(service.start_run_calls) == 1
        assert discovery.calls == []
        assert len(service.fail_run_calls) == 1
        assert service.fail_run_calls[0]["run_id"] == service.run_id
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.INTERNAL_ERROR
        assert service.fail_run_calls[0]["retryable"] is True
        assert service.complete_run_calls == []

    @pytest.mark.asyncio
    async def test_complete_run_failure_does_not_leave_running(self) -> None:
        service = FakeResearchRequestService(complete_run_exception=TransientInfrastructureError("commit failed"))
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery, service=service)

        with pytest.raises(TransientInfrastructureError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        # complete_run was attempted (and failed) exactly once; the
        # except clause then called fail_run for the same run - the run
        # is never left RUNNING with neither a completion nor a failure
        # recorded.
        assert len(service.complete_run_calls) == 1
        assert len(service.fail_run_calls) == 1
        assert service.fail_run_calls[0]["run_id"] == service.run_id
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.INTERNAL_ERROR
        assert service.fail_run_calls[0]["retryable"] is True

    @pytest.mark.asyncio
    async def test_final_progress_report_failure_does_not_leave_running(self) -> None:
        service = FakeResearchRequestService()
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery, service=service)
        # First report() call is the initial "submitting" one; the
        # second is the final one this test targets - it now runs
        # *before* terminalization (moved there by this correction), so
        # its failure must still result in fail_run, never a stray
        # COMPLETED/RUNNING mismatch.
        failing_progress = _FailingNthProgress(fail_on_call=2, exception=TransientInfrastructureError("progress sink down"))

        with pytest.raises(TransientInfrastructureError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=failing_progress)

        assert failing_progress.calls == 2
        # Because the progress failure happened *before* complete_run,
        # complete_run itself was never reached.
        assert service.complete_run_calls == []
        assert len(service.fail_run_calls) == 1
        assert service.fail_run_calls[0]["run_id"] == service.run_id
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.INTERNAL_ERROR
        assert service.fail_run_calls[0]["retryable"] is True


class TestDiscoveryMaxResultsWiring:
    """G2B Correction V2, item 5/7: the configured
    `PerplexitySearchSettings.live_research_perplexity_max_results`
    value (threaded into the handler as `discovery_max_results`) must
    reach every `DiscoverySearchRequest` the handler builds - never the
    model's own silent default."""

    @pytest.mark.asyncio
    async def test_configured_max_results_reaches_discovery_search_request(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery, discovery_max_results=17)
        await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())
        assert len(discovery.calls) == 1
        assert discovery.calls[0].max_results == 17

    @pytest.mark.asyncio
    async def test_configured_max_results_reaches_the_discovery_call_within_company_overview(self) -> None:
        official = FakeOfficialCompanyDataProvider(
            company_facts_result=_fetch_result("sec_edgar", candidates=[_candidate(
                source_type=SourceType.EXCHANGE_REGULATOR_GOVERNMENT, classification=EvidenceClassification.OFFICIAL,
            )])
        )
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery, official=official, discovery_max_results=5)
        await handler.handle(context=_context(), parameters=_params(ResearchScope.COMPANY_OVERVIEW), progress=_NoopProgress())
        assert discovery.calls[0].max_results == 5

    @pytest.mark.asyncio
    async def test_default_max_results_is_the_model_default_when_unconfigured(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery)  # discovery_max_results defaults to 10 in _handler()
        await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())
        assert discovery.calls[0].max_results == 10


class TestEvidencePersistenceFailureBoundary:
    """G2B Correction V3, item 8: `record_evidence` is inside the run's
    failure boundary too, for both a transient infrastructure failure and
    a wholly unexpected one - neither may leave the run RUNNING, and
    neither may be swallowed."""

    @pytest.mark.asyncio
    async def test_record_evidence_transient_failure_fails_the_run_as_retryable(self) -> None:
        service = FakeResearchRequestService(record_evidence_exception=TransientInfrastructureError("pool exhausted"))
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery, service=service)

        with pytest.raises(TransientInfrastructureError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        assert service.call_order.count("record_evidence") == 1
        assert service.record_evidence_calls == []
        assert service.complete_run_calls == []
        assert len(service.fail_run_calls) == 1
        assert service.fail_run_calls[0]["run_id"] == service.run_id
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.INTERNAL_ERROR
        assert service.fail_run_calls[0]["retryable"] is True

    @pytest.mark.asyncio
    async def test_record_evidence_unexpected_failure_fails_the_run_as_non_retryable(self) -> None:
        service = FakeResearchRequestService(record_evidence_exception=RuntimeError("unexpected bug"))
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery, service=service)

        with pytest.raises(RuntimeError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        assert service.complete_run_calls == []
        assert len(service.fail_run_calls) == 1
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.INTERNAL_ERROR
        assert service.fail_run_calls[0]["retryable"] is False

    @pytest.mark.asyncio
    async def test_a_mid_batch_record_evidence_failure_still_fails_the_run(self) -> None:
        # The first candidate persists, the second raises: partial
        # persistence is unavoidable once the batch has validated (the
        # per-candidate calls are not one transaction), but the run must
        # still end FAILED rather than RUNNING.
        service = FakeResearchRequestService()
        attempted_titles: list[str] = []

        async def _record_evidence(run_id, **kwargs):
            attempted_titles.append(kwargs["source_title"])
            if len(attempted_titles) == 1:
                return SimpleNamespace()
            raise TransientInfrastructureError("second write failed")

        service.record_evidence = _record_evidence  # type: ignore[method-assign]
        discovery = FakeDiscoveryProvider(
            result=_fetch_result("perplexity_search", candidates=[_candidate(title="first"), _candidate(title="second")])
        )
        handler, _ = _handler(discovery=discovery, service=service)

        with pytest.raises(TransientInfrastructureError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        assert attempted_titles == ["first", "second"]
        assert service.complete_run_calls == []
        assert len(service.fail_run_calls) == 1
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.INTERNAL_ERROR


class TestTerminalizationFailureBoundary:
    """G2B Correction V3, item 8: the NO_EVIDENCE_FOUND terminalization
    itself is inside the failure boundary, and nothing failure-prone runs
    after a successful terminalization."""

    @pytest.mark.asyncio
    async def test_no_evidence_found_fail_run_failure_is_followed_by_the_exception_boundary_fail_run(self) -> None:
        # fail_run raises on its first (NO_EVIDENCE_FOUND) call only. The
        # except clause must then attempt fail_run a second time, with the
        # *raised* exception's own mapped category - and the original
        # exception must still propagate, never be swallowed into a
        # falsely-successful HandlerOutcome.
        service = FakeResearchRequestService(
            fail_run_exception_on_call=1, fail_run_exception=TransientInfrastructureError("fail_run write failed"),
        )
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[]))
        handler, _ = _handler(discovery=discovery, service=service)

        with pytest.raises(TransientInfrastructureError):
            await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=_NoopProgress())

        assert len(service.fail_run_calls) == 2
        assert service.fail_run_calls[0]["failure_category"] == FailureCategory.NO_EVIDENCE_FOUND
        assert service.fail_run_calls[0]["retryable"] is False
        assert service.fail_run_calls[1]["failure_category"] == FailureCategory.INTERNAL_ERROR
        assert service.fail_run_calls[1]["retryable"] is True
        assert service.fail_run_calls[1]["run_id"] == service.run_id
        assert service.complete_run_calls == []

    @pytest.mark.asyncio
    async def test_nothing_failure_prone_runs_after_a_successful_complete_run(self) -> None:
        service = FakeResearchRequestService()
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        handler, _ = _handler(discovery=discovery, service=service)
        # Would raise on a third report() call - proving there is no
        # third one, i.e. no progress report after terminalization.
        progress = _FailingNthProgress(fail_on_call=3, exception=TransientInfrastructureError("must never be reached"))

        outcome = await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=progress)

        assert progress.calls == 2
        assert service.call_order[-1] == "complete_run"
        assert service.fail_run_calls == []
        assert outcome.result_summary["research_run_status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_nothing_failure_prone_runs_after_a_successful_no_evidence_found_fail_run(self) -> None:
        service = FakeResearchRequestService()
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[]))
        handler, _ = _handler(discovery=discovery, service=service)
        progress = _FailingNthProgress(fail_on_call=3, exception=TransientInfrastructureError("must never be reached"))

        outcome = await handler.handle(context=_context(), parameters=_params(ResearchScope.NEWS_SCAN), progress=progress)

        assert progress.calls == 2
        assert service.call_order[-1] == "fail_run"
        assert len(service.fail_run_calls) == 1
        assert outcome.result_summary["research_run_status"] == "FAILED"
        assert outcome.result_summary["failure_category"] == "NO_EVIDENCE_FOUND"
