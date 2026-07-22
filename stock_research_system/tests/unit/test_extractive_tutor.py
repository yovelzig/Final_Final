"""Unit tests for `DeterministicExtractiveTutor`."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorModelRequest
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorProviderType,
)
from stock_research_core.domain.ai_tutor.models import (
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import MODEL_NAME, DeterministicExtractiveTutor

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()


def _candidate(content: str) -> RetrievalCandidate:
    source = KnowledgeSource(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Source",
        approval_status=KnowledgeApprovalStatus.APPROVED,
    )
    document = KnowledgeDocument(
        source_id=source.source_id, title="Doc", content_text=content, content_hash=_HASH,
        status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW, parser_version="v1",
    )
    chunk = KnowledgeChunk(
        document_id=document.document_id, chunk_index=0, content=content, content_hash=_HASH,
        word_count=len(content.split()), estimated_token_count=len(content.split()) + 2,
        available_at=NOW, chunking_version="heading-word-chunker-v1",
    )
    return RetrievalCandidate(chunk=chunk, source=source, document=document, metadata_score=0.5, combined_score=0.5)


class TestDeterministicExtractiveTutor:
    async def test_no_candidates_returns_exact_fallback(self) -> None:
        tutor = DeterministicExtractiveTutor()
        request = TutorModelRequest(
            system_instructions="sys", user_question="What is diversification?", retrieved_candidates=[],
            prompt_version="grounded-tutor-prompt-v1",
        )
        result = await tutor.generate(request)
        assert result.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK
        assert result.cited_chunk_ids == []
        assert result.provider_type == TutorProviderType.EXTRACTIVE
        assert result.model_name == MODEL_NAME

    async def test_selects_most_relevant_sentence_and_cites_it(self) -> None:
        candidate = _candidate(
            "Diversification reduces reliance on a single asset. It does not guarantee against losses."
        )
        tutor = DeterministicExtractiveTutor()
        request = TutorModelRequest(
            system_instructions="sys", user_question="What is diversification?",
            retrieved_candidates=[candidate], prompt_version="grounded-tutor-prompt-v1",
        )
        result = await tutor.generate(request)
        assert "Diversification reduces reliance" in result.answer_markdown
        assert result.cited_chunk_ids == [candidate.chunk.chunk_id]
        assert "[1]" in result.answer_markdown

    async def test_irrelevant_candidates_produce_exact_fallback(self) -> None:
        candidate = _candidate("Bonds pay periodic interest called a coupon.")
        tutor = DeterministicExtractiveTutor()
        request = TutorModelRequest(
            system_instructions="sys", user_question="What is the capital of France?",
            retrieved_candidates=[candidate], prompt_version="grounded-tutor-prompt-v1",
        )
        result = await tutor.generate(request)
        assert result.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK
        assert result.cited_chunk_ids == []

    async def test_deterministic_repeatable_output(self) -> None:
        candidate = _candidate("Volatility measures the variation of returns over time.")
        tutor = DeterministicExtractiveTutor()
        request = TutorModelRequest(
            system_instructions="sys", user_question="What is volatility?", retrieved_candidates=[candidate],
            prompt_version="grounded-tutor-prompt-v1",
        )
        first = await tutor.generate(request)
        second = await tutor.generate(request)
        assert first.answer_markdown == second.answer_markdown
        assert first.cited_chunk_ids == second.cited_chunk_ids

    async def test_limits_to_at_most_three_citations(self) -> None:
        candidates = [
            _candidate(f"Diversification concept number {i} reduces risk across many assets.") for i in range(5)
        ]
        tutor = DeterministicExtractiveTutor()
        request = TutorModelRequest(
            system_instructions="sys", user_question="How does diversification reduce risk?",
            retrieved_candidates=candidates, prompt_version="grounded-tutor-prompt-v1",
        )
        result = await tutor.generate(request)
        assert len(result.cited_chunk_ids) <= 3

    async def test_citations_reference_only_retrieved_chunks(self) -> None:
        candidate = _candidate("Inflation is a general, sustained rise in prices across the economy.")
        tutor = DeterministicExtractiveTutor()
        request = TutorModelRequest(
            system_instructions="sys", user_question="What is inflation?", retrieved_candidates=[candidate],
            prompt_version="grounded-tutor-prompt-v1",
        )
        result = await tutor.generate(request)
        retrieved_ids = {candidate.chunk.chunk_id}
        assert set(result.cited_chunk_ids) <= retrieved_ids
