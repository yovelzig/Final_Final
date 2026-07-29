"""Unit tests for `application.operations.models.CoachResearchResumeParameters`
(spec G2D2 section 12) - a bounded, identifier-only job-parameters model,
no I/O.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.application.operations.models import CoachResearchResumeParameters


def test_valid_construction() -> None:
    coach_run_id, coach_thread_id, research_job_id = uuid4(), uuid4(), uuid4()
    parameters = CoachResearchResumeParameters(
        coach_run_id=coach_run_id, coach_thread_id=coach_thread_id, research_job_id=research_job_id,
    )
    assert parameters.coach_run_id == coach_run_id
    assert parameters.coach_thread_id == coach_thread_id
    assert parameters.research_job_id == research_job_id


@pytest.mark.parametrize("missing_field", ["coach_run_id", "coach_thread_id", "research_job_id"])
def test_every_field_is_required(missing_field: str) -> None:
    fields = {"coach_run_id": uuid4(), "coach_thread_id": uuid4(), "research_job_id": uuid4()}
    del fields[missing_field]
    with pytest.raises(ValidationError):
        CoachResearchResumeParameters(**fields)


def test_carries_no_resume_decision_or_evidence_fields() -> None:
    """Section 16: the resume payload must contain outcome metadata only,
    built by the handler itself - never accepted as job parameters,
    which could otherwise let an untrusted caller inject a decision or
    fabricated evidence."""
    field_names = set(CoachResearchResumeParameters.model_fields)
    assert field_names == {"coach_run_id", "coach_thread_id", "research_job_id"}
