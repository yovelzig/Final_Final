"""Unit tests for the Live Research domain models and their validation rules.

Pure Pydantic model tests: no SQLAlchemy, no fakes, no I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.live_research.enums import (
    ClaimCategory,
    ClaimStatus,
    EvidenceClassification,
    EvidenceStance,
    FailureCategory,
    ResearchRunStatus,
    ResearchScope,
    SourceType,
)
from stock_research_core.domain.live_research.hashing import compute_evidence_content_hash
from stock_research_core.domain.live_research.models import (
    ClaimEvidenceLink,
    EvidenceItem,
    ResearchClaim,
    ResearchRequest,
    ResearchRun,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# ResearchRequest
# ---------------------------------------------------------------------------


def _request(**overrides: object) -> ResearchRequest:
    defaults: dict = dict(
        requested_by_account_id=uuid4(),
        original_question="What is AAPL's latest revenue guidance?",
        normalized_query="what is aapl's latest revenue guidance?",
        subject_security_id=uuid4(),
        scope=ResearchScope.COMPANY_OVERVIEW,
        idempotency_key="key-1",
        request_hash="a" * 64,
    )
    defaults.update(overrides)
    return ResearchRequest(**defaults)


def test_request_requires_exactly_one_requester_identity() -> None:
    with pytest.raises(ValidationError):
        _request(requested_by_account_id=None, requested_by_integration_id=None)
    with pytest.raises(ValidationError):
        _request(requested_by_account_id=uuid4(), requested_by_integration_id=uuid4())


def test_request_requires_exactly_one_subject_unless_general_question() -> None:
    with pytest.raises(ValidationError):
        _request(subject_security_id=uuid4(), subject_raw_text="Apple Inc.")
    with pytest.raises(ValidationError):
        _request(subject_security_id=None, scope=ResearchScope.COMPANY_OVERVIEW)


def test_request_general_question_allows_no_subject() -> None:
    request = _request(subject_security_id=None, scope=ResearchScope.GENERAL_QUESTION)
    assert request.subject_security_id is None
    assert request.subject_raw_text is None


def test_request_rejects_malformed_request_hash() -> None:
    with pytest.raises(ValidationError):
        _request(request_hash="not-a-valid-hash")


def test_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(
            requested_by_account_id=uuid4(),
            original_question="Question?",
            normalized_query="question?",
            subject_security_id=uuid4(),
            scope=ResearchScope.COMPANY_OVERVIEW,
            idempotency_key="key-1",
            request_hash="a" * 64,
            not_a_real_field="oops",
        )


# ---------------------------------------------------------------------------
# ResearchRun
# ---------------------------------------------------------------------------


def _run(**overrides: object) -> ResearchRun:
    defaults: dict = dict(request_id=uuid4(), attempt_number=1)
    defaults.update(overrides)
    return ResearchRun(**defaults)


def test_run_attempt_number_lower_bound() -> None:
    with pytest.raises(ValidationError):
        _run(attempt_number=0)
    with pytest.raises(ValidationError):
        _run(attempt_number=-1)
    assert _run(attempt_number=1).attempt_number == 1


def test_run_running_requires_started_at() -> None:
    with pytest.raises(ValidationError):
        _run(status=ResearchRunStatus.RUNNING)
    running = _run(status=ResearchRunStatus.RUNNING, started_at=NOW)
    assert running.started_at == NOW


def test_run_completed_requires_completed_at() -> None:
    with pytest.raises(ValidationError):
        _run(status=ResearchRunStatus.COMPLETED, started_at=NOW)
    completed = _run(status=ResearchRunStatus.COMPLETED, started_at=NOW, completed_at=NOW)
    assert completed.completed_at == NOW


def test_run_cancelled_accepts_completed_at_or_cancelled_at() -> None:
    with pytest.raises(ValidationError):
        _run(status=ResearchRunStatus.CANCELLED)
    assert _run(status=ResearchRunStatus.CANCELLED, cancelled_at=NOW).cancelled_at == NOW
    assert _run(status=ResearchRunStatus.CANCELLED, completed_at=NOW).completed_at == NOW


def test_run_failed_requires_failure_category_message_and_retryable() -> None:
    with pytest.raises(ValidationError):
        _run(status=ResearchRunStatus.FAILED, started_at=NOW, completed_at=NOW)
    failed = _run(
        status=ResearchRunStatus.FAILED,
        started_at=NOW,
        completed_at=NOW,
        failure_category=FailureCategory.PROVIDER_ERROR,
        failure_message="The provider returned an error.",
        retryable=True,
    )
    assert failed.retryable is True


def test_run_rejects_sensitive_provider_metadata() -> None:
    with pytest.raises(ValidationError):
        _run(provider_metadata={"api_key": "sk-something"})


def test_run_rejects_traceback_in_failure_message() -> None:
    with pytest.raises(ValidationError):
        _run(
            status=ResearchRunStatus.FAILED,
            started_at=NOW,
            completed_at=NOW,
            failure_category=FailureCategory.INTERNAL_ERROR,
            failure_message="Traceback (most recent call last):\n  ...",
            retryable=False,
        )


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------


def _evidence_hash(**overrides: object) -> str:
    kwargs: dict = dict(
        source_type="SEC_OFFICIAL_FILING", classification="OFFICIAL",
        source_url="https://www.sec.gov/example", official_identifier="0001234567-26-000001",
        source_title="Form 10-K", publisher="SEC", published_at=NOW,
        raw_excerpt="Revenue increased.", normalized_text="revenue increased",
        structured_facts=None,
    )
    kwargs.update(overrides)
    return compute_evidence_content_hash(**kwargs)


def _evidence(**overrides: object) -> EvidenceItem:
    defaults: dict = dict(
        run_id=uuid4(),
        source_type=SourceType.SEC_OFFICIAL_FILING,
        classification=EvidenceClassification.OFFICIAL,
        source_url="https://www.sec.gov/example",
        official_identifier="0001234567-26-000001",
        source_title="Form 10-K",
        publisher="SEC",
        published_at=NOW,
        raw_excerpt="Revenue increased.",
        normalized_text="revenue increased",
        structured_facts=None,
        content_hash=_evidence_hash(),
    )
    defaults.update(overrides)
    return EvidenceItem(**defaults)


def test_evidence_source_identity_both_present_is_valid() -> None:
    evidence = _evidence()
    assert evidence.source_url is not None
    assert evidence.official_identifier is not None


def test_evidence_source_identity_url_only_is_valid() -> None:
    evidence = _evidence(
        official_identifier=None,
        content_hash=_evidence_hash(official_identifier=None),
    )
    assert evidence.source_url is not None


def test_evidence_source_identity_identifier_only_is_valid() -> None:
    evidence = _evidence(
        source_url=None,
        content_hash=_evidence_hash(source_url=None),
    )
    assert evidence.official_identifier is not None


def test_evidence_source_identity_neither_is_invalid() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            source_url=None,
            official_identifier=None,
            content_hash=_evidence_hash(source_url=None, official_identifier=None),
        )


def test_evidence_payload_both_present_is_valid() -> None:
    evidence = _evidence(structured_facts={"revenue": 100})
    assert evidence.raw_excerpt is not None
    assert evidence.structured_facts is not None


def test_evidence_payload_excerpt_only_is_valid() -> None:
    evidence = _evidence(structured_facts=None)
    assert evidence.raw_excerpt is not None


def test_evidence_payload_structured_facts_only_is_valid() -> None:
    evidence = _evidence(
        raw_excerpt=None,
        normalized_text=None,
        structured_facts={"revenue": 100},
        content_hash=_evidence_hash(raw_excerpt=None, normalized_text=None, structured_facts={"revenue": 100}),
    )
    assert evidence.structured_facts == {"revenue": 100}


def test_evidence_payload_neither_meaningful_is_invalid() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            raw_excerpt=None,
            normalized_text=None,
            structured_facts=None,
            content_hash=_evidence_hash(raw_excerpt=None, normalized_text=None, structured_facts=None),
        )


def test_evidence_payload_blank_excerpt_counts_as_missing() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            raw_excerpt="   ",
            normalized_text=None,
            structured_facts=None,
            content_hash=_evidence_hash(raw_excerpt="   ", normalized_text=None, structured_facts=None),
        )


def test_evidence_payload_empty_structured_facts_counts_as_missing() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            raw_excerpt=None,
            normalized_text=None,
            structured_facts={},
            content_hash=_evidence_hash(raw_excerpt=None, normalized_text=None, structured_facts={}),
        )


def test_evidence_is_immutable() -> None:
    evidence = _evidence()
    with pytest.raises(ValidationError):
        evidence.source_title = "A different title"


def test_evidence_rejects_malformed_content_hash() -> None:
    with pytest.raises(ValidationError):
        _evidence(content_hash="short")


def test_evidence_rejects_sensitive_structured_facts() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            structured_facts={"api_key": "sk-something"},
            content_hash=_evidence_hash(structured_facts={"api_key": "sk-something"}),
        )


# ---------------------------------------------------------------------------
# ResearchClaim
# ---------------------------------------------------------------------------


def _claim(**overrides: object) -> ResearchClaim:
    defaults: dict = dict(
        run_id=uuid4(),
        claim_text="Revenue grew 10% year over year.",
        category=ClaimCategory.FINANCIAL_METRIC,
    )
    defaults.update(overrides)
    return ResearchClaim(**defaults)


def test_claim_has_no_evidence_id_list_fields() -> None:
    claim = _claim()
    assert not hasattr(claim, "supporting_evidence_ids")
    assert not hasattr(claim, "contradicting_evidence_ids")


def test_claim_unverified_must_not_carry_confidence_score() -> None:
    with pytest.raises(ValidationError):
        _claim(status=ClaimStatus.UNVERIFIED, confidence_score=0.5)


def test_claim_corroborated_may_carry_confidence_score() -> None:
    claim = _claim(status=ClaimStatus.CORROBORATED, confidence_score=0.9)
    assert claim.confidence_score == 0.9


# ---------------------------------------------------------------------------
# ClaimEvidenceLink
# ---------------------------------------------------------------------------


def test_claim_evidence_link_round_trips_fields() -> None:
    claim_id = uuid4()
    evidence_id = uuid4()
    link = ClaimEvidenceLink(claim_id=claim_id, evidence_id=evidence_id, stance=EvidenceStance.SUPPORTS)
    assert link.claim_id == claim_id
    assert link.evidence_id == evidence_id
    assert link.stance == EvidenceStance.SUPPORTS
