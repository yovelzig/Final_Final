"""Unit tests for `application.live_research.citation_verifier.
ResearchEvidenceCitationVerifier` (spec G2D2 section 17)."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from stock_research_core.application.live_research.citation_verifier import ResearchEvidenceCitationVerifier
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.domain.live_research.models import EvidenceItem


def _evidence(run_id, *, classification=EvidenceClassification.NON_OFFICIAL) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id, source_type=SourceType.REPUTABLE_SECONDARY_SOURCE, classification=classification,
        source_url="https://example.com/a", source_title="Title", publisher="Publisher",
        raw_excerpt="Some excerpt.", content_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
    )


def test_all_citations_belonging_to_the_run_are_verified() -> None:
    run_id = uuid4()
    item = _evidence(run_id)
    verifier = ResearchEvidenceCitationVerifier()
    result = verifier.verify(cited_evidence_ids=[item.evidence_id], verified_run_evidence=[item], research_run_id=run_id)
    assert result.verified_evidence_ids == [item.evidence_id]
    assert result.rejected_evidence_ids == []
    assert result.all_verified is True


def test_fabricated_citation_is_rejected() -> None:
    run_id = uuid4()
    item = _evidence(run_id)
    verifier = ResearchEvidenceCitationVerifier()
    fabricated_id = uuid4()
    result = verifier.verify(
        cited_evidence_ids=[item.evidence_id, fabricated_id], verified_run_evidence=[item], research_run_id=run_id,
    )
    assert result.verified_evidence_ids == [item.evidence_id]
    assert result.rejected_evidence_ids == [fabricated_id]
    assert result.all_verified is False


def test_citation_belonging_to_a_different_run_is_rejected() -> None:
    """An EvidenceItem from a different run must never be accepted, even
    if it happens to be present in the (incorrectly-scoped) evidence
    list passed in - the run_id membership check is authoritative."""
    correct_run_id, other_run_id = uuid4(), uuid4()
    cross_run_item = _evidence(other_run_id)
    verifier = ResearchEvidenceCitationVerifier()
    result = verifier.verify(
        cited_evidence_ids=[cross_run_item.evidence_id], verified_run_evidence=[cross_run_item],
        research_run_id=correct_run_id,
    )
    assert result.verified_evidence_ids == []
    assert result.rejected_evidence_ids == [cross_run_item.evidence_id]
    assert result.all_verified is False


def test_empty_citations_are_trivially_all_verified() -> None:
    verifier = ResearchEvidenceCitationVerifier()
    result = verifier.verify(cited_evidence_ids=[], verified_run_evidence=[], research_run_id=uuid4())
    assert result.all_verified is True


def test_split_by_official_classification_keeps_categories_distinguishable() -> None:
    run_id = uuid4()
    official = _evidence(run_id, classification=EvidenceClassification.OFFICIAL)
    non_official = _evidence(run_id, classification=EvidenceClassification.NON_OFFICIAL)
    verifier = ResearchEvidenceCitationVerifier()
    official_list, non_official_list = verifier.split_by_official_classification([official, non_official])
    assert official_list == [official]
    assert non_official_list == [non_official]
