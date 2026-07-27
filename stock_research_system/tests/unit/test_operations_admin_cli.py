"""Unit tests for the admin CLI's requester-identity handling
(`cli.operations_admin`, G2B Correction V2 item 3).

`--requested-by-account-id`/`--requested-by-integration-id` are trusted
CLI options, resolved and validated *before* `BackgroundJobService.
create_job` is ever called - never read from `--parameters-file`'s
untrusted JSON. Uses a real `BackgroundJobService` over in-memory fakes
(no Redis/Celery/PostgreSQL) so the "real ADMIN_CLI job creation" test is
a genuine end-to-end call through the service, not a mock.

Also covers G2B Correction V3 item 7: an unparsable UUID string is
raised as `LiveResearchRequesterContextError` (a `StockResearchError`,
which `_run` already turns into a bounded `error: ...` line) rather than
escaping as `UUID`'s raw `ValueError`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import LiveResearchRequesterContextError, StockResearchError
from stock_research_core.application.operations.job_registry import (
    BackgroundJobRegistry,
    JobRegistryEntry,
    NeverRetryPolicy,
)
from stock_research_core.application.operations.models import (
    LiveResearchRunExecutionParameters,
    PortfolioValuationParameters,
)
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.cli.operations_admin import _create_job, _resolve_requester_identity
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


def _build_service():
    entries = []
    for job_type in BackgroundJobType:
        if job_type == BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION:
            entries.append(
                JobRegistryEntry(
                    job_type=job_type, parameter_model=LiveResearchRunExecutionParameters, queue_name="finquest.research",
                    task_name="finquest.live_research_run_execution", handler=object(), maximum_attempts=4,
                    retry_policy=NeverRetryPolicy(), time_limit_seconds=180, resource_key_builder=lambda context, p: None,
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
    return service, job_repo


class TestResolveRequesterIdentity:
    def test_exactly_one_account_id_resolves(self) -> None:
        account_id = uuid4()
        resolved_account, resolved_integration = _resolve_requester_identity(
            job_type="LIVE_RESEARCH_RUN_EXECUTION", requested_by_account_id=str(account_id),
            requested_by_integration_id=None,
        )
        assert resolved_account == account_id
        assert resolved_integration is None

    def test_exactly_one_integration_id_resolves(self) -> None:
        integration_id = uuid4()
        resolved_account, resolved_integration = _resolve_requester_identity(
            job_type="LIVE_RESEARCH_RUN_EXECUTION", requested_by_account_id=None,
            requested_by_integration_id=str(integration_id),
        )
        assert resolved_account is None
        assert resolved_integration == integration_id

    def test_missing_identity_raises_for_live_research(self) -> None:
        with pytest.raises(LiveResearchRequesterContextError):
            _resolve_requester_identity(
                job_type="LIVE_RESEARCH_RUN_EXECUTION", requested_by_account_id=None, requested_by_integration_id=None,
            )

    def test_ambiguous_identity_raises_for_live_research(self) -> None:
        with pytest.raises(LiveResearchRequesterContextError):
            _resolve_requester_identity(
                job_type="LIVE_RESEARCH_RUN_EXECUTION", requested_by_account_id=str(uuid4()),
                requested_by_integration_id=str(uuid4()),
            )

    def test_other_job_types_do_not_require_identity(self) -> None:
        resolved_account, resolved_integration = _resolve_requester_identity(
            job_type="PORTFOLIO_VALUATION", requested_by_account_id=None, requested_by_integration_id=None,
        )
        assert resolved_account is None
        assert resolved_integration is None


class TestInvalidRequesterUuidStrings:
    """G2B Correction V3, item 7: an unparsable `--requested-by-*` value
    is a caller mistake, not a crash. It must surface as
    `LiveResearchRequesterContextError` - which `_run`'s existing
    `except StockResearchError` boundary turns into a bounded
    `error: ...` line and exit code 1 - never as `UUID`'s own raw
    `ValueError` traceback."""

    @pytest.mark.parametrize(
        "invalid",
        [
            "not-a-uuid",
            "1234",
            "11111111-1111-1111-1111-11111111111",  # one digit short
            "11111111-1111-1111-1111-1111111111111",  # one digit too many
            "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
            "'; DROP TABLE background_jobs; --",
        ],
    )
    def test_invalid_account_uuid_raises_a_bounded_cli_error(self, invalid: str) -> None:
        with pytest.raises(LiveResearchRequesterContextError, match="--requested-by-account-id must be a valid UUID"):
            _resolve_requester_identity(
                job_type="LIVE_RESEARCH_RUN_EXECUTION", requested_by_account_id=invalid,
                requested_by_integration_id=None,
            )

    @pytest.mark.parametrize("invalid", ["not-a-uuid", "1234", "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"])
    def test_invalid_integration_uuid_raises_a_bounded_cli_error(self, invalid: str) -> None:
        with pytest.raises(LiveResearchRequesterContextError, match="--requested-by-integration-id must be a valid UUID"):
            _resolve_requester_identity(
                job_type="LIVE_RESEARCH_RUN_EXECUTION", requested_by_account_id=None,
                requested_by_integration_id=invalid,
            )

    def test_the_error_is_a_stock_research_error_so_the_cli_boundary_catches_it(self) -> None:
        with pytest.raises(StockResearchError):
            _resolve_requester_identity(
                job_type="LIVE_RESEARCH_RUN_EXECUTION", requested_by_account_id="not-a-uuid",
                requested_by_integration_id=None,
            )

    def test_the_message_never_echoes_the_rejected_value(self) -> None:
        # The value is caller-supplied; the bounded message reports only
        # its length, so a pasted secret can never end up on stderr.
        with pytest.raises(LiveResearchRequesterContextError) as exc_info:
            _resolve_requester_identity(
                job_type="LIVE_RESEARCH_RUN_EXECUTION",
                requested_by_account_id="sk-live-not-a-uuid-secret", requested_by_integration_id=None,
            )
        message = str(exc_info.value)
        assert "sk-live-not-a-uuid-secret" not in message
        assert "25 character(s)" in message

    def test_an_invalid_uuid_is_rejected_for_non_live_research_job_types_too(self) -> None:
        # The parse happens before the job-type-specific XOR rule, so
        # every job type gets the same bounded error rather than a
        # traceback.
        with pytest.raises(LiveResearchRequesterContextError):
            _resolve_requester_identity(
                job_type="PORTFOLIO_VALUATION", requested_by_account_id="not-a-uuid",
                requested_by_integration_id=None,
            )

    @pytest.mark.asyncio
    async def test_invalid_uuid_is_rejected_before_create_job_is_called(self, tmp_path) -> None:
        service, job_repo = _build_service()
        parameters_path = tmp_path / "live-research-parameters.json"
        parameters_path.write_text(
            json.dumps({"original_question": "What is happening with Acme Corp?", "scope": "GENERAL_QUESTION"}),
            encoding="utf-8",
        )

        with pytest.raises(LiveResearchRequesterContextError):
            await _create_job(
                service, job_type="LIVE_RESEARCH_RUN_EXECUTION", parameters_file=str(parameters_path),
                idempotency_key="cli-key-5", priority="NORMAL",
                requested_by_account_id="not-a-uuid", requested_by_integration_id=None,
            )
        assert job_repo.jobs == {}


class TestCreateJobCliRequesterIdentity:
    @pytest.mark.asyncio
    async def test_real_admin_cli_job_creation_with_a_trusted_requester(self, tmp_path) -> None:
        service, job_repo = _build_service()
        account_id = uuid4()
        parameters_path = tmp_path / "live-research-parameters.json"
        parameters_path.write_text(
            json.dumps({"original_question": "What is happening with Acme Corp?", "scope": "GENERAL_QUESTION"}),
            encoding="utf-8",
        )

        await _create_job(
            service, job_type="LIVE_RESEARCH_RUN_EXECUTION", parameters_file=str(parameters_path),
            idempotency_key="cli-key-1", priority="NORMAL",
            requested_by_account_id=str(account_id), requested_by_integration_id=None,
        )

        assert len(job_repo.jobs) == 1
        created_job = next(iter(job_repo.jobs.values()))
        assert created_job.job_type == BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        # The trusted CLI-supplied identity reached the persisted job -
        # never derived from the parameters file's JSON (which has no
        # identity field at all).
        assert created_job.requested_by_account_id == account_id
        assert created_job.requested_by_integration_id is None
        assert "requested_by_account_id" not in created_job.parameters
        assert "requested_by_integration_id" not in created_job.parameters

    @pytest.mark.asyncio
    async def test_missing_requester_identity_is_rejected_before_create_job_is_called(self, tmp_path) -> None:
        service, job_repo = _build_service()
        parameters_path = tmp_path / "live-research-parameters.json"
        parameters_path.write_text(
            json.dumps({"original_question": "What is happening with Acme Corp?", "scope": "GENERAL_QUESTION"}),
            encoding="utf-8",
        )

        with pytest.raises(LiveResearchRequesterContextError):
            await _create_job(
                service, job_type="LIVE_RESEARCH_RUN_EXECUTION", parameters_file=str(parameters_path),
                idempotency_key="cli-key-2", priority="NORMAL",
                requested_by_account_id=None, requested_by_integration_id=None,
            )
        assert job_repo.jobs == {}

    @pytest.mark.asyncio
    async def test_ambiguous_requester_identity_is_rejected_before_create_job_is_called(self, tmp_path) -> None:
        service, job_repo = _build_service()
        parameters_path = tmp_path / "live-research-parameters.json"
        parameters_path.write_text(
            json.dumps({"original_question": "What is happening with Acme Corp?", "scope": "GENERAL_QUESTION"}),
            encoding="utf-8",
        )

        with pytest.raises(LiveResearchRequesterContextError):
            await _create_job(
                service, job_type="LIVE_RESEARCH_RUN_EXECUTION", parameters_file=str(parameters_path),
                idempotency_key="cli-key-3", priority="NORMAL",
                requested_by_account_id=str(uuid4()), requested_by_integration_id=str(uuid4()),
            )
        assert job_repo.jobs == {}

    @pytest.mark.asyncio
    async def test_non_live_research_job_type_does_not_require_identity(self, tmp_path) -> None:
        service, job_repo = _build_service()
        parameters_path = tmp_path / "portfolio-valuation-parameters.json"
        parameters_path.write_text(
            json.dumps({"portfolio_id": str(uuid4()), "as_of": NOW.isoformat()}), encoding="utf-8",
        )

        await _create_job(
            service, job_type="PORTFOLIO_VALUATION", parameters_file=str(parameters_path),
            idempotency_key="cli-key-4", priority="NORMAL",
            requested_by_account_id=None, requested_by_integration_id=None,
        )
        assert len(job_repo.jobs) == 1
