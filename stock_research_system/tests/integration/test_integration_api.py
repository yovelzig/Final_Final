"""Integration tests (real PostgreSQL, via `api_client`) for:

- `/api/v1/operations/*` - admin-only job control plane.
- `/api/v1/integrations/n8n/*` - n8n API-key authentication and
  replay-protected job triggering.

A fake, in-memory `BackgroundJobService` is substituted via
`app.dependency_overrides` for these tests - job *execution* (Celery/
Redis) is covered separately in `test_job_worker_integration.py`/
`test_operations_end_to_end.py`; these tests exercise the HTTP contract,
authentication, and authorization only.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from stock_research_core.api.dependencies import get_background_job_service
from stock_research_core.application.operations.job_registry import (
    BackgroundJobRegistry,
    JobRegistryEntry,
    NeverRetryPolicy,
)
from stock_research_core.application.operations.models import (
    PortfolioBatchValuationParameters,
    PortfolioValuationParameters,
)
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.operations.enums import (
    BackgroundJobType,
    IntegrationClientStatus,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import IntegrationClient
from stock_research_core.infrastructure.operations.integration_auth import (
    generate_key_id,
    generate_raw_api_key,
    hash_api_key,
)
from tests.integration.conftest import auth_headers, promote_role

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _email() -> str:
    return f"ops-{uuid.uuid4().hex[:10]}@example.com"


async def _admin_headers(api_client, uow_factory) -> dict[str, str]:
    email = _email()
    headers = await auth_headers(api_client, email=email)
    me = await api_client.get("/api/v1/auth/me", headers=headers)
    account_id = me.json()["account"]["account_id"]
    await promote_role(uow_factory, account_id=account_id, role="ADMIN")
    login = await api_client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPassword123!"})
    return {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}


class FakeQueue:
    """Stands in for Celery/Redis - these are HTTP-contract and
    authentication tests, not job-execution tests (see
    `test_job_worker_integration.py` for real Celery+Redis execution)."""

    async def enqueue(self, *, job_id, job_type, queue_name, priority, available_at):
        return f"task-{job_id}"


class FakeLock:
    async def acquire(self, *, key, owner_id, ttl_seconds, wait_timeout_seconds):
        return True

    async def release(self, *, key, owner_id):
        return True

    async def extend(self, *, key, owner_id, ttl_seconds):
        return True


def _build_test_registry() -> BackgroundJobRegistry:
    parameter_models = {
        BackgroundJobType.PORTFOLIO_VALUATION: PortfolioValuationParameters,
        BackgroundJobType.PORTFOLIO_BATCH_VALUATION: PortfolioBatchValuationParameters,
    }
    entries = []
    for job_type in BackgroundJobType:
        entries.append(JobRegistryEntry(
            job_type=job_type, parameter_model=parameter_models.get(job_type, PortfolioValuationParameters),
            queue_name="finquest.default", task_name=f"finquest.{job_type.value.lower()}",
            handler=object(), maximum_attempts=3, retry_policy=NeverRetryPolicy(), time_limit_seconds=60,
            resource_key_builder=lambda p: None, allowed_trigger_sources=frozenset(JobTriggerSource),
        ))
    return BackgroundJobRegistry(entries)


@pytest.fixture
def fake_service(api_app, uow_factory) -> BackgroundJobService:
    """A real `BackgroundJobService` (real PostgreSQL persistence via
    `uow_factory`), with only the queue and distributed lock faked out -
    so `integration_requests`' foreign key to `background_jobs` is always
    satisfied, exactly like production."""
    service = BackgroundJobService(
        unit_of_work_factory=uow_factory, job_registry=_build_test_registry(), job_queue=FakeQueue(),
        lock_port=FakeLock(),
    )
    api_app.dependency_overrides[get_background_job_service] = lambda: service
    yield service
    api_app.dependency_overrides.pop(get_background_job_service, None)


class TestOperationsApi:
    async def test_learner_cannot_access_operations_endpoints(self, api_client, fake_service) -> None:
        learner_headers = await auth_headers(api_client, email=_email())
        response = await api_client.get("/api/v1/operations/jobs", headers=learner_headers)
        assert response.status_code == 403

    async def test_admin_can_create_a_job(self, api_client, uow_factory, fake_service) -> None:
        admin_headers = await _admin_headers(api_client, uow_factory)
        response = await api_client.post(
            "/api/v1/operations/jobs", headers=admin_headers,
            json={
                "job_type": "PORTFOLIO_VALUATION",
                "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()},
                "idempotency_key": "admin-created-1",
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["created"] is True
        assert body["job"]["status"] == "QUEUED"

    async def test_admin_job_creation_is_idempotent(self, api_client, uow_factory, fake_service) -> None:
        admin_headers = await _admin_headers(api_client, uow_factory)
        payload = {
            "job_type": "PORTFOLIO_VALUATION",
            "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()},
            "idempotency_key": "admin-idem-key",
        }
        first = await api_client.post("/api/v1/operations/jobs", headers=admin_headers, json=payload)
        second = await api_client.post("/api/v1/operations/jobs", headers=admin_headers, json=payload)
        assert first.json()["job"]["job_id"] == second.json()["job"]["job_id"]
        assert second.json()["created"] is False

    async def test_admin_job_listing(self, api_client, uow_factory, fake_service) -> None:
        admin_headers = await _admin_headers(api_client, uow_factory)
        await api_client.post(
            "/api/v1/operations/jobs", headers=admin_headers,
            json={
                "job_type": "PORTFOLIO_VALUATION",
                "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()},
                "idempotency_key": "listing-key",
            },
        )
        response = await api_client.get("/api/v1/operations/jobs", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["total"] >= 1

    async def test_job_detail_not_found_returns_404(self, api_client, uow_factory, fake_service) -> None:
        admin_headers = await _admin_headers(api_client, uow_factory)
        response = await api_client.get(f"/api/v1/operations/jobs/{uuid.uuid4()}", headers=admin_headers)
        assert response.status_code == 404
        body = response.json()
        assert "correlation_id" in body["error"]

    async def test_cancel_job(self, api_client, uow_factory, fake_service) -> None:
        admin_headers = await _admin_headers(api_client, uow_factory)
        created = await api_client.post(
            "/api/v1/operations/jobs", headers=admin_headers,
            json={
                "job_type": "PORTFOLIO_VALUATION",
                "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()},
                "idempotency_key": "cancel-key",
            },
        )
        job_id = created.json()["job"]["job_id"]
        response = await api_client.post(f"/api/v1/operations/jobs/{job_id}/cancel", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"

    async def test_correlation_id_is_echoed(self, api_client, uow_factory, fake_service) -> None:
        admin_headers = await _admin_headers(api_client, uow_factory)
        response = await api_client.get(
            "/api/v1/operations/jobs", headers={**admin_headers, "X-Correlation-ID": "test-corr-id"}
        )
        assert response.headers["X-Correlation-ID"] == "test-corr-id"


class TestIntegrationApiAuthentication:
    async def _create_integration_client(self, uow_factory, *, allowed_job_types: list[BackgroundJobType]) -> tuple[str, str]:
        raw_key = generate_raw_api_key()
        client = IntegrationClient(
            name="Test n8n Client", key_id=generate_key_id(), api_key_hash=hash_api_key(raw_key),
            status=IntegrationClientStatus.ACTIVE, allowed_job_types=allowed_job_types,
        )
        async with uow_factory() as uow:
            created = await uow.integration_clients.create(client)
            await uow.commit()
        return created.key_id, raw_key

    async def test_missing_credentials_are_rejected(self, api_client, fake_service) -> None:
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            json={"job_type": "RETRIEVAL_EVALUATION", "parameters": {}},
        )
        assert response.status_code == 401

    async def test_unknown_key_id_is_rejected(self, api_client, fake_service) -> None:
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers={
                "X-FinQuest-Key-Id": "unknown", "X-FinQuest-Integration-Key": "whatever",
                "X-FinQuest-Request-ID": "req-1", "Idempotency-Key": "idem-1",
            },
            json={"job_type": "RETRIEVAL_EVALUATION", "parameters": {}},
        )
        assert response.status_code == 401

    async def test_wrong_key_is_rejected(self, api_client, uow_factory, fake_service) -> None:
        key_id, _raw_key = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers={
                "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": "totally-wrong-key",
                "X-FinQuest-Request-ID": "req-1", "Idempotency-Key": "idem-1",
            },
            json={"job_type": "RETRIEVAL_EVALUATION", "parameters": {}},
        )
        assert response.status_code == 401

    async def test_disabled_client_is_rejected(self, api_client, uow_factory, fake_service) -> None:
        from stock_research_core.domain.operations.enums import IntegrationClientStatus as Status

        key_id, raw_key = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION]
        )
        async with uow_factory() as uow:
            client = await uow.integration_clients.get_by_key_id(key_id)
            await uow.integration_clients.set_status(client.integration_id, status=Status.DISABLED)
            await uow.commit()

        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers={
                "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key,
                "X-FinQuest-Request-ID": "req-1", "Idempotency-Key": "idem-1",
            },
            json={"job_type": "RETRIEVAL_EVALUATION", "parameters": {}},
        )
        assert response.status_code == 401

    async def test_disallowed_job_type_is_rejected(self, api_client, uow_factory, fake_service) -> None:
        key_id, raw_key = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers={
                "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key,
                "X-FinQuest-Request-ID": "req-1", "Idempotency-Key": "idem-1",
            },
            json={"job_type": "TRACKED_MARKET_REFRESH", "parameters": {}},
        )
        assert response.status_code == 422

    async def test_valid_key_creates_a_job(self, api_client, uow_factory, fake_service) -> None:
        key_id, raw_key = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.PORTFOLIO_VALUATION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers={
                "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key,
                "X-FinQuest-Request-ID": "req-valid-1", "Idempotency-Key": "idem-valid-1",
            },
            json={"job_type": "PORTFOLIO_VALUATION", "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()}},
        )
        assert response.status_code == 202, response.text

    async def test_replay_with_same_body_returns_canonical_job(self, api_client, uow_factory, fake_service) -> None:
        key_id, raw_key = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.PORTFOLIO_VALUATION]
        )
        headers = {
            "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key,
            "X-FinQuest-Request-ID": "req-replay-1", "Idempotency-Key": "idem-replay-1",
        }
        body = {"job_type": "PORTFOLIO_VALUATION", "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()}}
        first = await api_client.post("/api/v1/integrations/n8n/jobs", headers=headers, json=body)
        second = await api_client.post("/api/v1/integrations/n8n/jobs", headers=headers, json=body)
        assert first.json()["job"]["job_id"] == second.json()["job"]["job_id"]
        assert second.json()["created"] is False

    async def test_replay_with_different_body_returns_409(self, api_client, uow_factory, fake_service) -> None:
        key_id, raw_key = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.PORTFOLIO_VALUATION]
        )
        headers = {
            "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key,
            "X-FinQuest-Request-ID": "req-conflict-1", "Idempotency-Key": "idem-conflict-1",
        }
        await api_client.post(
            "/api/v1/integrations/n8n/jobs", headers=headers,
            json={"job_type": "PORTFOLIO_VALUATION", "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()}},
        )
        conflicting = await api_client.post(
            "/api/v1/integrations/n8n/jobs", headers=headers,
            json={"job_type": "PORTFOLIO_VALUATION", "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()}},
        )
        assert conflicting.status_code == 409

    async def test_integration_can_only_view_its_own_jobs(self, api_client, uow_factory, fake_service) -> None:
        key_id_a, raw_key_a = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.PORTFOLIO_VALUATION]
        )
        key_id_b, raw_key_b = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.PORTFOLIO_VALUATION]
        )
        created = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers={
                "X-FinQuest-Key-Id": key_id_a, "X-FinQuest-Integration-Key": raw_key_a,
                "X-FinQuest-Request-ID": "req-own-1", "Idempotency-Key": "idem-own-1",
            },
            json={"job_type": "PORTFOLIO_VALUATION", "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()}},
        )
        job_id = created.json()["job"]["job_id"]

        as_owner = await api_client.get(
            f"/api/v1/integrations/n8n/jobs/{job_id}",
            headers={"X-FinQuest-Key-Id": key_id_a, "X-FinQuest-Integration-Key": raw_key_a},
        )
        as_other = await api_client.get(
            f"/api/v1/integrations/n8n/jobs/{job_id}",
            headers={"X-FinQuest-Key-Id": key_id_b, "X-FinQuest-Integration-Key": raw_key_b},
        )
        assert as_owner.status_code == 200
        assert as_other.status_code == 404  # generic not-found, never reveals another client's job

    async def test_client_last_used_at_is_updated(self, api_client, uow_factory, fake_service) -> None:
        key_id, raw_key = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.PORTFOLIO_VALUATION]
        )
        async with uow_factory() as uow:
            before = await uow.integration_clients.get_by_key_id(key_id)
        assert before.last_used_at is None

        await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers={
                "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key,
                "X-FinQuest-Request-ID": "req-lastused-1", "Idempotency-Key": "idem-lastused-1",
            },
            json={"job_type": "PORTFOLIO_VALUATION", "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()}},
        )
        async with uow_factory() as uow:
            after = await uow.integration_clients.get_by_key_id(key_id)
        assert after.last_used_at is not None

    async def test_raw_api_key_never_appears_in_the_response(self, api_client, uow_factory, fake_service) -> None:
        key_id, raw_key = await self._create_integration_client(
            uow_factory, allowed_job_types=[BackgroundJobType.PORTFOLIO_VALUATION]
        )
        response = await api_client.post(
            "/api/v1/integrations/n8n/jobs",
            headers={
                "X-FinQuest-Key-Id": key_id, "X-FinQuest-Integration-Key": raw_key,
                "X-FinQuest-Request-ID": "req-nokey-1", "Idempotency-Key": "idem-nokey-1",
            },
            json={"job_type": "PORTFOLIO_VALUATION", "parameters": {"portfolio_id": str(uuid.uuid4()), "as_of": NOW.isoformat()}},
        )
        assert raw_key not in response.text

    async def test_readiness_endpoint_requires_authentication(self, api_client) -> None:
        response = await api_client.get("/api/v1/integrations/n8n/ready")
        assert response.status_code == 401
