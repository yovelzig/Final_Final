"""Unit tests for `GroundedTutorPromptBuilder`."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext
from stock_research_core.application.ai_tutor.prompt_builder import PROMPT_VERSION, GroundedTutorPromptBuilder
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorContextType,
    TutorMessageRole,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource, TutorMessage

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()


def _candidate(content: str = "Diversification reduces reliance on a single asset.") -> RetrievalCandidate:
    source = KnowledgeSource(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Approved Source",
        approval_status=KnowledgeApprovalStatus.APPROVED,
    )
    document = KnowledgeDocument(
        source_id=source.source_id, title="Doc Title", content_text=content, content_hash=_HASH,
        status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW, parser_version="v1",
    )
    chunk = KnowledgeChunk(
        document_id=document.document_id, chunk_index=0, heading_path=["Section"], content=content,
        content_hash=_HASH, word_count=len(content.split()), estimated_token_count=len(content.split()) + 2,
        available_at=NOW, chunking_version="heading-word-chunker-v1",
    )
    return RetrievalCandidate(chunk=chunk, source=source, document=document, metadata_score=0.5, combined_score=0.5)


class TestGroundedTutorPromptBuilder:
    def test_prompt_version_constant(self) -> None:
        assert GroundedTutorPromptBuilder().prompt_version == PROMPT_VERSION == "grounded-tutor-prompt-v1"

    def test_includes_evidence_and_question(self) -> None:
        builder = GroundedTutorPromptBuilder()
        candidate = _candidate()
        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())
        request = builder.build(question="What is diversification?", conversation_messages=[], candidates=[candidate], context=context)
        assert request.user_question == "What is diversification?"
        assert "Diversification reduces reliance" in request.system_instructions
        assert str(candidate.chunk.chunk_id) in request.system_instructions

    def test_forbids_outside_knowledge_and_personalized_advice(self) -> None:
        builder = GroundedTutorPromptBuilder()
        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())
        request = builder.build(question="q", conversation_messages=[], candidates=[], context=context)
        lowered = request.system_instructions.lower()
        assert "do not use any outside knowledge" in lowered
        assert "personalized" in lowered

    def test_scenario_before_decision_adds_reveal_guidance(self) -> None:
        builder = GroundedTutorPromptBuilder()
        context = TutorContext(
            context_type=TutorContextType.SCENARIO_BEFORE_DECISION, learner_id=uuid4(), scenario_id=uuid4(),
            knowledge_cutoff_at=NOW,
        )
        request = builder.build(question="q", conversation_messages=[], candidates=[], context=context)
        assert "do not reveal" in request.system_instructions.lower()

    def test_portfolio_explanation_forbids_prescribing_trades(self) -> None:
        builder = GroundedTutorPromptBuilder()
        context = TutorContext(
            context_type=TutorContextType.PORTFOLIO_EXPLANATION, learner_id=uuid4(), portfolio_id=uuid4()
        )
        request = builder.build(question="q", conversation_messages=[], candidates=[], context=context)
        assert "never prescribe a trade" in request.system_instructions.lower()

    def test_conversation_history_included_but_labeled_as_context_only(self) -> None:
        builder = GroundedTutorPromptBuilder()
        message = TutorMessage(conversation_id=uuid4(), role=TutorMessageRole.USER, content="earlier question")
        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())
        request = builder.build(question="q", conversation_messages=[message], candidates=[], context=context)
        assert "earlier question" in request.system_instructions
        assert "not a factual source" in request.system_instructions.lower()
        assert request.conversation_messages == [message]

    def test_requires_structured_json_response(self) -> None:
        builder = GroundedTutorPromptBuilder()
        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())
        request = builder.build(question="q", conversation_messages=[], candidates=[], context=context)
        assert "answer_markdown" in request.system_instructions
        assert "cited_chunk_ids" in request.system_instructions
