"""Unit tests for the Live Research ORM-to-domain mapper functions.

These instantiate ORM classes as plain Python objects (no database
connection, no PostgreSQL required) and check the resulting domain
objects, including the `DatabaseMappingError` wrapping path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.live_research.hashing import compute_evidence_content_hash
from stock_research_core.infrastructure.database.mappers.live_research_mappers import (
    claim_evidence_link_orm_to_domain,
    evidence_item_orm_to_domain,
    research_claim_orm_to_domain,
    research_request_orm_to_domain,
    research_run_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.claim_evidence_link import ClaimEvidenceLinkORM
from stock_research_core.infrastructure.database.orm.evidence_item import EvidenceItemORM
from stock_research_core.infrastructure.database.orm.research_claim import ResearchClaimORM
from stock_research_core.infrastructure.database.orm.research_request import ResearchRequestORM
from stock_research_core.infrastructure.database.orm.research_run import ResearchRunORM

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _request_row(**overrides: object) -> ResearchRequestORM:
    defaults: dict = dict(
        request_id=uuid4(),
        requested_by_account_id=uuid4(),
        requested_by_integration_id=None,
        requester_key="account:placeholder",
        original_question="What is AAPL's latest revenue guidance?",
        normalized_query="what is aapl's latest revenue guidance?",
        subject_security_id=uuid4(),
        subject_raw_text=None,
        scope="COMPANY_OVERVIEW",
        idempotency_key="key-1",
        request_hash="a" * 64,
        created_at=NOW,
    )
    defaults.update(overrides)
    return ResearchRequestORM(**defaults)


def _run_row(**overrides: object) -> ResearchRunORM:
    defaults: dict = dict(
        run_id=uuid4(),
        request_id=uuid4(),
        attempt_number=1,
        status="QUEUED",
        failure_category=None,
        failure_message=None,
        retryable=None,
        provider_metadata={},
        queued_at=NOW,
        started_at=None,
        completed_at=None,
        cancelled_at=None,
    )
    defaults.update(overrides)
    return ResearchRunORM(**defaults)


def _evidence_row(**overrides: object) -> EvidenceItemORM:
    content_hash = compute_evidence_content_hash(
        source_type="SEC_OFFICIAL_FILING", classification="OFFICIAL",
        source_url="https://www.sec.gov/example", official_identifier="0001234567-26-000001",
        source_title="Form 10-K", publisher="SEC", published_at=NOW,
        raw_excerpt="Revenue increased.", normalized_text="revenue increased", structured_facts=None,
    )
    defaults: dict = dict(
        evidence_id=uuid4(),
        run_id=uuid4(),
        source_type="SEC_OFFICIAL_FILING",
        classification="OFFICIAL",
        source_url="https://www.sec.gov/example",
        official_identifier="0001234567-26-000001",
        source_title="Form 10-K",
        publisher="SEC",
        retrieved_at=NOW,
        published_at=NOW,
        raw_excerpt="Revenue increased.",
        normalized_text="revenue increased",
        content_hash=content_hash,
        structured_facts=None,
    )
    defaults.update(overrides)
    return EvidenceItemORM(**defaults)


def _claim_row(**overrides: object) -> ResearchClaimORM:
    defaults: dict = dict(
        claim_id=uuid4(),
        run_id=uuid4(),
        claim_text="Revenue grew 10% year over year.",
        category="FINANCIAL_METRIC",
        status="UNVERIFIED",
        confidence_score=None,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return ResearchClaimORM(**defaults)


def _link_row(**overrides: object) -> ClaimEvidenceLinkORM:
    defaults: dict = dict(
        link_id=uuid4(),
        claim_id=uuid4(),
        evidence_id=uuid4(),
        stance="SUPPORTS",
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return ClaimEvidenceLinkORM(**defaults)


# ---------------------------------------------------------------------------
# ResearchRequest
# ---------------------------------------------------------------------------


def test_research_request_orm_to_domain_maps_all_fields() -> None:
    row = _request_row()
    domain = research_request_orm_to_domain(row)
    assert domain.request_id == row.request_id
    assert domain.original_question == row.original_question
    assert domain.normalized_query == row.normalized_query
    assert domain.subject_security_id == row.subject_security_id
    assert domain.scope.value == row.scope
    assert domain.request_hash == row.request_hash


def test_research_request_orm_to_domain_wraps_invalid_row_in_database_mapping_error() -> None:
    row = _request_row(request_hash="not-a-valid-hash")
    with pytest.raises(DatabaseMappingError):
        research_request_orm_to_domain(row)


# ---------------------------------------------------------------------------
# ResearchRun
# ---------------------------------------------------------------------------


def test_research_run_orm_to_domain_maps_all_fields() -> None:
    row = _run_row()
    domain = research_run_orm_to_domain(row)
    assert domain.run_id == row.run_id
    assert domain.request_id == row.request_id
    assert domain.attempt_number == row.attempt_number
    assert domain.status.value == row.status


def test_research_run_orm_to_domain_wraps_invalid_row_in_database_mapping_error() -> None:
    row = _run_row(attempt_number=0)
    with pytest.raises(DatabaseMappingError):
        research_run_orm_to_domain(row)


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------


def test_evidence_item_orm_to_domain_maps_all_fields() -> None:
    row = _evidence_row()
    domain = evidence_item_orm_to_domain(row)
    assert domain.evidence_id == row.evidence_id
    assert domain.run_id == row.run_id
    assert domain.content_hash == row.content_hash
    assert domain.source_type.value == row.source_type


def test_evidence_item_orm_to_domain_wraps_invalid_row_in_database_mapping_error() -> None:
    row = _evidence_row(source_url=None, official_identifier=None)
    with pytest.raises(DatabaseMappingError):
        evidence_item_orm_to_domain(row)


# ---------------------------------------------------------------------------
# ResearchClaim
# ---------------------------------------------------------------------------


def test_research_claim_orm_to_domain_maps_all_fields() -> None:
    row = _claim_row(status="CORROBORATED", confidence_score=Decimal("0.90"))
    domain = research_claim_orm_to_domain(row)
    assert domain.claim_id == row.claim_id
    assert domain.status.value == row.status
    assert domain.confidence_score == pytest.approx(0.90)


def test_research_claim_orm_to_domain_wraps_invalid_row_in_database_mapping_error() -> None:
    row = _claim_row(status="UNVERIFIED", confidence_score=Decimal("0.5"))
    with pytest.raises(DatabaseMappingError):
        research_claim_orm_to_domain(row)


# ---------------------------------------------------------------------------
# ClaimEvidenceLink
# ---------------------------------------------------------------------------


def test_claim_evidence_link_orm_to_domain_maps_all_fields() -> None:
    row = _link_row()
    domain = claim_evidence_link_orm_to_domain(row)
    assert domain.link_id == row.link_id
    assert domain.claim_id == row.claim_id
    assert domain.evidence_id == row.evidence_id
    assert domain.stance.value == row.stance


def test_claim_evidence_link_orm_to_domain_wraps_invalid_row_in_database_mapping_error() -> None:
    row = _link_row(stance="NOT_A_REAL_STANCE")
    with pytest.raises(DatabaseMappingError):
        claim_evidence_link_orm_to_domain(row)
