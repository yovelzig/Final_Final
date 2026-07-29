"""Deterministic interpretation of a terminal `LIVE_RESEARCH_RUN_EXECUTION`
`BackgroundJob` (spec G2D2 section 15's truth table).

Shared by any caller that must decide what a finished Live Research job
means without re-deriving the same bounded parsing/validation logic -
today `CoachResearchResumeJobHandler` (spec section 16). Never touches
PostgreSQL and never performs an ownership check itself: callers still
load/verify the `ResearchRun`/`ResearchRequest` rows and their requester
identity separately, since "who owns this" differs by caller (an
`IntegrationClient` for the n8n evidence endpoint, an account for the
Coach resume path). This module only decides which lifecycle branch a
job's own `BackgroundJobStatus`/`result_summary` lands in - and fails
closed (`INCONSISTENT`) on any shape that doesn't exactly match one of
the two SUCCEEDED branches, e.g. a bool where an integer evidence count
is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from stock_research_core.domain.live_research.enums import ResearchRunStatus
from stock_research_core.domain.operations.enums import BackgroundJobStatus
from stock_research_core.domain.operations.models import BackgroundJob


class LiveResearchTerminalOutcome(StrEnum):
    #: BackgroundJobStatus.SUCCEEDED, ResearchRun COMPLETED, evidence_recorded > 0.
    EVIDENCE_FOUND = "EVIDENCE_FOUND"
    #: BackgroundJobStatus.SUCCEEDED, ResearchRun FAILED/NO_EVIDENCE_FOUND, evidence_recorded == 0.
    NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"
    #: BackgroundJobStatus.FAILED - a provider or infrastructure failure; no research IDs required.
    PROVIDER_OR_INFRASTRUCTURE_FAILURE = "PROVIDER_OR_INFRASTRUCTURE_FAILURE"
    #: BackgroundJobStatus.CANCELLED or SKIPPED.
    CANCELLED_OR_SKIPPED = "CANCELLED_OR_SKIPPED"
    #: Any other combination - a non-terminal status reached this
    #: function, a malformed result_summary, or a shape that doesn't
    #: exactly match EVIDENCE_FOUND/NO_EVIDENCE_FOUND. Callers must treat
    #: this as a hard failure, never as an ungrounded success.
    INCONSISTENT = "INCONSISTENT"


@dataclass(frozen=True)
class LiveResearchTerminalInterpretation:
    outcome: LiveResearchTerminalOutcome
    research_request_id: UUID | None = None
    research_run_id: UUID | None = None
    evidence_count: int | None = None
    failure_category: str | None = None


def _parsed_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def interpret_live_research_terminal_job(job: BackgroundJob) -> LiveResearchTerminalInterpretation:
    """`job` must already be confirmed `LIVE_RESEARCH_RUN_EXECUTION` and
    terminal (`BackgroundJobStatus` in `TERMINAL_JOB_STATUSES`) by the
    caller - a non-terminal status reaching here returns `INCONSISTENT`
    rather than raising, so every caller fails closed the same way."""
    if job.status in (BackgroundJobStatus.CANCELLED, BackgroundJobStatus.SKIPPED):
        return LiveResearchTerminalInterpretation(outcome=LiveResearchTerminalOutcome.CANCELLED_OR_SKIPPED)

    if job.status == BackgroundJobStatus.FAILED:
        return LiveResearchTerminalInterpretation(outcome=LiveResearchTerminalOutcome.PROVIDER_OR_INFRASTRUCTURE_FAILURE)

    if job.status != BackgroundJobStatus.SUCCEEDED:
        return LiveResearchTerminalInterpretation(outcome=LiveResearchTerminalOutcome.INCONSISTENT)

    result_summary: Any = job.result_summary
    if not isinstance(result_summary, dict):
        return LiveResearchTerminalInterpretation(outcome=LiveResearchTerminalOutcome.INCONSISTENT)

    research_run_status = result_summary.get("research_run_status")
    evidence_recorded = result_summary.get("evidence_recorded")
    has_valid_evidence_count = isinstance(evidence_recorded, int) and not isinstance(evidence_recorded, bool)
    failure_category = result_summary.get("failure_category")
    research_request_id = _parsed_uuid(result_summary.get("research_request_id"))
    research_run_id = _parsed_uuid(result_summary.get("research_run_id"))

    if (
        research_run_status == ResearchRunStatus.COMPLETED.value
        and failure_category is None
        and has_valid_evidence_count
        and evidence_recorded > 0
        and research_request_id is not None
        and research_run_id is not None
    ):
        return LiveResearchTerminalInterpretation(
            outcome=LiveResearchTerminalOutcome.EVIDENCE_FOUND, research_request_id=research_request_id,
            research_run_id=research_run_id, evidence_count=evidence_recorded,
        )

    if (
        research_run_status == "FAILED"
        and failure_category == "NO_EVIDENCE_FOUND"
        and has_valid_evidence_count
        and evidence_recorded == 0
    ):
        return LiveResearchTerminalInterpretation(
            outcome=LiveResearchTerminalOutcome.NO_EVIDENCE_FOUND, evidence_count=0,
            failure_category="NO_EVIDENCE_FOUND",
        )

    return LiveResearchTerminalInterpretation(outcome=LiveResearchTerminalOutcome.INCONSISTENT)
