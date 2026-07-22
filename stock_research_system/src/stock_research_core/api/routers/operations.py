"""`/api/v1/operations`: admin-protected background-job control plane.

Every job type in this Phase 11 release is an internal/system job (market
refresh, portfolio batch valuation, knowledge maintenance, retrieval
evaluation) - none is currently learner-owned, so every endpoint here
requires ADMIN. If a future learner-owned job type is introduced, its
detail endpoint should additionally allow the owning learner via
`ensure_owned_by_learner`, matching every other router in this API.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from stock_research_core.api.dependencies import get_background_job_service, get_correlation_id, require_admin
from stock_research_core.api.schemas.operations import (
    BackgroundJobResponse,
    CreateJobRequest,
    CreateJobResponse,
    JobAttemptResponse,
    JobDetailResponse,
    JobEventResponse,
    JobListResponse,
    MetricsSummaryResponse,
)
from stock_research_core.application.identity.models import AuthenticatedPrincipal
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.models import utc_now
from stock_research_core.domain.operations.enums import BackgroundJobStatus, BackgroundJobType, JobTriggerSource

router = APIRouter(dependencies=[Depends(require_admin)])

_DEFAULT_LIST_LIMIT = 50


@router.post(
    "/jobs", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED,
    summary="Create (or idempotently return) a background job",
)
async def create_job(
    body: CreateJobRequest,
    service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
) -> CreateJobResponse:
    result = await service.create_job(
        job_type=body.job_type, raw_parameters=body.parameters, idempotency_key=body.idempotency_key,
        trigger_source=JobTriggerSource.API, requested_by_account_id=principal.account_id,
        priority=body.priority, available_at=body.available_at, correlation_id=correlation_id,
    )
    return CreateJobResponse(
        job=BackgroundJobResponse.from_domain(result.job), created=result.created,
        duplicate_of_job_id=result.duplicate_of_job_id,
    )


@router.get("/jobs", response_model=JobListResponse, summary="List background jobs")
async def list_jobs(
    service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
    job_type: BackgroundJobType | None = None,
    status_filter: Annotated[BackgroundJobStatus | None, Query(alias="status")] = None,
    trigger_source: JobTriggerSource | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    filters = dict(
        job_type=job_type, status=status_filter,
        trigger_source=trigger_source.value if trigger_source else None,
        created_after=created_after, created_before=created_before,
    )
    jobs = await service.list_jobs(**filters, limit=limit, offset=offset)
    total = await service.count_jobs(**filters)
    return JobListResponse(
        items=[BackgroundJobResponse.from_domain(job) for job in jobs], limit=limit, offset=offset, total=total,
    )


@router.get("/jobs/{job_id}", response_model=JobDetailResponse, summary="Get one job's full detail")
async def get_job(
    job_id: UUID, service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
) -> JobDetailResponse:
    job = await service.get_job(job_id)
    attempts = await service.list_attempts(job_id)
    events = await service.list_events(job_id)
    return JobDetailResponse(
        job=BackgroundJobResponse.from_domain(job),
        attempts=[JobAttemptResponse.from_domain(attempt) for attempt in attempts],
        events=[JobEventResponse.from_domain(event) for event in events],
    )


@router.post("/jobs/{job_id}/cancel", response_model=BackgroundJobResponse, summary="Cancel a non-terminal job")
async def cancel_job(
    job_id: UUID, service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
) -> BackgroundJobResponse:
    job = await service.cancel_job(job_id)
    return BackgroundJobResponse.from_domain(job)


@router.post(
    "/jobs/{job_id}/requeue", response_model=BackgroundJobResponse,
    summary="Requeue a FAILED or RETRY_SCHEDULED job that has not exhausted its maximum attempts",
)
async def requeue_job(
    job_id: UUID, service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
) -> BackgroundJobResponse:
    job = await service.requeue_job(job_id)
    return BackgroundJobResponse.from_domain(job)


@router.get("/metrics-summary", response_model=MetricsSummaryResponse, summary="A small, safe operational summary")
async def metrics_summary(
    service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
) -> MetricsSummaryResponse:
    jobs_by_status = {
        job_status.value: await service.count_jobs(status=job_status) for job_status in BackgroundJobStatus
    }
    cutoff = utc_now() - timedelta(hours=24)
    created_24h = await service.count_jobs(created_after=cutoff)
    failed_24h = await service.count_jobs(status=BackgroundJobStatus.FAILED, created_after=cutoff)
    return MetricsSummaryResponse(
        jobs_by_status=jobs_by_status, jobs_created_last_24h=created_24h, jobs_failed_last_24h=failed_24h,
    )
