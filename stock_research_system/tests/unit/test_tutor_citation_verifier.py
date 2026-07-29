"""Unit tests for `application.ai_tutor.citation_verifier.TutorCitationVerifier` -
extracted from `RuleBasedTutorGuardrail.validate_output` (spec G2D2
section 17), behavior-identical to the inline checks it replaced (see
`test_tutor_guardrails.py::TestValidateOutput` for the guardrail-level
regression coverage of this exact behavior)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from stock_research_core.application.ai_tutor.citation_verifier import TutorCitationVerifier
from stock_research_core.application.ai_tutor.models import KnowledgeSource, RetrievalCandidate
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _candidate(*, chunk_id=None, canonical_url: str | None = None) -> RetrievalCandidate:
    from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument

    source = KnowledgeSource(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Approved Source",
        approval_status=KnowledgeApprovalStatus.APPROVED, canonical_url=canonical_url,
    )
    document = KnowledgeDocument(
        source_id=source.source_id, title="Doc", content_text="content", content_hash="a" * 64,
        status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW, parser_version="v1",
    )
    chunk = KnowledgeChunk(
        chunk_id=chunk_id or uuid4(), document_id=document.document_id, chunk_index=0, content="content",
        content_hash="a" * 64, word_count=1, estimated_token_count=1, available_at=NOW, chunking_version="v1",
    )
    return RetrievalCandidate(chunk=chunk, source=source, document=document, metadata_score=0.5, combined_score=0.5)


def test_check_citations_passes_when_all_ids_are_retrieved() -> None:
    candidate = _candidate()
    verifier = TutorCitationVerifier()
    issues = verifier.check_citations(cited_chunk_ids=[candidate.chunk.chunk_id], retrieved_candidates=[candidate])
    assert issues == []


def test_check_citations_flags_an_id_that_was_never_retrieved() -> None:
    candidate = _candidate()
    verifier = TutorCitationVerifier()
    issues = verifier.check_citations(cited_chunk_ids=[uuid4()], retrieved_candidates=[candidate])
    assert issues == ["INVALID_CITATION_CHUNK_ID"]


def test_check_citations_passes_with_no_citations() -> None:
    verifier = TutorCitationVerifier()
    assert verifier.check_citations(cited_chunk_ids=[], retrieved_candidates=[]) == []


def test_check_urls_passes_when_url_matches_an_allowed_source() -> None:
    candidate = _candidate(canonical_url="https://example.com/approved")
    verifier = TutorCitationVerifier()
    issues = verifier.check_urls(
        answer_text="See https://example.com/approved for details.", retrieved_candidates=[candidate]
    )
    assert issues == []


def test_check_urls_flags_a_url_not_in_any_retrieved_source() -> None:
    candidate = _candidate(canonical_url="https://example.com/approved")
    verifier = TutorCitationVerifier()
    issues = verifier.check_urls(
        answer_text="See https://evil.example/not-approved for details.", retrieved_candidates=[candidate]
    )
    assert issues == ["UNVERIFIED_URL"]


def test_check_urls_passes_with_no_urls_in_the_answer() -> None:
    verifier = TutorCitationVerifier()
    assert verifier.check_urls(answer_text="No links here.", retrieved_candidates=[]) == []
