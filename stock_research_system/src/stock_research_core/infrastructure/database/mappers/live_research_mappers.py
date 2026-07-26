"""Maps ORM rows to Phase G1 Live Research domain models."""

from __future__ import annotations

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.live_research.models import (
    ClaimEvidenceLink,
    EvidenceItem,
    ResearchClaim,
    ResearchRequest,
    ResearchRun,
)
from stock_research_core.infrastructure.database.orm.claim_evidence_link import ClaimEvidenceLinkORM
from stock_research_core.infrastructure.database.orm.evidence_item import EvidenceItemORM
from stock_research_core.infrastructure.database.orm.research_claim import ResearchClaimORM
from stock_research_core.infrastructure.database.orm.research_request import ResearchRequestORM
from stock_research_core.infrastructure.database.orm.research_run import ResearchRunORM


def research_request_orm_to_domain(row: ResearchRequestORM) -> ResearchRequest:
    try:
        return ResearchRequest(
            request_id=row.request_id,
            requested_by_account_id=row.requested_by_account_id,
            requested_by_integration_id=row.requested_by_integration_id,
            original_question=row.original_question,
            normalized_query=row.normalized_query,
            subject_security_id=row.subject_security_id,
            subject_raw_text=row.subject_raw_text,
            scope=row.scope,
            idempotency_key=row.idempotency_key,
            request_hash=row.request_hash,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored research-request row '{row.request_id}' could not be mapped to a domain ResearchRequest."
        ) from exc


def research_run_orm_to_domain(row: ResearchRunORM) -> ResearchRun:
    try:
        return ResearchRun(
            run_id=row.run_id,
            request_id=row.request_id,
            attempt_number=row.attempt_number,
            status=row.status,
            failure_category=row.failure_category,
            failure_message=row.failure_message,
            retryable=row.retryable,
            provider_metadata=row.provider_metadata or {},
            queued_at=row.queued_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            cancelled_at=row.cancelled_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored research-run row '{row.run_id}' could not be mapped to a domain ResearchRun."
        ) from exc


def evidence_item_orm_to_domain(row: EvidenceItemORM) -> EvidenceItem:
    try:
        return EvidenceItem(
            evidence_id=row.evidence_id,
            run_id=row.run_id,
            source_type=row.source_type,
            classification=row.classification,
            source_url=row.source_url,
            official_identifier=row.official_identifier,
            source_title=row.source_title,
            publisher=row.publisher,
            retrieved_at=row.retrieved_at,
            published_at=row.published_at,
            raw_excerpt=row.raw_excerpt,
            normalized_text=row.normalized_text,
            content_hash=row.content_hash,
            structured_facts=row.structured_facts,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored evidence-item row '{row.evidence_id}' could not be mapped to a domain EvidenceItem."
        ) from exc


def research_claim_orm_to_domain(row: ResearchClaimORM) -> ResearchClaim:
    try:
        return ResearchClaim(
            claim_id=row.claim_id,
            run_id=row.run_id,
            claim_text=row.claim_text,
            category=row.category,
            status=row.status,
            confidence_score=float(row.confidence_score) if row.confidence_score is not None else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored research-claim row '{row.claim_id}' could not be mapped to a domain ResearchClaim."
        ) from exc


def claim_evidence_link_orm_to_domain(row: ClaimEvidenceLinkORM) -> ClaimEvidenceLink:
    try:
        return ClaimEvidenceLink(
            link_id=row.link_id,
            claim_id=row.claim_id,
            evidence_id=row.evidence_id,
            stance=row.stance,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored claim-evidence-link row '{row.link_id}' could not be mapped to a domain ClaimEvidenceLink."
        ) from exc
