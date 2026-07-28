"""Integration tests (real PostgreSQL, via `api_client`) for Phase G2C:
n8n triggering `LIVE_RESEARCH_RUN_EXECUTION` through the existing
`POST /api/v1/integrations/n8n/jobs` endpoint.

Uses the REAL production job registry (`build_default_registry`, with
plain `object()` stand-ins for the handlers - execution is never reached
here, only trigger-source and parameter validation) so
`LIVE_RESEARCH_RUN_EXECUTION`'s actual `allowed_trigger_sources` (N8N
allowed, API excluded, per `job_registry.py`) is exercised end-to-end,
rather than the permissive "allow every trigger source" test registry
used by `test_integration_api.py`'s generic HTTP-contract tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.api.dependencies import get_background_job_service
from stock_research_core.application.operations.job_registry import build_default_registry
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.operations.enums import BackgroundJobType, IntegrationClientStatus
from stock_research_core.domain.operations.models import IntegrationClient
from stock_research_core.infrastructure.operations.integration_auth import (
    generate_key_id,
    generate_raw_api_key,
    hash_api_key,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeQueue:
    async def enqueue(self, *, job_id, job_type, queue_name, priority, available_at):
        return f"task-{job_id}"


class FakeLock:
    async def acquire(self, *, key, owner_id, ttl_seconds, wait_timeout_seconds):
        return True

    async def release(self, *, key, owner_id):
        return True

    async def extend(self, *, key, owner_id, ttl_seconds):
        return True


@pytest.fixture
def real_registry_service(api_app, uow_factory) -> BackgroundJobService:
    handlers = {job_type: object() for job_type in BackgroundJobType}
    registry = build_default_registry(handlers)
    service = BackgroundJobService(
        unit_of_work_factory=uow_factory, job_registry=registry, job_queue=FakeQueue(), lock_port=FakeLock(),
    )
    api_app.dependency_overrides[get_background_job_service] = lambda: service
    yield service
    api_app.dependency_overrides.pop(get_background_job_service, None)


async def _create_integration_client(
    uow_factory, *, allowed_job_types: list[BackgroundJobType]
) -> tuple[str, str, uuid.UUID]:
    raw_key = generate_raw_api_key()
    client = IntegrationClient(
        name="Test n8n Live Research Client", key_id=generate_key_id(), api_key_hash=hash_api_key(raw_key),
        status=IntegrationClientStatus.ACTIVE, allowed_job_types=allowed_job_types,
    )
    async with uow_factory() as uow:
        created = await uow.integration_clients.create(client)
        await uow.commit()
    return created.key_id, raw_key, created.integration_id


def _headers(key_id: str, raw_key: str, *, invocation_id: str) -> dict[str, str]:
    return {
        "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key,
        "X-FinQuest-Request-ID": f"livequery-req:{invocation_id}",
        "Idempotency-Key": f"livequery-idem:{invocation_id}",
    }


class TestRegistryPermitsN8nExcludesApi:
    """Confirms the real (not test-relaxed) registry's
    `allowed_trigger_sources` for `LIVE_RESEARCH_RUN_EXECUTION` end-to-end
    through the HTTP boundary."""

    async def test_authorized_n8n_client_with_permission_can_trigger_general_question(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers=_headers(key_id, raw_key, invocation_id="inv-1"),
            json={
                "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
                "parameters": {
                    "original_question": "What recent developments may affect semiconductor demand?",
                    "scope": "GENERAL_QUESTION",
                },
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["job"]["job_type"] == "LIVE_RESEARCH_RUN_EXECUTION"
        assert body["job"]["status"] == "QUEUED"


class TestAuthorizationLayers:
    async def test_client_without_the_job_permission_is_rejected(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers=_headers(key_id, raw_key, invocation_id="inv-2"),
            json={
                "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
                "parameters": {
                    "original_question": "What recent developments may affect semiconductor demand?",
                    "scope": "GENERAL_QUESTION",
                },
            },
        )
        assert response.status_code == 422

    async def test_requested_by_integration_id_comes_from_authentication_not_parameters(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, integration_id = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers=_headers(key_id, raw_key, invocation_id="inv-3"),
            json={
                "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
                "parameters": {
                    "original_question": "Find recent material news about NVIDIA.", "scope": "NEWS_SCAN",
                    "subject_raw_text": "NVIDIA Corporation",
                },
            },
        )
        assert response.status_code == 202, response.text
        job_id = uuid.UUID(response.json()["job"]["job_id"])
        async with uow_factory() as uow:
            job = await uow.background_jobs.get_by_id(job_id)
        # requested_by_integration_id is only ever set server-side, from the
        # authenticated IntegrationClient - LiveResearchRunExecutionParameters
        # forbids extra fields, so a request body cannot even carry an
        # identity-shaped field, let alone have it override authentication.
        assert job.requested_by_integration_id == integration_id

    async def test_parameter_model_rejects_an_identity_shaped_extra_field(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers=_headers(key_id, raw_key, invocation_id="inv-3b"),
            json={
                "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
                "parameters": {
                    "original_question": "Find recent material news about NVIDIA.", "scope": "NEWS_SCAN",
                    "subject_raw_text": "NVIDIA Corporation",
                    "requested_by_integration_id": str(uuid4()),
                },
            },
        )
        assert response.status_code == 422


class TestParameterValidationBeforeEnqueue:
    async def test_market_data_snapshot_is_rejected_before_enqueue(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers=_headers(key_id, raw_key, invocation_id="inv-4"),
            json={"job_type": "LIVE_RESEARCH_RUN_EXECUTION", "parameters": {"scope": "MARKET_DATA_SNAPSHOT"}},
        )
        assert response.status_code == 422

    async def test_financial_filing_review_without_sec_cik_is_rejected(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers=_headers(key_id, raw_key, invocation_id="inv-5"),
            json={
                "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
                "parameters": {
                    "original_question": "Find the latest filings for Apple.", "scope": "FINANCIAL_FILING_REVIEW",
                    "subject_raw_text": "Apple Inc.",
                },
            },
        )
        assert response.status_code == 422

    async def test_company_overview_without_sec_concepts_is_rejected(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers=_headers(key_id, raw_key, invocation_id="inv-6"),
            json={
                "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
                "parameters": {
                    "original_question": "Give an overview of Apple.", "scope": "COMPANY_OVERVIEW",
                    "subject_raw_text": "Apple Inc.", "sec_cik": "0000320193",
                },
            },
        )
        assert response.status_code == 422


class TestIdempotencyAndInvocationScoping:
    async def test_same_invocation_id_with_same_body_replays_the_same_job(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        headers = _headers(key_id, raw_key, invocation_id="inv-7")
        body = {
            "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
            "parameters": {
                "original_question": "What is the analyst sentiment toward Microsoft?", "scope": "ANALYST_SENTIMENT",
                "subject_raw_text": "Microsoft Corporation",
            },
        }
        first = await api_client.post("/api/v1/integrations/n8n/jobs", headers=headers, json=body)
        second = await api_client.post("/api/v1/integrations/n8n/jobs", headers=headers, json=body)
        assert first.status_code == 202, first.text
        assert first.json()["job"]["job_id"] == second.json()["job"]["job_id"]
        assert second.json()["created"] is False

    async def test_same_request_id_with_a_conflicting_body_is_rejected(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        headers = _headers(key_id, raw_key, invocation_id="inv-8")
        await api_client.post(
            "/api/v1/integrations/n8n/jobs", headers=headers,
            json={
                "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
                "parameters": {"original_question": "First question.", "scope": "GENERAL_QUESTION"},
            },
        )
        conflicting = await api_client.post(
            "/api/v1/integrations/n8n/jobs", headers=headers,
            json={
                "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
                "parameters": {"original_question": "A totally different question.", "scope": "GENERAL_QUESTION"},
            },
        )
        assert conflicting.status_code == 409

    async def test_different_invocation_ids_create_different_jobs_for_identical_content(
        self, api_client, uow_factory, real_registry_service
    ) -> None:
        key_id, raw_key, _ = await _create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        body = {
            "job_type": "LIVE_RESEARCH_RUN_EXECUTION",
            "parameters": {"original_question": "Same question, independent invocation.", "scope": "GENERAL_QUESTION"},
        }
        first = await api_client.post(
            "/api/v1/integrations/n8n/jobs", headers=_headers(key_id, raw_key, invocation_id="inv-9a"), json=body
        )
        second = await api_client.post(
            "/api/v1/integrations/n8n/jobs", headers=_headers(key_id, raw_key, invocation_id="inv-9b"), json=body
        )
        assert first.status_code == 202 and second.status_code == 202
        assert first.json()["job"]["job_id"] != second.json()["job"]["job_id"]
        assert first.json()["created"] is True
        assert second.json()["created"] is True
