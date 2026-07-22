"""Integration tests for `/api/v1/admin/evaluations` against the real
PostgreSQL test database, driven over HTTP (spec section 28.10).

Run *creation* only proves a background job was queued with the right
type/parameters - there is no live Celery worker consuming the test
database's queue in this test environment (the docker-compose worker
points at the dev database, not `_test`), so read-endpoint tests
(samples/metrics/compare) seed their run/sample/metric rows directly
through the repositories, exactly as `RagasQualityEvaluationJobHandler`
itself would have written them.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid

import pytest

from stock_research_core.domain.quality_evaluation.enums import (
    EvaluationCaseContextType,
    QualityEvaluationCaseStatus,
    QualityEvaluationMode,
    QualityEvaluationRunStatus,
    QualityEvaluationSuiteType,
    QualityGateStatus,
    QualityMetricType,
)
from stock_research_core.domain.quality_evaluation.models import (
    QualityEvaluationCase,
    QualityEvaluationRun,
    QualityEvaluationSampleResult,
    QualityEvaluationSuite,
    QualityMetricResult,
)
from tests.integration.conftest import auth_headers, promote_role

pytestmark = pytest.mark.integration

VALID_HASH = hashlib.sha256(b"fixture").hexdigest()


def _email() -> str:
    return f"qe-api-{uuid.uuid4().hex[:10]}@example.com"


async def _admin_headers(api_client, uow_factory) -> dict[str, str]:
    email = _email()
    body_headers = await auth_headers(api_client, email=email)
    me = await api_client.get("/api/v1/auth/me", headers=body_headers)
    account_id = me.json()["account"]["account_id"]
    await promote_role(uow_factory, account_id=account_id, role="ADMIN")
    login = await api_client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPassword123!"})
    return {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}


def _jsonl_bytes(*records: dict) -> bytes:
    return "\n".join(json.dumps(record) for record in records).encode("utf-8")


async def test_non_admin_is_denied(api_client) -> None:
    learner_headers = await auth_headers(api_client, email=_email())
    response = await api_client.get("/api/v1/admin/evaluations/suites", headers=learner_headers)
    assert response.status_code == 403


async def test_openapi_schema_exposes_the_evaluation_paths(api_client) -> None:
    response = await api_client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/admin/evaluations/suites" in paths
    assert "/api/v1/admin/evaluations/runs" in paths
    assert "/api/v1/admin/evaluations/runs/{run_id}/approve-baseline" in paths


async def test_import_validate_approve_suite_flow(api_client, uow_factory) -> None:
    headers = await _admin_headers(api_client, uow_factory)
    code = f"QE_API_TEST_{uuid.uuid4().hex[:8].upper()}"
    content = _jsonl_bytes(
        {
            "external_case_id": "api-case-1", "context_type": "GENERAL_RAG", "user_input": "What is a bond?",
            "required_concepts": ["bond"],
        }
    )
    response = await api_client.post(
        "/api/v1/admin/evaluations/suites/import",
        params={"code": code, "name": "API test suite", "suite_type": "RAG_SINGLE_TURN", "version": "v1"},
        files={"file": ("suite.jsonl", io.BytesIO(content), "application/jsonl")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["case_count"] == 1
    suite_id = body["suite_id"]

    # Importing the exact same code/version again is rejected, not
    # silently duplicated.
    duplicate = await api_client.post(
        "/api/v1/admin/evaluations/suites/import",
        params={"code": code, "name": "API test suite", "suite_type": "RAG_SINGLE_TURN", "version": "v1"},
        files={"file": ("suite.jsonl", io.BytesIO(content), "application/jsonl")},
        headers=headers,
    )
    assert duplicate.status_code == 409

    approved = await api_client.post(f"/api/v1/admin/evaluations/suites/{suite_id}/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    fetched = await api_client.get(f"/api/v1/admin/evaluations/suites/{suite_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "APPROVED"

    listed = await api_client.get("/api/v1/admin/evaluations/suites", headers=headers)
    assert listed.status_code == 200
    assert any(item["suite_id"] == suite_id for item in listed.json()["items"])


async def test_import_rejects_a_malformed_dataset(api_client, uow_factory) -> None:
    headers = await _admin_headers(api_client, uow_factory)
    bad_content = b"{not valid json}"
    response = await api_client.post(
        "/api/v1/admin/evaluations/suites/import",
        params={
            "code": f"QE_BAD_{uuid.uuid4().hex[:8].upper()}", "name": "Bad suite", "suite_type": "SAFETY", "version": "v1",
        },
        files={"file": ("suite.jsonl", io.BytesIO(bad_content), "application/jsonl")},
        headers=headers,
    )
    assert response.status_code == 422


async def test_create_run_returns_202_and_queues_a_job(api_client, uow_factory) -> None:
    headers = await _admin_headers(api_client, uow_factory)
    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.create_suite(
            QualityEvaluationSuite(
                code=f"QE_API_RUN_{uuid.uuid4().hex[:8].upper()}", name="Run test suite",
                suite_type=QualityEvaluationSuiteType.SAFETY, version="v1", case_count=0, dataset_hash=VALID_HASH,
            )
        )
        await uow.commit()
        await uow.quality_evaluation_suites.update_suite_status(suite.suite_id, status=QualityEvaluationCaseStatus.APPROVED)
        await uow.commit()

    response = await api_client.post(
        "/api/v1/admin/evaluations/runs",
        json={
            "suite_id": str(suite.suite_id), "mode": "DETERMINISTIC", "idempotency_key": f"key-{uuid.uuid4()}",
            "system_version": "1.0", "retrieval_policy_version": "v1", "embedding_model": "fake",
            "embedding_version": "v1", "tutor_policy_version": "v1", "prompt_version": "v1", "guardrail_version": "v1",
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["suite_id"] == str(suite.suite_id)
    assert "job_id" in body

    async with uow_factory() as uow:
        job = await uow.background_jobs.get_by_id(uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.job_type.value == "RAGAS_QUALITY_EVALUATION"


async def test_run_samples_and_metrics_endpoints(api_client, uow_factory) -> None:
    headers = await _admin_headers(api_client, uow_factory)
    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.create_suite(
            QualityEvaluationSuite(
                code=f"QE_API_READ_{uuid.uuid4().hex[:8].upper()}", name="Read test suite",
                suite_type=QualityEvaluationSuiteType.SAFETY, version="v1", case_count=1, dataset_hash=VALID_HASH,
            )
        )
        case = await uow.quality_evaluation_suites.create_case(
            QualityEvaluationCase(
                suite_id=suite.suite_id, external_case_id="read-case", context_type=EvaluationCaseContextType.GENERAL_RAG,
                user_input="What is a stock?", case_version="v1", required_concepts=["stock"],
            )
        )
        run = await uow.quality_evaluation_runs.create(
            QualityEvaluationRun(
                suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, system_version="1.0",
                retrieval_policy_version="v1", embedding_model="fake", embedding_version="v1",
                tutor_policy_version="v1", prompt_version="v1", guardrail_version="v1",
                dataset_hash=VALID_HASH, configuration_hash=VALID_HASH,
            )
        )
        sample = await uow.quality_evaluation_results.create_sample_result(
            QualityEvaluationSampleResult(
                run_id=run.run_id, case_id=case.case_id, status=QualityGateStatus.PASS,
                generated_response="A stock is a share of ownership in a company. " * 6
                + "This sentence, repeated, pushes the text safely past two hundred characters "
                "so the API preview-truncation path is actually exercised by this test and never leaks the full text.",
            )
        )
        await uow.quality_evaluation_results.bulk_create_metric_results(
            [
                QualityMetricResult(
                    run_id=run.run_id, sample_result_id=sample.sample_result_id, metric_name="required_concept_coverage",
                    metric_type=QualityMetricType.DETERMINISTIC, metric_version="v1", score=1.0,
                )
            ]
        )
        await uow.commit()

    run_response = await api_client.get(f"/api/v1/admin/evaluations/runs/{run.run_id}", headers=headers)
    assert run_response.status_code == 200
    assert run_response.json()["run_id"] == str(run.run_id)

    samples_response = await api_client.get(f"/api/v1/admin/evaluations/runs/{run.run_id}/samples", headers=headers)
    assert samples_response.status_code == 200
    items = samples_response.json()["items"]
    assert len(items) == 1
    # Never the full generated response - only a bounded preview.
    assert len(items[0]["generated_response_preview"]) <= 200
    assert items[0]["generated_response_preview"] != sample.generated_response

    metrics_response = await api_client.get(f"/api/v1/admin/evaluations/runs/{run.run_id}/metrics", headers=headers)
    assert metrics_response.status_code == 200
    assert any(m["metric_name"] == "required_concept_coverage" for m in metrics_response.json()["items"])


async def test_approve_baseline_and_compare(api_client, uow_factory) -> None:
    headers = await _admin_headers(api_client, uow_factory)
    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.create_suite(
            QualityEvaluationSuite(
                code=f"QE_API_BASELINE_{uuid.uuid4().hex[:8].upper()}", name="Baseline test suite",
                suite_type=QualityEvaluationSuiteType.SAFETY, version="v1", case_count=0, dataset_hash=VALID_HASH,
            )
        )
        run = await uow.quality_evaluation_runs.create(
            QualityEvaluationRun(
                suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, system_version="1.0",
                retrieval_policy_version="v1", embedding_model="fake", embedding_version="v1",
                tutor_policy_version="v1", prompt_version="v1", guardrail_version="v1",
                dataset_hash=VALID_HASH, configuration_hash=VALID_HASH,
            )
        )
        await uow.commit()

    approve_response = await api_client.post(
        f"/api/v1/admin/evaluations/runs/{run.run_id}/approve-baseline", json={"name": "v1-baseline"}, headers=headers,
    )
    assert approve_response.status_code == 200
    baseline = approve_response.json()
    assert baseline["approved"] is True

    fetched = await api_client.get(f"/api/v1/admin/evaluations/baselines/{baseline['baseline_id']}", headers=headers)
    assert fetched.status_code == 200

    listed = await api_client.get(
        "/api/v1/admin/evaluations/baselines", params={"suite_id": str(suite.suite_id)}, headers=headers
    )
    assert listed.status_code == 200
    assert any(item["baseline_id"] == baseline["baseline_id"] for item in listed.json()["items"])

    compare_response = await api_client.post(
        f"/api/v1/admin/evaluations/runs/{run.run_id}/compare", json={"baseline_id": baseline["baseline_id"]},
        headers=headers,
    )
    assert compare_response.status_code == 200
    assert compare_response.json()["comparable"] is True
