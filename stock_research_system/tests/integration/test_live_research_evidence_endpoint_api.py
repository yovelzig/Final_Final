"""Integration tests (real PostgreSQL, via `api_client`) for Phase G2C's
`GET /api/v1/integrations/n8n/jobs/{job_id}/live-research/evidence`.

Job execution (Celery/Redis, the real `LiveResearchRunExecutionJobHandler`)
is never exercised here - every `BackgroundJob`/`ResearchRequest`/
`ResearchRun`/`EvidenceItem` fixture is written directly through the
repositories, exactly like `test_live_research_repositories.py`, so these
tests isolate the endpoint's own 7-step authorization/validation flow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.live_research.enums import (
    EvidenceClassification,
    FailureCategory,
    ResearchRunStatus,
    ResearchScope,
    SourceType,
)
from stock_research_core.domain.live_research.hashing import compute_evidence_content_hash
from stock_research_core.domain.live_research.models import EvidenceItem, ResearchRequest, ResearchRun
from stock_research_core.domain.operations.enums import (
    BackgroundJobStatus,
    BackgroundJobType,
    IntegrationClientStatus,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import BackgroundJob, IntegrationClient
from stock_research_core.infrastructure.operations.integration_auth import (
    generate_key_id,
    generate_raw_api_key,
    hash_api_key,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _create_integration_client(uow_factory) -> tuple[str, str, uuid.UUID]:
    raw_key = generate_raw_api_key()
    client = IntegrationClient(
        name="Test n8n Evidence Client", key_id=generate_key_id(), api_key_hash=hash_api_key(raw_key),
        status=IntegrationClientStatus.ACTIVE, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION],
    )
    async with uow_factory() as uow:
        created = await uow.integration_clients.create(client)
        await uow.commit()
    return created.key_id, raw_key, created.integration_id


def _auth_headers(key_id: str, raw_key: str) -> dict[str, str]:
    return {"X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key}


_TERMINAL_STATUSES = {
    BackgroundJobStatus.SUCCEEDED, BackgroundJobStatus.FAILED, BackgroundJobStatus.CANCELLED, BackgroundJobStatus.SKIPPED,
}


async def _create_job(
    uow_factory, *,
    job_type: BackgroundJobType = BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
    status: BackgroundJobStatus = BackgroundJobStatus.SUCCEEDED,
    requested_by_integration_id: uuid.UUID,
    result_summary: dict | None = None,
) -> BackgroundJob:
    if status == BackgroundJobStatus.SUCCEEDED and result_summary is None:
        # A dummy-but-valid summary - used only by tests where job_type
        # (checked before result_summary content) is what must reject.
        result_summary = {"ok": True}
    job = BackgroundJob(
        job_type=job_type, status=status, trigger_source=JobTriggerSource.N8N,
        requested_by_integration_id=requested_by_integration_id, idempotency_key=f"idem-{uuid4().hex[:12]}",
        queue_name="finquest.research", task_name="finquest.live_research_run_execution",
        result_summary=result_summary, available_at=NOW,
        started_at=NOW if status in (BackgroundJobStatus.RUNNING, BackgroundJobStatus.RETRY_SCHEDULED) else None,
        completed_at=NOW if status in _TERMINAL_STATUSES else None,
        cancelled_at=NOW if status == BackgroundJobStatus.CANCELLED else None,
    )
    async with uow_factory() as uow:
        created = await uow.background_jobs.create(job)
        await uow.commit()
    return created


async def _create_request(uow_factory, *, requested_by_integration_id: uuid.UUID, **overrides: object) -> ResearchRequest:
    defaults: dict = dict(
        requested_by_integration_id=requested_by_integration_id,
        original_question="What is going on with this company?",
        normalized_query="what is going on with this company?",
        scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key=f"key-{uuid4().hex[:8]}",
        request_hash="a" * 64,
    )
    defaults.update(overrides)
    request = ResearchRequest(**defaults)
    async with uow_factory() as uow:
        created = await uow.research_requests.create(request)
        await uow.commit()
    return created


async def _create_run(uow_factory, request_id: uuid.UUID, *, status: ResearchRunStatus = ResearchRunStatus.COMPLETED) -> ResearchRun:
    run = ResearchRun(request_id=request_id, attempt_number=1)
    async with uow_factory() as uow:
        created = await uow.research_runs.create(run)
        if status == ResearchRunStatus.COMPLETED:
            created = await uow.research_runs.mark_completed(created.run_id, completed_at=NOW)
        elif status == ResearchRunStatus.FAILED:
            created = await uow.research_runs.mark_failed(
                created.run_id, completed_at=NOW, failure_category=FailureCategory.NO_EVIDENCE_FOUND,
                failure_message="No evidence found.", retryable=False,
            )
        elif status == ResearchRunStatus.RUNNING:
            created = await uow.research_runs.mark_running(created.run_id, started_at=NOW)
        await uow.commit()
    return created


async def _create_evidence(uow_factory, run_id: uuid.UUID, **overrides: object) -> EvidenceItem:
    defaults: dict = dict(
        source_type=SourceType.SEC_OFFICIAL_FILING, classification=EvidenceClassification.OFFICIAL,
        source_url="https://www.sec.gov/example", official_identifier=f"0001234567-26-{uuid4().hex[:6]}",
        source_title="Form 10-K", publisher="SEC", published_at=NOW,
        raw_excerpt="Revenue increased 10% year over year, driven by strong product demand.",
        normalized_text="revenue increased 10% year over year", structured_facts=None,
    )
    defaults.update(overrides)
    content_hash = compute_evidence_content_hash(
        source_type=defaults["source_type"].value, classification=defaults["classification"].value,
        source_url=defaults["source_url"], official_identifier=defaults["official_identifier"],
        source_title=defaults["source_title"], publisher=defaults["publisher"], published_at=defaults["published_at"],
        raw_excerpt=defaults["raw_excerpt"], normalized_text=defaults["normalized_text"],
        structured_facts=defaults["structured_facts"],
    )
    item = EvidenceItem(run_id=run_id, content_hash=content_hash, **defaults)
    async with uow_factory() as uow:
        created = await uow.evidence_items.create(item)
        await uow.commit()
    return created


def _completed_summary(
    *, research_run_id: uuid.UUID, research_request_id: uuid.UUID | None = None, evidence_recorded: int = 1,
) -> dict:
    # `research_request_id` defaults to an unrelated random UUID - callers
    # that actually reach the job-to-run binding check (Correction V2)
    # must pass the real, matching `request.request_id` explicitly.
    return {
        "research_request_id": str(research_request_id) if research_request_id is not None else str(uuid4()),
        "research_run_id": str(research_run_id), "research_attempt_number": 1,
        "research_run_status": "COMPLETED", "failure_category": None, "scope": "GENERAL_QUESTION",
        "providers_called": ["perplexity_discovery_search"], "provider_request_ids": ["req-abc123"],
        "candidates_received": evidence_recorded, "evidence_recorded": evidence_recorded, "duplicates_skipped": 0,
    }


def _no_evidence_summary(*, research_run_id: uuid.UUID) -> dict:
    return {
        "research_request_id": str(uuid4()), "research_run_id": str(research_run_id), "research_attempt_number": 1,
        "research_run_status": "FAILED", "failure_category": "NO_EVIDENCE_FOUND", "scope": "GENERAL_QUESTION",
        "providers_called": ["perplexity_discovery_search"], "provider_request_ids": ["req-abc123"],
        "candidates_received": 0, "evidence_recorded": 0, "duplicates_skipped": 0,
    }


def _evidence_url(job_id: uuid.UUID) -> str:
    return f"/api/v1/integrations/n8n/jobs/{job_id}/live-research/evidence"


class TestOwnershipIsCheckedFirst:
    async def test_unknown_job_returns_404(self, api_client, uow_factory) -> None:
        key_id, raw_key, _ = await _create_integration_client(uow_factory)
        response = await api_client.get(_evidence_url(uuid4()), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 404

    async def test_another_integrations_job_returns_404(self, api_client, uow_factory) -> None:
        _, _, owner_id = await _create_integration_client(uow_factory)
        key_id_b, raw_key_b, _ = await _create_integration_client(uow_factory)
        job = await _create_job(
            uow_factory, requested_by_integration_id=owner_id,
            result_summary=_completed_summary(research_run_id=uuid4()),
        )
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id_b, raw_key_b))
        assert response.status_code == 404

    async def test_another_integrations_job_of_the_wrong_type_returns_404(self, api_client, uow_factory) -> None:
        _, _, owner_id = await _create_integration_client(uow_factory)
        key_id_b, raw_key_b, _ = await _create_integration_client(uow_factory)
        job = await _create_job(
            uow_factory, requested_by_integration_id=owner_id, job_type=BackgroundJobType.RETRIEVAL_EVALUATION,
        )
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id_b, raw_key_b))
        assert response.status_code == 404

    async def test_another_integrations_failed_job_returns_404(self, api_client, uow_factory) -> None:
        _, _, owner_id = await _create_integration_client(uow_factory)
        key_id_b, raw_key_b, _ = await _create_integration_client(uow_factory)
        job = await _create_job(
            uow_factory, requested_by_integration_id=owner_id, status=BackgroundJobStatus.FAILED,
            result_summary={"error_code": "PROVIDER_ERROR", "error_message": "boom"},
        )
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id_b, raw_key_b))
        assert response.status_code == 404


class TestOwnedJobStateValidation:
    async def test_owned_job_of_another_type_returns_409(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        job = await _create_job(
            uow_factory, requested_by_integration_id=integration_id, job_type=BackgroundJobType.RETRIEVAL_EVALUATION,
        )
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    @pytest.mark.parametrize(
        "status", [
            BackgroundJobStatus.PENDING, BackgroundJobStatus.QUEUED, BackgroundJobStatus.RUNNING,
            BackgroundJobStatus.RETRY_SCHEDULED, BackgroundJobStatus.FAILED, BackgroundJobStatus.CANCELLED,
            BackgroundJobStatus.SKIPPED,
        ],
    )
    async def test_owned_non_succeeded_job_returns_409(self, api_client, uow_factory, status: BackgroundJobStatus) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, status=status)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_owned_succeeded_job_with_missing_result_summary_returns_409(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary={})
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_malformed_research_run_id_returns_409(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        summary = _completed_summary(research_run_id=uuid4())
        summary["research_run_id"] = "not-a-uuid"
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_evidence_recorded_zero_returns_409(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        summary = _completed_summary(research_run_id=run.run_id, evidence_recorded=0)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_no_evidence_found_result_returns_409(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id, status=ResearchRunStatus.FAILED)
        summary = _no_evidence_summary(research_run_id=run.run_id)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_result_summary_claims_completed_but_run_is_not_completed_returns_409(
        self, api_client, uow_factory
    ) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id, status=ResearchRunStatus.RUNNING)
        # result_summary lies (claims COMPLETED) - the endpoint must not
        # trust it and must re-check the actual ResearchRun row.
        summary = _completed_summary(research_run_id=run.run_id)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_result_summary_references_a_nonexistent_run_returns_409(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        summary = _completed_summary(research_run_id=uuid4())
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_research_request_ownership_mismatch_returns_404(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        _, _, other_integration_id = await _create_integration_client(uow_factory)
        # The ResearchRequest belongs to a DIFFERENT integration than the
        # one that owns the BackgroundJob - the second authorization layer
        # (step 6) must independently reject this, even though step 1's
        # job-ownership check already passed.
        request = await _create_request(uow_factory, requested_by_integration_id=other_integration_id)
        run = await _create_run(uow_factory, request.request_id)
        # research_request_id matches this run's own request_id (the
        # job-to-run binding check must pass) - only the actual ownership
        # check (step 6) is being exercised here.
        summary = _completed_summary(research_run_id=run.run_id, research_request_id=request.request_id)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 404


class TestJobToRunBinding:
    """Correction V2 - `result_summary.research_request_id` must agree
    with the loaded `ResearchRun.request_id` before the ownership
    revalidation (step 6) ever runs. All three cases return the same
    bounded 409 EVIDENCE_NOT_AVAILABLE response as every other
    result_summary validation failure."""

    async def test_malformed_research_request_id_returns_409(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        summary = _completed_summary(research_run_id=run.run_id, research_request_id=request.request_id)
        summary["research_request_id"] = "not-a-uuid"
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_research_request_id_mismatched_with_run_request_id_returns_409(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        # A well-formed UUID, but not this run's actual request_id.
        summary = _completed_summary(research_run_id=run.run_id, research_request_id=uuid4())
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409

    async def test_summary_pointing_to_another_completed_run_owned_by_the_same_integration_returns_409(
        self, api_client, uow_factory
    ) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request_a = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run_a = await _create_run(uow_factory, request_a.request_id)
        await _create_evidence(uow_factory, run_a.run_id)

        request_b = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run_b = await _create_run(uow_factory, request_b.request_id)
        await _create_evidence(uow_factory, run_b.run_id)

        # research_run_id points at run_b (real, COMPLETED, owned by this
        # same integration), but research_request_id claims request_a's id
        # - internally inconsistent even though both requests/runs belong
        # to the same, correctly-authenticated integration client.
        summary = _completed_summary(research_run_id=run_b.run_id, research_request_id=request_a.request_id)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)
        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 409


class TestSuccessfulEvidenceRetrieval:
    async def test_successful_owned_completed_run_with_evidence_returns_200(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        await _create_evidence(uow_factory, run.run_id, source_title="Form 10-K")
        summary = _completed_summary(research_run_id=run.run_id, research_request_id=request.request_id, evidence_recorded=1)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)

        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["limit"] == 25
        assert body["offset"] == 0
        assert body["has_more"] is False
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["source_title"] == "Form 10-K"
        assert item["classification"] == "OFFICIAL"
        assert item["source_type"] == "SEC_OFFICIAL_FILING"

    async def test_response_excludes_raw_evidence_and_provider_internals(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        await _create_evidence(
            uow_factory, run.run_id,
            raw_excerpt="SECRET_RAW_EXCERPT_MARKER", normalized_text="secret_normalized_text_marker",
            structured_facts={"internal_marker": "structured_fact_value"},
        )
        summary = _completed_summary(research_run_id=run.run_id, research_request_id=request.request_id, evidence_recorded=1)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)

        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 200, response.text
        raw_body_text = response.text
        assert "SECRET_RAW_EXCERPT_MARKER" not in raw_body_text
        assert "secret_normalized_text_marker" not in raw_body_text
        assert "structured_fact_value" not in raw_body_text
        item = response.json()["items"][0]
        assert "raw_excerpt" not in item
        assert "normalized_text" not in item
        assert "structured_facts" not in item
        assert "provider_metadata" not in item
        assert set(item.keys()) == {
            "evidence_id", "source_type", "classification", "source_title", "publisher",
            "source_url", "official_identifier", "published_at",
        }

    async def test_discovery_only_evidence_remains_visibly_non_official(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        await _create_evidence(
            uow_factory, run.run_id, source_type=SourceType.DISCOVERY_ONLY, classification=EvidenceClassification.NON_OFFICIAL,
            source_url="https://news.example.com/article", official_identifier=None, publisher="Example News",
        )
        summary = _completed_summary(research_run_id=run.run_id, research_request_id=request.request_id, evidence_recorded=1)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)

        response = await api_client.get(_evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key))
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["source_type"] == "DISCOVERY_ONLY"
        assert item["classification"] == "NON_OFFICIAL"


class TestEvidencePaginationParameters:
    async def test_pagination_query_parameters_are_honored(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        for i in range(5):
            await _create_evidence(uow_factory, run.run_id, source_title=f"Filing #{i}")
        summary = _completed_summary(research_run_id=run.run_id, research_request_id=request.request_id, evidence_recorded=5)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)

        first_page = await api_client.get(
            _evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key), params={"limit": 2, "offset": 0}
        )
        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["items"]) == 2
        assert first_body["has_more"] is True
        assert first_body["next_offset"] == 2

        last_page = await api_client.get(
            _evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key), params={"limit": 2, "offset": 4}
        )
        last_body = last_page.json()
        assert len(last_body["items"]) == 1
        assert last_body["has_more"] is False
        assert last_body["next_offset"] is None

    async def test_limit_above_maximum_is_rejected(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        summary = _completed_summary(research_run_id=run.run_id, evidence_recorded=1)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)

        response = await api_client.get(
            _evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key), params={"limit": 51}
        )
        assert response.status_code == 422

    async def test_limit_below_one_is_rejected(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        summary = _completed_summary(research_run_id=run.run_id, evidence_recorded=1)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)

        response = await api_client.get(
            _evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key), params={"limit": 0}
        )
        assert response.status_code == 422

    async def test_negative_offset_is_rejected(self, api_client, uow_factory) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(uow_factory)
        request = await _create_request(uow_factory, requested_by_integration_id=integration_id)
        run = await _create_run(uow_factory, request.request_id)
        summary = _completed_summary(research_run_id=run.run_id, evidence_recorded=1)
        job = await _create_job(uow_factory, requested_by_integration_id=integration_id, result_summary=summary)

        response = await api_client.get(
            _evidence_url(job.job_id), headers=_auth_headers(key_id, raw_key), params={"offset": -1}
        )
        assert response.status_code == 422
