"""Unit tests for `RuleBasedTutorGuardrail`."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorContextType,
    TutorGuardrailAction,
    TutorMessageRole,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    TutorMessage,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()


def _message(text: str) -> TutorMessage:
    return TutorMessage(conversation_id=uuid4(), role=TutorMessageRole.USER, content=text)


def _general_context() -> TutorContext:
    return TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())


def _candidate(content: str = "Diversification reduces reliance on a single asset.") -> RetrievalCandidate:
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


@pytest.mark.parametrize(
    "question,expected_category,expected_action",
    [
        ("Should I buy NVDA?", TutorRequestCategory.BUY_SELL_REQUEST, TutorGuardrailAction.REFUSE),
        ("Tell me which stock to sell.", TutorRequestCategory.BUY_SELL_REQUEST, TutorGuardrailAction.REFUSE),
        ("Is this a good entry price?", TutorRequestCategory.BUY_SELL_REQUEST, TutorGuardrailAction.REFUSE),
        (
            "How should I invest my $50,000?",
            TutorRequestCategory.PERSONALIZED_INVESTMENT_ADVICE, TutorGuardrailAction.ALLOW_WITH_BOUNDARY,
        ),
        (
            "What percentage should I put in stocks?",
            TutorRequestCategory.PERSONALIZED_INVESTMENT_ADVICE, TutorGuardrailAction.ALLOW_WITH_BOUNDARY,
        ),
        ("How can I guarantee 20%?", TutorRequestCategory.GUARANTEED_RETURN_REQUEST, TutorGuardrailAction.REFUSE),
        ("Which strategy cannot lose?", TutorRequestCategory.GUARANTEED_RETURN_REQUEST, TutorGuardrailAction.REFUSE),
        ("What is diversification?", TutorRequestCategory.ALLOWED_EDUCATION, TutorGuardrailAction.ALLOW),
        ("How is maximum drawdown calculated?", TutorRequestCategory.ALLOWED_EDUCATION, TutorGuardrailAction.ALLOW),
        ("Why does concentration increase risk?", TutorRequestCategory.ALLOWED_EDUCATION, TutorGuardrailAction.ALLOW),
    ],
)
def test_evaluate_input_matches_spec_examples(question, expected_category, expected_action) -> None:
    guardrail = RuleBasedTutorGuardrail()
    decision = guardrail.evaluate_input(conversation_id=uuid4(), message=_message(question), context=_general_context())
    assert decision.request_category == expected_category
    assert decision.action == expected_action


def test_off_topic_question_falls_back() -> None:
    guardrail = RuleBasedTutorGuardrail()
    decision = guardrail.evaluate_input(
        conversation_id=uuid4(), message=_message("Can you recommend a good pizza restaurant near me?"),
        context=_general_context(),
    )
    assert decision.action == TutorGuardrailAction.FALLBACK
    assert decision.request_category == TutorRequestCategory.UNSUPPORTED_TOPIC
    assert decision.safe_response_override == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK


def test_refuse_and_fallback_always_carry_english_override() -> None:
    guardrail = RuleBasedTutorGuardrail()
    for question in ("Should I buy NVDA?", "How can I guarantee 20%?"):
        decision = guardrail.evaluate_input(conversation_id=uuid4(), message=_message(question), context=_general_context())
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.safe_response_override == EXACT_ADVICE_REFUSAL


def test_scenario_before_decision_refuses_future_information_requests() -> None:
    guardrail = RuleBasedTutorGuardrail()
    context = TutorContext(
        context_type=TutorContextType.SCENARIO_BEFORE_DECISION, learner_id=uuid4(), scenario_id=uuid4(),
        knowledge_cutoff_at=NOW,
    )
    for question in ("What happens next?", "Does the stock rise?", "Which option is correct?"):
        decision = guardrail.evaluate_input(conversation_id=uuid4(), message=_message(question), context=context)
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.safe_response_override == EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL


def test_scenario_after_reveal_does_not_trigger_future_information_rule() -> None:
    guardrail = RuleBasedTutorGuardrail()
    context = TutorContext(
        context_type=TutorContextType.SCENARIO_AFTER_REVEAL, learner_id=uuid4(), scenario_id=uuid4()
    )
    decision = guardrail.evaluate_input(
        conversation_id=uuid4(), message=_message("What happens next?"), context=context
    )
    assert decision.action != TutorGuardrailAction.REFUSE or decision.request_category != TutorRequestCategory.UNSUPPORTED_TOPIC


class TestValidateOutput:
    def test_grounded_answer_with_valid_citation(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        candidate = _candidate()
        status, issues = guardrail.validate_output(
            answer_text="Diversification reduces reliance on a single asset [1].",
            cited_chunk_ids=[candidate.chunk.chunk_id], retrieved_candidates=[candidate],
            context=_general_context(),
        )
        assert status == GroundingStatus.GROUNDED
        assert issues == []

    def test_invalid_citation_chunk_id(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        candidate = _candidate()
        status, issues = guardrail.validate_output(
            answer_text="Some claim [1].", cited_chunk_ids=[uuid4()], retrieved_candidates=[candidate],
            context=_general_context(),
        )
        assert status == GroundingStatus.INVALID_CITATIONS
        assert "INVALID_CITATION_CHUNK_ID" in issues

    def test_no_citations_is_insufficient_evidence(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        status, _issues = guardrail.validate_output(
            answer_text="Some uncited claim.", cited_chunk_ids=[], retrieved_candidates=[_candidate()],
            context=_general_context(),
        )
        assert status == GroundingStatus.INSUFFICIENT_EVIDENCE

    def test_guaranteed_return_claim_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        candidate = _candidate()
        _status, issues = guardrail.validate_output(
            answer_text="This guarantees a 20% profit [1].", cited_chunk_ids=[candidate.chunk.chunk_id],
            retrieved_candidates=[candidate], context=_general_context(),
        )
        assert "GUARANTEED_RETURN_CLAIM" in issues

    def test_direct_buy_sell_instruction_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        candidate = _candidate()
        _status, issues = guardrail.validate_output(
            answer_text="Buy 10 shares now [1].", cited_chunk_ids=[candidate.chunk.chunk_id],
            retrieved_candidates=[candidate], context=_general_context(),
        )
        assert "DIRECT_BUY_SELL_INSTRUCTION" in issues

    def test_scenario_future_leak_flagged_before_reveal(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        context = TutorContext(
            context_type=TutorContextType.SCENARIO_BEFORE_DECISION, learner_id=uuid4(), scenario_id=uuid4(),
            knowledge_cutoff_at=NOW,
        )
        _status, issues = guardrail.validate_output(
            answer_text="The stock rose sharply after the decision point.", cited_chunk_ids=[],
            retrieved_candidates=[], context=context,
        )
        assert "SCENARIO_FUTURE_INFORMATION_LEAK" in issues

    def test_portfolio_trade_prescription_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        context = TutorContext(
            context_type=TutorContextType.PORTFOLIO_EXPLANATION, learner_id=uuid4(), portfolio_id=uuid4()
        )
        _status, issues = guardrail.validate_output(
            answer_text="You should sell 20 shares of your largest position.", cited_chunk_ids=[],
            retrieved_candidates=[], context=context,
        )
        assert "PORTFOLIO_TRADE_PRESCRIPTION" in issues

    def test_unverified_url_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        candidate = _candidate()
        _status, issues = guardrail.validate_output(
            answer_text="See https://not-a-real-source.example/page [1].",
            cited_chunk_ids=[candidate.chunk.chunk_id], retrieved_candidates=[candidate],
            context=_general_context(),
        )
        assert "UNVERIFIED_URL" in issues

    def test_hidden_reasoning_marker_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        candidate = _candidate()
        _status, issues = guardrail.validate_output(
            answer_text="<thinking>internal notes</thinking> Diversification helps [1].",
            cited_chunk_ids=[candidate.chunk.chunk_id], retrieved_candidates=[candidate],
            context=_general_context(),
        )
        assert "HIDDEN_REASONING_MARKER" in issues
