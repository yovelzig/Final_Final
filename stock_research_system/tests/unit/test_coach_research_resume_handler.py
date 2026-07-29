"""Unit tests for `CoachResearchResumeJobHandler` (spec G2D2 section 16) -
the full resume-verification-order matrix, with in-memory fakes for
every repository and no real LangGraph/Postgres/Redis required.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import (
    CoachResearchResumeInconsistentJobError,
    CoachResearchResumeOwnershipError,
    CoachResearchResumeStateConflictError,
)
from stock_research_core.application.operations.handlers import CoachResearchResumeJobHandler
from stock_research_core.application.operations.models import CoachResearchResumeParameters
from stock_research_core.application.operations.ports import JobExecutionContext
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus
from stock_research_core.domain.learning_orchestrator.models import LearningOrchestratorRun
from stock_research_core.domain.live_research.enums import FailureCategory, ResearchRunStatus, ResearchScope
from stock_research_core.domain.live_research.models import ResearchRequest, ResearchRun
from stock_research_core.domain.operations.enums import BackgroundJobStatus, BackgroundJobType, JobTriggerSource
from stock_research_core.domain.operations.models import BackgroundJob

from tests.unit.learning_orchestrator_fakes import FakeRunRepo

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _hash() -> str:
    return hashlib.sha256(uuid4().bytes).hexdigest()


class _FakeBackgroundJobRepo:
    def __init__(self) -> None:
        self.jobs: dict = {}

    async def get_by_id(self, job_id):
        return self.jobs.get(job_id)


class _FakeResearchRunRepo:
    def __init__(self) -> None:
        self.runs: dict = {}

    async def get(self, run_id, *, for_update: bool = False):
        return self.runs.get(run_id)


class _FakeResearchRequestRepo:
    def __init__(self) -> None:
        self.requests: dict = {}

    async def get(self, request_id):
        return self.requests.get(request_id)


class _FakeUoW:
    def __init__(self, *, runs=None, background_jobs=None, research_runs=None, research_requests=None):
        self.learning_orchestrator_runs = runs or FakeRunRepo()
        self.background_jobs = background_jobs or _FakeBackgroundJobRepo()
        self.research_runs = research_runs or _FakeResearchRunRepo()
        self.research_requests = research_requests or _FakeResearchRequestRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def commit(self) -> None:
        pass


class _FakeProgress:
    def __init__(self) -> None:
        self.reports: list = []

    async def report(self, *, current, total, message=None):
        self.reports.append((current, total, message))


class _FakeLearningOrchestratorService:
    def __init__(self, *, resulting_run: LearningOrchestratorRun) -> None:
        self.resulting_run = resulting_run
        self.calls: list = []

    async def resume_from_research(self, *, run_id, resume_value):
        self.calls.append({"run_id": run_id, "resume_value": resume_value})
        return self.resulting_run


def _coach_run(**overrides) -> LearningOrchestratorRun:
    fields = dict(
        thread_id=uuid4(), learner_id=uuid4(), trusted_account_id=uuid4(), idempotency_key=f"key-{uuid4()}",
        correlation_id=str(uuid4()), graph_version="learning-coach-graph-v1",
        status=LearningOrchestratorRunStatus.WAITING_FOR_RESEARCH, waiting_at=NOW, research_job_id=uuid4(),
    )
    fields.update(overrides)
    return LearningOrchestratorRun(**fields)


def _background_job(**overrides) -> BackgroundJob:
    fields = dict(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, status=BackgroundJobStatus.SUCCEEDED,
        trigger_source=JobTriggerSource.SYSTEM, idempotency_key=f"key-{uuid4()}", queue_name="finquest.research",
        task_name="finquest.live_research_run_execution", started_at=NOW, completed_at=NOW,
        result_summary={"placeholder": True},
    )
    fields.update(overrides)
    return BackgroundJob(**fields)


def _context(*, idempotency_key: str = "coach-resume-key") -> JobExecutionContext:
    return JobExecutionContext(
        job_id=uuid4(), job_type=BackgroundJobType.COACH_RESEARCH_RESUME, trigger_source=JobTriggerSource.SYSTEM,
        requested_by_account_id=None, requested_by_integration_id=None, idempotency_key=idempotency_key,
        correlation_id=None, attempt_number=1,
    )


async def test_evidence_found_resumes_with_verified_outcome_metadata() -> None:
    account_id = uuid4()
    coach_run = _coach_run(trusted_account_id=account_id)
    request_id, research_run_id, live_research_job_id = uuid4(), uuid4(), coach_run.research_job_id

    research_request = ResearchRequest(
        request_id=request_id, requested_by_account_id=account_id, original_question="What happened to Nvidia?",
        normalized_query="what happened to nvidia", scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key="req-key", request_hash=_hash(),
    )
    research_run = ResearchRun(
        run_id=research_run_id, request_id=request_id, attempt_number=1, status=ResearchRunStatus.COMPLETED,
        completed_at=NOW,
    )
    job = _background_job(
        job_id=live_research_job_id, requested_by_account_id=account_id,
        result_summary={
            "research_run_status": "COMPLETED", "failure_category": None, "evidence_recorded": 5,
            "research_request_id": str(request_id), "research_run_id": str(research_run_id),
        },
    )

    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(
        runs=run_repo,
        background_jobs=_FakeBackgroundJobRepo(),
        research_runs=_FakeResearchRunRepo(),
        research_requests=_FakeResearchRequestRepo(),
    )
    uow.background_jobs.jobs[live_research_job_id] = job
    uow.research_runs.runs[research_run_id] = research_run
    uow.research_requests.requests[request_id] = research_request

    resulting_run = coach_run.model_copy(update={"status": LearningOrchestratorRunStatus.SUCCEEDED})
    service = _FakeLearningOrchestratorService(resulting_run=resulting_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)

    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=live_research_job_id,
    )
    outcome = await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())

    assert outcome.result_summary["outcome"] == "EVIDENCE_FOUND"
    assert outcome.result_summary["final_status"] == "SUCCEEDED"
    assert service.calls[0]["resume_value"] == {
        "outcome": "EVIDENCE_FOUND", "research_run_id": str(research_run_id), "evidence_count": 5,
    }
    # Never raw evidence, only outcome metadata.
    assert "evidence" not in str(service.calls[0]["resume_value"].get("evidence_items", ""))


async def test_no_evidence_found_resumes_without_touching_research_run_or_request() -> None:
    account_id = uuid4()
    coach_run = _coach_run(trusted_account_id=account_id)
    job = _background_job(
        job_id=coach_run.research_job_id, requested_by_account_id=account_id,
        result_summary={"research_run_status": "FAILED", "failure_category": "NO_EVIDENCE_FOUND", "evidence_recorded": 0},
    )
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    uow.background_jobs.jobs[job.job_id] = job

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=job.job_id,
    )
    outcome = await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())

    assert outcome.result_summary["outcome"] == "NO_EVIDENCE_FOUND"
    assert service.calls[0]["resume_value"] == {"outcome": "NO_EVIDENCE_FOUND", "evidence_count": 0}


async def test_provider_failure_resumes_without_requiring_research_ids() -> None:
    account_id = uuid4()
    coach_run = _coach_run(trusted_account_id=account_id)
    job = _background_job(
        job_id=coach_run.research_job_id, requested_by_account_id=account_id, status=BackgroundJobStatus.FAILED,
        result_summary={"error_code": "PROVIDER_ERROR"},
    )
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    uow.background_jobs.jobs[job.job_id] = job

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=job.job_id,
    )
    outcome = await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())
    assert outcome.result_summary["outcome"] == "PROVIDER_FAILURE"


async def test_cancelled_job_resumes_with_cancelled_outcome() -> None:
    account_id = uuid4()
    coach_run = _coach_run(trusted_account_id=account_id)
    job = _background_job(
        job_id=coach_run.research_job_id, requested_by_account_id=account_id, status=BackgroundJobStatus.CANCELLED,
        result_summary=None, cancelled_at=NOW,
    )
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    uow.background_jobs.jobs[job.job_id] = job

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=job.job_id,
    )
    outcome = await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())
    assert outcome.result_summary["outcome"] == "CANCELLED"


async def test_already_resumed_run_is_an_idempotent_no_op() -> None:
    account_id = uuid4()
    research_job_id = uuid4()
    coach_run = _coach_run(
        trusted_account_id=account_id, status=LearningOrchestratorRunStatus.SUCCEEDED, research_job_id=research_job_id,
        completed_at=NOW,
    )
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=research_job_id,
    )
    outcome = await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())

    assert outcome.result_summary["outcome"] == "ALREADY_RESUMED"
    assert service.calls == []  # never resumes the graph a second time


async def test_thread_id_mismatch_fails_closed() -> None:
    coach_run = _coach_run()
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)

    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=uuid4(), research_job_id=coach_run.research_job_id,
    )
    with pytest.raises(CoachResearchResumeStateConflictError):
        await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())


async def test_cross_account_ownership_mismatch_fails_closed() -> None:
    coach_run = _coach_run(trusted_account_id=uuid4())
    job = _background_job(job_id=coach_run.research_job_id, requested_by_account_id=uuid4())  # different account
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    uow.background_jobs.jobs[job.job_id] = job

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=job.job_id,
    )
    with pytest.raises(CoachResearchResumeOwnershipError):
        await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())
    assert service.calls == []


async def test_research_run_request_mismatch_fails_closed() -> None:
    account_id = uuid4()
    coach_run = _coach_run(trusted_account_id=account_id)
    request_id, other_request_id, research_run_id = uuid4(), uuid4(), uuid4()
    # ResearchRun belongs to a DIFFERENT request than the job's own summary claims.
    research_run = ResearchRun(
        run_id=research_run_id, request_id=other_request_id, attempt_number=1, status=ResearchRunStatus.COMPLETED,
        completed_at=NOW,
    )
    job = _background_job(
        job_id=coach_run.research_job_id, requested_by_account_id=account_id,
        result_summary={
            "research_run_status": "COMPLETED", "failure_category": None, "evidence_recorded": 2,
            "research_request_id": str(request_id), "research_run_id": str(research_run_id),
        },
    )
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    uow.background_jobs.jobs[job.job_id] = job
    uow.research_runs.runs[research_run_id] = research_run

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=job.job_id,
    )
    with pytest.raises(CoachResearchResumeInconsistentJobError):
        await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())
    assert service.calls == []


async def test_fabricated_evidence_citation_ownership_rejected_via_request_account_mismatch() -> None:
    """The ResearchRequest itself must belong to the Coach run's trusted
    account too - not just the BackgroundJob - closing the gap where a
    job's own requested_by_account_id happens to match but the
    underlying request was created for someone else."""
    account_id = uuid4()
    coach_run = _coach_run(trusted_account_id=account_id)
    request_id, research_run_id = uuid4(), uuid4()
    research_request = ResearchRequest(
        request_id=request_id, requested_by_account_id=uuid4(), original_question="What happened to Nvidia?",
        normalized_query="what happened to nvidia", scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key="req-key", request_hash=_hash(),
    )
    research_run = ResearchRun(
        run_id=research_run_id, request_id=request_id, attempt_number=1, status=ResearchRunStatus.COMPLETED,
        completed_at=NOW,
    )
    job = _background_job(
        job_id=coach_run.research_job_id, requested_by_account_id=account_id,
        result_summary={
            "research_run_status": "COMPLETED", "failure_category": None, "evidence_recorded": 1,
            "research_request_id": str(request_id), "research_run_id": str(research_run_id),
        },
    )
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    uow.background_jobs.jobs[job.job_id] = job
    uow.research_runs.runs[research_run_id] = research_run
    uow.research_requests.requests[request_id] = research_request

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=job.job_id,
    )
    with pytest.raises(CoachResearchResumeOwnershipError):
        await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())
    assert service.calls == []


async def test_non_terminal_job_fails_closed() -> None:
    coach_run = _coach_run()
    job = _background_job(
        job_id=coach_run.research_job_id, status=BackgroundJobStatus.RUNNING, result_summary=None,
    )
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    uow.background_jobs.jobs[job.job_id] = job

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=job.job_id,
    )
    with pytest.raises(CoachResearchResumeInconsistentJobError):
        await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())


async def test_wrong_job_type_fails_closed() -> None:
    coach_run = _coach_run()
    job = _background_job(
        job_id=coach_run.research_job_id, job_type=BackgroundJobType.KNOWLEDGE_GAP_SUMMARY,
        queue_name="finquest.knowledge", task_name="finquest.knowledge_gap_summary",
    )
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    uow.background_jobs.jobs[job.job_id] = job

    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=job.job_id,
    )
    with pytest.raises(CoachResearchResumeInconsistentJobError):
        await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())


async def test_research_job_id_drift_fails_closed() -> None:
    """The resume job's own research_job_id must match the Coach run's
    stored research_job_id - a mismatch means the two records have
    drifted, and must never be silently reconciled."""
    coach_run = _coach_run()
    run_repo = FakeRunRepo()
    run_repo.runs[coach_run.run_id] = coach_run
    uow = _FakeUoW(runs=run_repo)
    service = _FakeLearningOrchestratorService(resulting_run=coach_run)
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)

    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run.run_id, coach_thread_id=coach_run.thread_id, research_job_id=uuid4(),
    )
    with pytest.raises(CoachResearchResumeStateConflictError):
        await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())


async def test_missing_coach_run_fails_closed() -> None:
    uow = _FakeUoW()
    service = _FakeLearningOrchestratorService(resulting_run=_coach_run())
    handler = CoachResearchResumeJobHandler(unit_of_work_factory=lambda: uow, learning_orchestrator_service=service)
    parameters = CoachResearchResumeParameters(coach_run_id=uuid4(), coach_thread_id=uuid4(), research_job_id=uuid4())
    with pytest.raises(CoachResearchResumeStateConflictError):
        await handler.handle(context=_context(), parameters=parameters, progress=_FakeProgress())
