"""Unit tests for `application.live_research.terminal_outcome` - the
G2D2 section 15 truth table, pure function, no I/O."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from stock_research_core.application.live_research.terminal_outcome import (
    LiveResearchTerminalOutcome,
    interpret_live_research_terminal_job,
)
from stock_research_core.domain.operations.enums import (
    TERMINAL_JOB_STATUSES,
    BackgroundJobStatus,
    BackgroundJobType,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import BackgroundJob

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _job(*, status: BackgroundJobStatus, result_summary=None) -> BackgroundJob:
    return BackgroundJob(
        job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, status=status, trigger_source=JobTriggerSource.SYSTEM,
        requested_by_account_id=uuid4(), idempotency_key="key-1", result_summary=result_summary,
        queue_name="finquest.research", task_name="finquest.live_research_run_execution", started_at=NOW,
        completed_at=NOW if status in TERMINAL_JOB_STATUSES else None,
    )


def test_evidence_found_on_completed_run_with_evidence() -> None:
    request_id, run_id = uuid4(), uuid4()
    job = _job(
        status=BackgroundJobStatus.SUCCEEDED,
        result_summary={
            "research_run_status": "COMPLETED", "failure_category": None, "evidence_recorded": 3,
            "research_request_id": str(request_id), "research_run_id": str(run_id),
        },
    )
    result = interpret_live_research_terminal_job(job)
    assert result.outcome == LiveResearchTerminalOutcome.EVIDENCE_FOUND
    assert result.research_request_id == request_id
    assert result.research_run_id == run_id
    assert result.evidence_count == 3


def test_no_evidence_found_contract() -> None:
    job = _job(
        status=BackgroundJobStatus.SUCCEEDED,
        result_summary={"research_run_status": "FAILED", "failure_category": "NO_EVIDENCE_FOUND", "evidence_recorded": 0},
    )
    result = interpret_live_research_terminal_job(job)
    assert result.outcome == LiveResearchTerminalOutcome.NO_EVIDENCE_FOUND
    assert result.evidence_count == 0


def test_failed_job_is_provider_or_infrastructure_failure_without_requiring_research_ids() -> None:
    job = _job(status=BackgroundJobStatus.FAILED, result_summary={"error_code": "PROVIDER_ERROR"})
    result = interpret_live_research_terminal_job(job)
    assert result.outcome == LiveResearchTerminalOutcome.PROVIDER_OR_INFRASTRUCTURE_FAILURE


def test_cancelled_job() -> None:
    job = _job(status=BackgroundJobStatus.CANCELLED)
    assert interpret_live_research_terminal_job(job).outcome == LiveResearchTerminalOutcome.CANCELLED_OR_SKIPPED


def test_skipped_job() -> None:
    job = _job(status=BackgroundJobStatus.SKIPPED)
    assert interpret_live_research_terminal_job(job).outcome == LiveResearchTerminalOutcome.CANCELLED_OR_SKIPPED


def test_non_terminal_status_fails_closed() -> None:
    job = _job(status=BackgroundJobStatus.RUNNING)
    assert interpret_live_research_terminal_job(job).outcome == LiveResearchTerminalOutcome.INCONSISTENT


def test_missing_result_summary_fails_closed() -> None:
    # A real SUCCEEDED `BackgroundJob` can never have a `None`
    # `result_summary` (`_validate_succeeded_result` forbids it) - this
    # uses `model_construct` to prove the defensive check still holds
    # even if that invariant were ever violated upstream.
    job = _job(status=BackgroundJobStatus.SUCCEEDED, result_summary={"placeholder": True})
    job = job.model_construct(**{**job.model_dump(), "result_summary": None})
    assert interpret_live_research_terminal_job(job).outcome == LiveResearchTerminalOutcome.INCONSISTENT


def test_bool_evidence_count_fails_closed() -> None:
    """A bool is technically `isinstance(x, int)` in Python - this must
    be explicitly rejected, not silently treated as 0/1."""
    job = _job(
        status=BackgroundJobStatus.SUCCEEDED,
        result_summary={
            "research_run_status": "COMPLETED", "failure_category": None, "evidence_recorded": True,
            "research_request_id": str(uuid4()), "research_run_id": str(uuid4()),
        },
    )
    assert interpret_live_research_terminal_job(job).outcome == LiveResearchTerminalOutcome.INCONSISTENT


def test_completed_status_without_evidence_ids_fails_closed() -> None:
    job = _job(
        status=BackgroundJobStatus.SUCCEEDED,
        result_summary={"research_run_status": "COMPLETED", "failure_category": None, "evidence_recorded": 2},
    )
    assert interpret_live_research_terminal_job(job).outcome == LiveResearchTerminalOutcome.INCONSISTENT


def test_completed_status_with_zero_evidence_fails_closed_not_no_evidence_found() -> None:
    """COMPLETED + 0 evidence does not match either accepted contract -
    the accepted NO_EVIDENCE_FOUND contract requires research_run_status
    == FAILED and failure_category == NO_EVIDENCE_FOUND specifically."""
    job = _job(
        status=BackgroundJobStatus.SUCCEEDED,
        result_summary={
            "research_run_status": "COMPLETED", "failure_category": None, "evidence_recorded": 0,
            "research_request_id": str(uuid4()), "research_run_id": str(uuid4()),
        },
    )
    assert interpret_live_research_terminal_job(job).outcome == LiveResearchTerminalOutcome.INCONSISTENT


def test_malformed_result_summary_type_fails_closed() -> None:
    # `model_construct` bypasses Pydantic validation deliberately here -
    # `BackgroundJob.result_summary` is typed `dict[str, Any] | None` and
    # would normally reject this at construction, but the point of this
    # test is to prove `interpret_live_research_terminal_job` itself
    # fails closed defensively rather than trusting the type annotation
    # alone (e.g. if a future caller loads a raw, unvalidated JSONB value).
    job = _job(status=BackgroundJobStatus.SUCCEEDED, result_summary={"placeholder": True})
    job = job.model_construct(**{**job.model_dump(), "result_summary": "not-a-dict"})
    assert interpret_live_research_terminal_job(job).outcome == LiveResearchTerminalOutcome.INCONSISTENT
