"""`/api/v1/integrations/n8n`: the n8n (or other automation) integration
surface.

Authenticated via `X-FinQuest-Key-Id` + `X-FinQuest-Integration-Key`
(never a learner JWT). Every job-trigger request must carry a stable
`X-FinQuest-Request-ID` (replay-audited via `integration_requests`) and
an `Idempotency-Key` (the same durable idempotency scope every other job
creation path uses). n8n never receives a database URL, a Redis URL, a
secret, a raw traceback, or any learner information unrelated to the
job it triggered.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request

from stock_research_core.api.dependencies import get_background_job_service, get_correlation_id, get_uow_factory, rate_limit
from stock_research_core.api.integration_dependencies import (
    get_integration_principal,
    require_external_request_id,
    require_idempotency_key,
)
from stock_research_core.api.schemas.integrations import (
    EvidenceItemSummary,
    EvidencePageResponse,
    IntegrationJobRequest,
    IntegrationReadinessResponse,
)
from stock_research_core.api.schemas.operations import BackgroundJobResponse, CreateJobResponse, JobEventResponse
from stock_research_core.application.exceptions import (
    BackgroundJobNotFoundError,
    IntegrationRequestConflictError,
    JobTypeNotAllowedError,
    LiveResearchEvidenceNotAvailableError,
)
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.live_research.enums import ResearchRunStatus
from stock_research_core.domain.models import utc_now
from stock_research_core.domain.operations.enums import (
    BackgroundJobStatus,
    BackgroundJobType,
    IntegrationRequestStatus,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import IntegrationClient, IntegrationRequest

router = APIRouter()

_JOB_TRIGGER_RATE_LIMIT = 30
_JOB_TRIGGER_RATE_WINDOW_SECONDS = 60

_EVIDENCE_NOT_AVAILABLE_MESSAGE = "Evidence is not available for this job."
_EVIDENCE_DEFAULT_LIMIT = 25
_EVIDENCE_MAX_LIMIT = 50


def _request_hash(job_type: str, parameters: dict) -> str:
    canonical = json.dumps({"job_type": job_type, "parameters": parameters}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@router.post(
    "/jobs", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a background job (only job types allowed for this integration client)",
    dependencies=[Depends(rate_limit(action="n8n_create_job", limit=_JOB_TRIGGER_RATE_LIMIT, window_seconds=_JOB_TRIGGER_RATE_WINDOW_SECONDS))],
)
async def create_job(
    body: IntegrationJobRequest,
    client: Annotated[IntegrationClient, Depends(get_integration_principal)],
    service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
    external_request_id: Annotated[str, Depends(require_external_request_id)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> CreateJobResponse:
    if body.job_type not in client.allowed_job_types:
        raise JobTypeNotAllowedError(
            f"Integration client '{client.name}' is not allowed to trigger job type {body.job_type.value}."
        )

    request_hash = _request_hash(body.job_type.value, body.parameters)

    async with uow_factory() as uow:  # type: UnitOfWorkPort
        existing = await uow.integration_requests.get_by_external_request_id(
            integration_id=client.integration_id, external_request_id=external_request_id
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IntegrationRequestConflictError(
                    "X-FinQuest-Request-ID was already used with a different request body."
                )
            if existing.job_id is None:
                raise IntegrationRequestConflictError(
                    "This request is still being processed; retry shortly."
                )
            job = await service.get_job(existing.job_id)
            return CreateJobResponse(job=BackgroundJobResponse.from_domain(job), created=False, duplicate_of_job_id=job.job_id)

        integration_request = await uow.integration_requests.create(
            IntegrationRequest(
                request_id=uuid4(), integration_id=client.integration_id, external_request_id=external_request_id,
                idempotency_key=idempotency_key, status=IntegrationRequestStatus.ACCEPTED,
                request_hash=request_hash, correlation_id=correlation_id,
            )
        )
        await uow.commit()

    try:
        result = await service.create_job(
            job_type=body.job_type, raw_parameters=body.parameters, idempotency_key=idempotency_key,
            trigger_source=JobTriggerSource.N8N, requested_by_integration_id=client.integration_id,
            correlation_id=correlation_id,
        )
    except Exception:
        async with uow_factory() as uow:
            await uow.integration_requests.mark_failed(integration_request.request_id, completed_at=utc_now())
            await uow.commit()
        raise

    async with uow_factory() as uow:
        await uow.integration_requests.mark_completed(
            integration_request.request_id, job_id=result.job.job_id, completed_at=utc_now()
        )
        await uow.commit()

    return CreateJobResponse(
        job=BackgroundJobResponse.from_domain(result.job), created=result.created,
        duplicate_of_job_id=result.duplicate_of_job_id,
    )


async def _get_own_job(
    job_id: UUID, client: IntegrationClient, service: BackgroundJobService
) -> BackgroundJobResponse:
    job = await service.get_job(job_id)
    if job.requested_by_integration_id != client.integration_id:
        # Same generic not-found used for any non-owner - never reveals
        # that a job triggered by a different integration exists.
        raise BackgroundJobNotFoundError(f"No background job found with id '{job_id}'.")
    return BackgroundJobResponse.from_domain(job)


@router.get("/jobs/{job_id}", response_model=BackgroundJobResponse, summary="Get a job this integration client created")
async def get_job(
    job_id: UUID,
    client: Annotated[IntegrationClient, Depends(get_integration_principal)],
    service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
) -> BackgroundJobResponse:
    return await _get_own_job(job_id, client, service)


@router.get(
    "/jobs/{job_id}/events", response_model=list[JobEventResponse],
    summary="Poll safe job events for a job this integration client created",
)
async def get_job_events(
    job_id: UUID,
    client: Annotated[IntegrationClient, Depends(get_integration_principal)],
    service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
) -> list[JobEventResponse]:
    await _get_own_job(job_id, client, service)
    events = await service.list_events(job_id)
    return [JobEventResponse.from_domain(event) for event in events]


def _require_evidence_available(condition: bool) -> None:
    if not condition:
        raise LiveResearchEvidenceNotAvailableError(_EVIDENCE_NOT_AVAILABLE_MESSAGE)


@router.get(
    "/jobs/{job_id}/live-research/evidence", response_model=EvidencePageResponse,
    summary="Get a bounded, provenance-safe evidence page for a completed Live Research job this integration client created",
)
async def get_job_live_research_evidence(
    job_id: UUID,
    client: Annotated[IntegrationClient, Depends(get_integration_principal)],
    service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    limit: Annotated[int, Query(ge=1, le=_EVIDENCE_MAX_LIMIT)] = _EVIDENCE_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidencePageResponse:
    # Step 1 - ownership first. `_get_own_job` raises the same generic
    # BackgroundJobNotFoundError (-> 404) whether the job simply doesn't
    # exist or belongs to a different integration client - no job type or
    # lifecycle information is evaluated before this check passes.
    job = await service.get_job(job_id)
    if job.requested_by_integration_id != client.integration_id:
        raise BackgroundJobNotFoundError(f"No background job found with id '{job_id}'.")

    # Step 2 - correct job type.
    if job.job_type != BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION:
        raise LiveResearchEvidenceNotAvailableError(_EVIDENCE_NOT_AVAILABLE_MESSAGE)

    # Step 3 - the BackgroundJob itself must have succeeded. PENDING,
    # QUEUED, RUNNING, RETRY_SCHEDULED, FAILED, CANCELLED, and SKIPPED all
    # return the same bounded 409 - this endpoint is not a failure-debug
    # surface, and a FAILED job's operations error summary is exposed only
    # via the existing GET /jobs/{job_id} endpoint.
    if job.status != BackgroundJobStatus.SUCCEEDED:
        raise LiveResearchEvidenceNotAvailableError(_EVIDENCE_NOT_AVAILABLE_MESSAGE)

    # Step 4 - validate result_summary. A technically-SUCCEEDED job whose
    # research_run_status is FAILED/NO_EVIDENCE_FOUND fails this check too.
    result_summary: Any = job.result_summary
    _require_evidence_available(isinstance(result_summary, dict))
    _require_evidence_available(result_summary.get("research_run_status") == ResearchRunStatus.COMPLETED.value)
    evidence_recorded = result_summary.get("evidence_recorded")
    _require_evidence_available(isinstance(evidence_recorded, int) and not isinstance(evidence_recorded, bool) and evidence_recorded > 0)
    raw_run_id = result_summary.get("research_run_id")
    _require_evidence_available(raw_run_id is not None)
    try:
        research_run_id = UUID(str(raw_run_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LiveResearchEvidenceNotAvailableError(_EVIDENCE_NOT_AVAILABLE_MESSAGE) from exc

    # Correction V2: also parse research_request_id here, alongside
    # research_run_id - both are validated before any database access.
    raw_request_id = result_summary.get("research_request_id")
    _require_evidence_available(raw_request_id is not None)
    try:
        summary_request_id = UUID(str(raw_request_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LiveResearchEvidenceNotAvailableError(_EVIDENCE_NOT_AVAILABLE_MESSAGE) from exc

    async with uow_factory() as uow:  # type: UnitOfWorkPort
        # Step 5 - load and validate the ResearchRun from PostgreSQL; the
        # result_summary is never trusted as the lifecycle source of truth.
        research_run = await uow.research_runs.get(research_run_id)
        _require_evidence_available(research_run is not None)
        _require_evidence_available(research_run.status == ResearchRunStatus.COMPLETED)

        # Step 5b - job-to-run binding (Correction V2): result_summary's
        # own research_request_id must agree with the request_id the
        # loaded ResearchRun actually has. This catches a result_summary
        # that is internally inconsistent - e.g. it names a research_run_id
        # that is real, COMPLETED, and even owned by this same integration,
        # but that run does not belong to the request the summary claims -
        # before any ownership check runs.
        _require_evidence_available(research_run.request_id == summary_request_id)

        # Step 6 - revalidate ResearchRequest ownership as a second,
        # independent authorization layer, loading the exact
        # ResearchRequest via the now cross-validated request_id. Neither
        # research_run_id nor research_request_id from result_summary is
        # ever trusted for authorization by itself.
        research_request = await uow.research_requests.get(research_run.request_id)
        if research_request is None or research_request.requested_by_integration_id != client.integration_id:
            raise BackgroundJobNotFoundError(f"No background job found with id '{job_id}'.")

        # Step 7 - return a database-paginated, bounded evidence page.
        # Request one extra row so has_more never needs a separate COUNT(*).
        rows = await uow.evidence_items.list_page_for_run(research_run.run_id, limit=limit + 1, offset=offset)

    has_more = len(rows) > limit
    page_items = rows[:limit]
    return EvidencePageResponse(
        items=[EvidenceItemSummary.from_domain(item) for item in page_items],
        limit=limit, offset=offset, has_more=has_more,
        next_offset=(offset + limit) if has_more else None,
    )


@router.get("/ready", response_model=IntegrationReadinessResponse, summary="Integration-safe readiness summary")
async def integration_ready(
    request: Request, client: Annotated[IntegrationClient, Depends(get_integration_principal)],
) -> IntegrationReadinessResponse:
    engine: AsyncEngine = request.app.state.engine
    database_ready = False
    migration_up_to_date = False
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            database_ready = True
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            migration_up_to_date = result.scalar_one_or_none() is not None
    except Exception:  # noqa: BLE001 - readiness must never raise
        database_ready = False

    redis_client = getattr(request.app.state, "redis_client", None)
    redis_ready = False
    if redis_client is not None:
        try:
            redis_ready = bool(await redis_client.ping())
        except Exception:  # noqa: BLE001
            redis_ready = False

    return IntegrationReadinessResponse(
        ready=database_ready and redis_ready, database_ready=database_ready, redis_ready=redis_ready,
        migration_up_to_date=migration_up_to_date,
    )
