"""`/api/v1/admin/evaluations`: ADMIN-only quality-evaluation control
plane (Phase 13, spec section 22).

Run creation goes through the existing durable background-job engine
(`BackgroundJobService`) - PostgreSQL remains the canonical store, Redis
delivers, Celery executes - exactly like every other operational job
type; this router never runs an evaluation inline. Reads that don't
need `QualityEvaluationService`'s orchestration logic go straight
through the same `UnitOfWorkPort` factory every other router uses.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from stock_research_core.api.dependencies import (
    get_background_job_service,
    get_correlation_id,
    get_quality_evaluation_service,
    get_uow_factory,
    require_admin,
)
from stock_research_core.api.schemas.quality_evaluation import (
    ApproveBaselineRequest,
    CompareRunRequest,
    CreateRunRequest,
    CreateRunResponse,
    EvaluationRegressionReportResponse,
    ImportSuiteRequest,
    MetricComparisonResponse,
    QualityEvaluationBaselineListResponse,
    QualityEvaluationBaselineResponse,
    QualityEvaluationRunListResponse,
    QualityEvaluationRunResponse,
    QualityEvaluationSampleResultListResponse,
    QualityEvaluationSampleResultResponse,
    QualityEvaluationSuiteListResponse,
    QualityEvaluationSuiteResponse,
    QualityMetricResultListResponse,
    QualityMetricResultResponse,
)
from stock_research_core.application.exceptions import QualityEvaluationRunNotFoundError, QualityEvaluationSuiteNotFoundError
from stock_research_core.application.identity.models import AuthenticatedPrincipal
from stock_research_core.application.operations.models import RagasQualityEvaluationParameters
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.quality_evaluation.datasets import DatasetValidationError
from stock_research_core.application.quality_evaluation.service import QualityEvaluationService
from stock_research_core.domain.operations.enums import BackgroundJobType, JobTriggerSource
from stock_research_core.domain.quality_evaluation.enums import QualityEvaluationCaseStatus
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationSuite
from stock_research_core.infrastructure.quality_evaluation.dataset_loader import (
    MAX_DATASET_FILE_SIZE_BYTES,
    load_cases_from_file,
)

router = APIRouter(dependencies=[Depends(require_admin)])

_DEFAULT_LIST_LIMIT = 50

UowFactory = Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)]


# -- suites -----------------------------------------------


@router.get("/suites", response_model=QualityEvaluationSuiteListResponse, summary="List evaluation suites")
async def list_suites(uow_factory: UowFactory, limit: int = _DEFAULT_LIST_LIMIT, offset: int = 0) -> QualityEvaluationSuiteListResponse:
    async with uow_factory() as uow:
        suites = await uow.quality_evaluation_suites.list_suites(limit=limit, offset=offset)
    return QualityEvaluationSuiteListResponse(
        items=[QualityEvaluationSuiteResponse.from_domain(suite) for suite in suites], limit=limit, offset=offset,
    )


@router.post(
    "/suites/import", response_model=QualityEvaluationSuiteResponse, status_code=status.HTTP_201_CREATED,
    summary="Import a curated JSONL evaluation suite (never auto-approved)",
)
async def import_suite(
    uow_factory: UowFactory, metadata: Annotated[ImportSuiteRequest, Depends()], file: Annotated[UploadFile, File()],
) -> QualityEvaluationSuiteResponse:
    raw_bytes = await file.read(MAX_DATASET_FILE_SIZE_BYTES + 1)
    if len(raw_bytes) > MAX_DATASET_FILE_SIZE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Dataset file exceeds the size limit.")

    # Written to a caller-controlled temp file (never a caller-supplied
    # path) and always deleted, whether import succeeds or fails.
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "suite.jsonl"
        tmp_path.write_bytes(raw_bytes)

        async with uow_factory() as uow:
            existing = await uow.quality_evaluation_suites.get_suite_by_code_and_version(
                code=metadata.code, version=metadata.version
            )
            if existing is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, "This suite code/version has already been imported.")

            suite = await uow.quality_evaluation_suites.create_suite(
                QualityEvaluationSuite(
                    code=metadata.code, name=metadata.name, description=metadata.description,
                    suite_type=metadata.suite_type, version=metadata.version, case_count=0, dataset_hash="0" * 64,
                )
            )
            try:
                cases, dataset_hash = load_cases_from_file(tmp_path, suite_id=suite.suite_id, case_version=metadata.version)
            except DatasetValidationError:
                await uow.rollback()
                raise
            for case in cases:
                await uow.quality_evaluation_suites.create_case(case)
            updated = await uow.quality_evaluation_suites.update_suite_status(
                suite.suite_id, status=QualityEvaluationCaseStatus.DRAFT, case_count=len(cases),
            )
            await uow.commit()
    return QualityEvaluationSuiteResponse.from_domain(updated)


@router.get("/suites/{suite_id}", response_model=QualityEvaluationSuiteResponse, summary="Get one evaluation suite")
async def get_suite(suite_id: UUID, uow_factory: UowFactory) -> QualityEvaluationSuiteResponse:
    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.get_suite_by_id(suite_id)
    if suite is None:
        raise QualityEvaluationSuiteNotFoundError(f"Suite '{suite_id}' not found.")
    return QualityEvaluationSuiteResponse.from_domain(suite)


@router.post("/suites/{suite_id}/approve", response_model=QualityEvaluationSuiteResponse, summary="Approve a suite (ADMIN only)")
async def approve_suite(
    suite_id: UUID, service: Annotated[QualityEvaluationService, Depends(get_quality_evaluation_service)],
) -> QualityEvaluationSuiteResponse:
    updated = await service.approve_suite(suite_id=suite_id)
    return QualityEvaluationSuiteResponse.from_domain(updated)


@router.post("/suites/{suite_id}/archive", response_model=QualityEvaluationSuiteResponse, summary="Archive a suite")
async def archive_suite(suite_id: UUID, uow_factory: UowFactory) -> QualityEvaluationSuiteResponse:
    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.get_suite_by_id(suite_id)
        if suite is None:
            raise QualityEvaluationSuiteNotFoundError(f"Suite '{suite_id}' not found.")
        updated = await uow.quality_evaluation_suites.update_suite_status(suite_id, status=QualityEvaluationCaseStatus.ARCHIVED)
        await uow.commit()
    return QualityEvaluationSuiteResponse.from_domain(updated)


# -- runs -----------------------------------------------


@router.post(
    "/runs", response_model=CreateRunResponse, status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a new evaluation run",
)
async def create_run(
    body: CreateRunRequest,
    job_service: Annotated[BackgroundJobService, Depends(get_background_job_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
) -> CreateRunResponse:
    parameters = RagasQualityEvaluationParameters(
        suite_id=body.suite_id, mode=body.mode.value, maximum_cases=body.maximum_cases,
        maximum_concurrency=body.maximum_concurrency,
    )
    result = await job_service.create_job(
        job_type=BackgroundJobType.RAGAS_QUALITY_EVALUATION, raw_parameters=parameters.model_dump(mode="json"),
        idempotency_key=body.idempotency_key, trigger_source=JobTriggerSource.API,
        requested_by_account_id=principal.account_id, correlation_id=correlation_id,
    )
    return CreateRunResponse(job_id=result.job.job_id, suite_id=body.suite_id, mode=body.mode)


@router.get("/runs", response_model=QualityEvaluationRunListResponse, summary="List evaluation runs")
async def list_runs(uow_factory: UowFactory, limit: int = _DEFAULT_LIST_LIMIT, offset: int = 0) -> QualityEvaluationRunListResponse:
    async with uow_factory() as uow:
        runs = await uow.quality_evaluation_runs.list_recent(limit=limit, offset=offset)
    return QualityEvaluationRunListResponse(
        items=[QualityEvaluationRunResponse.from_domain(run) for run in runs], limit=limit, offset=offset,
    )


@router.get("/runs/{run_id}", response_model=QualityEvaluationRunResponse, summary="Get one evaluation run")
async def get_run(run_id: UUID, uow_factory: UowFactory) -> QualityEvaluationRunResponse:
    async with uow_factory() as uow:
        run = await uow.quality_evaluation_runs.get_by_id(run_id)
    if run is None:
        raise QualityEvaluationRunNotFoundError(f"Run '{run_id}' not found.")
    return QualityEvaluationRunResponse.from_domain(run)


@router.get(
    "/runs/{run_id}/samples", response_model=QualityEvaluationSampleResultListResponse,
    summary="List one run's per-case sample results",
)
async def list_run_samples(
    run_id: UUID, uow_factory: UowFactory, limit: int = 200, offset: int = 0,
) -> QualityEvaluationSampleResultListResponse:
    async with uow_factory() as uow:
        samples = await uow.quality_evaluation_results.list_sample_results_for_run(run_id, limit=limit, offset=offset)
    return QualityEvaluationSampleResultListResponse(
        items=[QualityEvaluationSampleResultResponse.from_domain(sample) for sample in samples]
    )


@router.get(
    "/runs/{run_id}/metrics", response_model=QualityMetricResultListResponse, summary="List one run's metric results",
)
async def list_run_metrics(run_id: UUID, uow_factory: UowFactory) -> QualityMetricResultListResponse:
    async with uow_factory() as uow:
        metrics = await uow.quality_evaluation_results.list_metric_results_for_run(run_id)
    return QualityMetricResultListResponse(items=[QualityMetricResultResponse.from_domain(metric) for metric in metrics])


@router.post(
    "/runs/{run_id}/compare", response_model=EvaluationRegressionReportResponse,
    summary="Compare a run against an approved baseline",
)
async def compare_run(
    run_id: UUID, body: CompareRunRequest,
    service: Annotated[QualityEvaluationService, Depends(get_quality_evaluation_service)],
) -> EvaluationRegressionReportResponse:
    report = await service.compare_with_baseline(run_id=run_id, baseline_id=body.baseline_id)
    return EvaluationRegressionReportResponse(
        run_id=report.run_id, baseline_id=report.baseline_id, comparable=report.comparable,
        overall_result=report.overall_result.value,
        metric_comparisons=[
            MetricComparisonResponse(
                metric_name=comparison.metric_name, baseline_value=comparison.baseline_value,
                candidate_value=comparison.candidate_value, result=comparison.result.value, detail=comparison.detail,
            )
            for comparison in report.metric_comparisons
        ],
        notes=report.notes,
    )


# -- baselines -----------------------------------------------


@router.get("/baselines", response_model=QualityEvaluationBaselineListResponse, summary="List baselines for a suite")
async def list_baselines(suite_id: UUID, uow_factory: UowFactory) -> QualityEvaluationBaselineListResponse:
    async with uow_factory() as uow:
        baselines = await uow.quality_evaluation_baselines.list_for_suite(suite_id)
    return QualityEvaluationBaselineListResponse(
        items=[QualityEvaluationBaselineResponse.from_domain(baseline) for baseline in baselines]
    )


@router.post(
    "/runs/{run_id}/approve-baseline", response_model=QualityEvaluationBaselineResponse,
    summary="Approve a run's metrics as the new baseline (ADMIN only, never automatic)",
)
async def approve_baseline(
    run_id: UUID, body: ApproveBaselineRequest,
    service: Annotated[QualityEvaluationService, Depends(get_quality_evaluation_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
) -> QualityEvaluationBaselineResponse:
    baseline = await service.approve_baseline(run_id=run_id, name=body.name, approved_by_account_id=principal.account_id)
    return QualityEvaluationBaselineResponse.from_domain(baseline)


@router.get("/baselines/{baseline_id}", response_model=QualityEvaluationBaselineResponse, summary="Get one baseline")
async def get_baseline(baseline_id: UUID, uow_factory: UowFactory) -> QualityEvaluationBaselineResponse:
    async with uow_factory() as uow:
        baseline = await uow.quality_evaluation_baselines.get_by_id(baseline_id)
    if baseline is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Baseline not found.")
    return QualityEvaluationBaselineResponse.from_domain(baseline)
