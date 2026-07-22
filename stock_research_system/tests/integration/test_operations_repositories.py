"""Integration tests for the Phase 11 repositories against the real
PostgreSQL/TimescaleDB test database: `BackgroundJob`,
`BackgroundJobAttempt`, `BackgroundJobEvent`, `IntegrationClient`, and
`IntegrationRequest` persistence round-trips.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.operations.enums import (
    BackgroundJobPriority,
    BackgroundJobStatus,
    BackgroundJobType,
    IntegrationClientStatus,
    IntegrationRequestStatus,
    JobAttemptStatus,
    JobEventType,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundJobEvent,
    IntegrationClient,
    IntegrationRequest,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _job(**overrides) -> BackgroundJob:
    fields = dict(
        job_type=BackgroundJobType.PORTFOLIO_VALUATION, trigger_source=JobTriggerSource.API,
        idempotency_key=f"key-{uuid4()}", queue_name="finquest.portfolio", task_name="finquest.portfolio_valuation",
        available_at=NOW,
    )
    fields.update(overrides)
    return BackgroundJob(**fields)


class TestBackgroundJobRepository:
    async def test_create_and_get_by_id(self, uow_factory) -> None:
        job = _job()
        async with uow_factory() as uow:
            created = await uow.background_jobs.create(job)
            await uow.commit()
        async with uow_factory() as uow:
            fetched = await uow.background_jobs.get_by_id(created.job_id)
        assert fetched is not None
        assert fetched.idempotency_key == job.idempotency_key
        assert fetched.status == BackgroundJobStatus.PENDING

    async def test_idempotency_scope_lookup_round_trips(self, uow_factory) -> None:
        # SYSTEM trigger source (no account/integration FK needed) keeps
        # this a pure repository test, independent of the identity schema.
        job = _job(idempotency_key="stable-key", trigger_source=JobTriggerSource.SYSTEM)
        async with uow_factory() as uow:
            created = await uow.background_jobs.create(job)
            await uow.commit()
        async with uow_factory() as uow:
            found = await uow.background_jobs.get_by_idempotency_key(
                job_type=BackgroundJobType.PORTFOLIO_VALUATION, trigger_source=JobTriggerSource.SYSTEM.value,
                requested_by_account_id=None, requested_by_integration_id=None,
                idempotency_key="stable-key",
            )
        assert found is not None
        assert found.job_id == created.job_id

    async def test_duplicate_idempotency_scope_is_rejected_at_the_database(self, uow_factory) -> None:
        from stock_research_core.application.exceptions import PersistenceError

        job1 = _job(idempotency_key="dupe-key", trigger_source=JobTriggerSource.SYSTEM)
        job2 = _job(idempotency_key="dupe-key", trigger_source=JobTriggerSource.SYSTEM)
        async with uow_factory() as uow:
            await uow.background_jobs.create(job1)
            await uow.commit()
        with pytest.raises(PersistenceError):
            async with uow_factory() as uow:
                await uow.background_jobs.create(job2)
                await uow.commit()

    async def test_state_transitions_round_trip(self, uow_factory) -> None:
        job = _job()
        async with uow_factory() as uow:
            created = await uow.background_jobs.create(job)
            await uow.background_jobs.mark_queued(created.job_id, task_id="task-1")
            await uow.commit()

        async with uow_factory() as uow:
            running = await uow.background_jobs.mark_running(created.job_id, started_at=NOW)
            assert running.status == BackgroundJobStatus.RUNNING
            assert running.attempt_count == 1
            progressed = await uow.background_jobs.update_progress(created.job_id, current=3, total=10, message="working")
            assert progressed.progress_current == 3
            succeeded = await uow.background_jobs.mark_succeeded(
                created.job_id, completed_at=NOW, result_summary={"ok": True}
            )
            await uow.commit()
        assert succeeded.status == BackgroundJobStatus.SUCCEEDED
        assert succeeded.result_summary == {"ok": True}

    async def test_mark_succeeded_rejects_sensitive_result_summary(self, uow_factory) -> None:
        from stock_research_core.application.exceptions import PersistenceError

        job = _job()
        async with uow_factory() as uow:
            created = await uow.background_jobs.create(job)
            await uow.commit()
        with pytest.raises(PersistenceError):
            async with uow_factory() as uow:
                await uow.background_jobs.mark_succeeded(
                    created.job_id, completed_at=NOW, result_summary={"database_url": "postgresql://u:p@h/d"}
                )

    async def test_list_and_count_jobs_with_filters(self, uow_factory) -> None:
        async with uow_factory() as uow:
            await uow.background_jobs.create(_job(job_type=BackgroundJobType.PORTFOLIO_VALUATION))
            await uow.background_jobs.create(_job(job_type=BackgroundJobType.KNOWLEDGE_GAP_SUMMARY))
            await uow.commit()

        async with uow_factory() as uow:
            jobs = await uow.background_jobs.list_jobs(job_type=BackgroundJobType.PORTFOLIO_VALUATION, limit=10)
            count = await uow.background_jobs.count_jobs(job_type=BackgroundJobType.PORTFOLIO_VALUATION)
        assert all(j.job_type == BackgroundJobType.PORTFOLIO_VALUATION for j in jobs)
        assert count == len(jobs)

    async def test_list_stale_running_job_ids(self, uow_factory) -> None:
        old_start = NOW - timedelta(hours=2)
        job = _job()
        async with uow_factory() as uow:
            created = await uow.background_jobs.create(job)
            await uow.background_jobs.mark_running(created.job_id, started_at=old_start)
            await uow.commit()

        async with uow_factory() as uow:
            stale_ids = await uow.background_jobs.list_stale_running_job_ids(older_than=NOW - timedelta(minutes=30))
        assert created.job_id in stale_ids


class TestBackgroundJobAttemptRepository:
    async def test_create_and_complete_attempt(self, uow_factory) -> None:
        job = _job()
        async with uow_factory() as uow:
            created_job = await uow.background_jobs.create(job)
            attempt = await uow.background_job_attempts.create(
                BackgroundJobAttempt(job_id=created_job.job_id, attempt_number=1, started_at=NOW)
            )
            await uow.commit()

        async with uow_factory() as uow:
            completed = await uow.background_job_attempts.complete(
                attempt.attempt_id, status=JobAttemptStatus.SUCCEEDED, completed_at=NOW,
            )
            await uow.commit()
        assert completed.status == JobAttemptStatus.SUCCEEDED

        async with uow_factory() as uow:
            attempts = await uow.background_job_attempts.list_for_job(created_job.job_id)
        assert len(attempts) == 1


class TestBackgroundJobEventRepository:
    async def test_events_are_returned_in_deterministic_order(self, uow_factory) -> None:
        # Each event committed in its own transaction: Postgres `now()` is
        # stable *within* a transaction, so events appended together in one
        # transaction can legitimately share a `created_at` (ordering then
        # deterministically falls back to `event_id`, not insertion order -
        # exactly per the domain model's documented ordering rule).
        # Separate transactions are what actually produce distinct timestamps.
        job = _job()
        async with uow_factory() as uow:
            created_job = await uow.background_jobs.create(job)
            await uow.commit()

        for event_type in (JobEventType.CREATED, JobEventType.QUEUED, JobEventType.STARTED):
            async with uow_factory() as uow:
                await uow.background_job_events.append(
                    BackgroundJobEvent(job_id=created_job.job_id, event_type=event_type, message=f"{event_type.value} event.")
                )
                await uow.commit()

        async with uow_factory() as uow:
            events = await uow.background_job_events.list_for_job(created_job.job_id)
        assert [e.event_type for e in events] == [JobEventType.CREATED, JobEventType.QUEUED, JobEventType.STARTED]

        # Regardless of timing, repeated reads return the identical order -
        # the actual "deterministic" guarantee the domain model promises.
        async with uow_factory() as uow:
            events_again = await uow.background_job_events.list_for_job(created_job.job_id)
        assert [e.event_id for e in events] == [e.event_id for e in events_again]


class TestIntegrationClientRepository:
    async def test_create_get_by_key_id_and_load_allowed_job_types(self, uow_factory) -> None:
        client = IntegrationClient(
            name="n8n", key_id=f"key-{uuid4().hex[:12]}", api_key_hash="a" * 64,
            allowed_job_types=[BackgroundJobType.TRACKED_MARKET_REFRESH, BackgroundJobType.RETRIEVAL_EVALUATION],
        )
        async with uow_factory() as uow:
            created = await uow.integration_clients.create(client)
            await uow.commit()

        async with uow_factory() as uow:
            fetched = await uow.integration_clients.get_by_key_id(client.key_id)
        assert fetched is not None
        assert fetched.integration_id == created.integration_id
        assert set(fetched.allowed_job_types) == {
            BackgroundJobType.TRACKED_MARKET_REFRESH, BackgroundJobType.RETRIEVAL_EVALUATION,
        }

    async def test_set_status_and_update_last_used(self, uow_factory) -> None:
        client = IntegrationClient(
            name="n8n", key_id=f"key-{uuid4().hex[:12]}", api_key_hash="b" * 64,
            allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION],
        )
        async with uow_factory() as uow:
            created = await uow.integration_clients.create(client)
            await uow.commit()

        async with uow_factory() as uow:
            revoked = await uow.integration_clients.set_status(created.integration_id, status=IntegrationClientStatus.REVOKED)
            used = await uow.integration_clients.update_last_used(created.integration_id, last_used_at=NOW)
            await uow.commit()
        assert revoked.status == IntegrationClientStatus.REVOKED
        assert used.last_used_at == NOW


class TestIntegrationRequestRepository:
    async def test_replay_lookup_and_completion(self, uow_factory) -> None:
        client = IntegrationClient(
            name="n8n", key_id=f"key-{uuid4().hex[:12]}", api_key_hash="c" * 64,
            allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION],
        )
        async with uow_factory() as uow:
            created_client = await uow.integration_clients.create(client)
            await uow.commit()

        request = IntegrationRequest(
            integration_id=created_client.integration_id, external_request_id="ext-1", idempotency_key="idem-1",
            request_hash="d" * 64, correlation_id="corr-1",
        )
        async with uow_factory() as uow:
            created_request = await uow.integration_requests.create(request)
            await uow.commit()

        async with uow_factory() as uow:
            found = await uow.integration_requests.get_by_external_request_id(
                integration_id=created_client.integration_id, external_request_id="ext-1"
            )
        assert found is not None
        assert found.status == IntegrationRequestStatus.ACCEPTED

        job_id = uuid4()
        async with uow_factory() as uow:
            job = _job(requested_by_integration_id=created_client.integration_id, trigger_source=JobTriggerSource.N8N)
            job = job.model_copy(update={"job_id": job_id})
            await uow.background_jobs.create(job)
            completed = await uow.integration_requests.mark_completed(
                created_request.request_id, job_id=job_id, completed_at=NOW
            )
            await uow.commit()
        assert completed.status == IntegrationRequestStatus.COMPLETED
        assert completed.job_id == job_id
