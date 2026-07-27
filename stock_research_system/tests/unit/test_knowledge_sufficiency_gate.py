"""Unit tests for the Phase E1 Knowledge Sufficiency Gate.

Pure unit tests against `RuleBasedKnowledgeSufficiencyGate`,
`DisabledKnowledgeSufficiencyGate`, and `is_current_information_request`
- no database, network, or LLM call anywhere in this file.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext
from stock_research_core.application.ai_tutor.sufficiency import (
    DISABLED_POLICY_VERSION,
    REASON_BELOW_RELEVANCE_THRESHOLDS,
    REASON_CURRENT_INFORMATION_REQUEST,
    REASON_GATE_DISABLED,
    REASON_LEXICAL_SCORE_SUFFICIENT,
    REASON_METADATA_SCORE_SUFFICIENT,
    REASON_NO_CANDIDATES,
    REASON_VECTOR_SCORE_SUFFICIENT,
    RULE_BASED_POLICY_VERSION,
    DisabledKnowledgeSufficiencyGate,
    RuleBasedKnowledgeSufficiencyGate,
    is_current_information_request,
)
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorContextType,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()


def _candidate(
    *,
    vector_score: float | None = None,
    lexical_score: float | None = None,
    metadata_score: float = 0.5,
    content: str = "Diversification reduces reliance on a single asset.",
) -> RetrievalCandidate:
    source = KnowledgeSource(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Approved Source",
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
    return RetrievalCandidate(
        chunk=chunk, source=source, document=document,
        vector_score=vector_score, lexical_score=lexical_score, metadata_score=metadata_score,
        combined_score=0.5,
    )


def _context() -> TutorContext:
    return TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())


class TestRuleBasedGateDecisionOrder:
    def test_no_candidates_is_insufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        decision = gate.evaluate(query="What is diversification?", candidates=[], context=_context())

        assert decision.sufficient is False
        assert decision.reason_codes == [REASON_NO_CANDIDATES]
        assert decision.best_vector_score is None
        assert decision.best_lexical_score is None
        assert decision.best_metadata_score is None
        assert decision.policy_version == RULE_BASED_POLICY_VERSION

    def test_vector_score_below_threshold_is_insufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.51, lexical_score=0.0, metadata_score=0.1)

        decision = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())

        assert decision.sufficient is False
        assert decision.reason_codes == [REASON_BELOW_RELEVANCE_THRESHOLDS]
        assert decision.best_vector_score == 0.51

    def test_vector_score_exactly_at_threshold_is_sufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.52, lexical_score=0.0, metadata_score=0.1)

        decision = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())

        assert decision.sufficient is True
        assert decision.reason_codes == [REASON_VECTOR_SCORE_SUFFICIENT]
        assert decision.best_vector_score == 0.52

    def test_vector_score_above_threshold_is_sufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.726081, lexical_score=0.0, metadata_score=0.1)

        decision = gate.evaluate(query="What is compound interest?", candidates=[candidate], context=_context())

        assert decision.sufficient is True
        assert decision.reason_codes == [REASON_VECTOR_SCORE_SUFFICIENT]
        assert decision.best_vector_score == 0.726081

    def test_lexical_score_exactly_at_threshold_is_sufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.1, lexical_score=0.05, metadata_score=0.1)

        decision = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())

        assert decision.sufficient is True
        assert decision.reason_codes == [REASON_LEXICAL_SCORE_SUFFICIENT]
        assert decision.best_lexical_score == 0.05

    def test_lexical_score_below_threshold_is_insufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.1, lexical_score=0.049, metadata_score=0.1)

        decision = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())

        assert decision.sufficient is False
        assert decision.reason_codes == [REASON_BELOW_RELEVANCE_THRESHOLDS]

    def test_high_context_metadata_score_is_sufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.1, lexical_score=0.0, metadata_score=0.95)

        decision = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())

        assert decision.sufficient is True
        assert decision.reason_codes == [REASON_METADATA_SCORE_SUFFICIENT]
        assert decision.best_metadata_score == 0.95

    def test_metadata_score_below_threshold_is_insufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.1, lexical_score=0.0, metadata_score=0.89)

        decision = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())

        assert decision.sufficient is False
        assert decision.reason_codes == [REASON_BELOW_RELEVANCE_THRESHOLDS]

    def test_all_scores_absent_or_low_is_insufficient(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=None, lexical_score=None, metadata_score=0.1)

        decision = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())

        assert decision.sufficient is False
        assert decision.reason_codes == [REASON_BELOW_RELEVANCE_THRESHOLDS]
        assert decision.best_vector_score is None
        assert decision.best_lexical_score is None
        assert decision.best_metadata_score == 0.1

    def test_best_score_is_the_maximum_across_multiple_candidates(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        low = _candidate(vector_score=0.1, lexical_score=0.0, metadata_score=0.1)
        high = _candidate(vector_score=0.8, lexical_score=0.0, metadata_score=0.1)

        decision = gate.evaluate(query="What is diversification?", candidates=[low, high], context=_context())

        assert decision.sufficient is True
        assert decision.best_vector_score == 0.8

    def test_multiple_sufficient_signals_produce_deterministic_reason_code_ordering(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.9, lexical_score=0.9, metadata_score=0.95)

        decision = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())

        assert decision.sufficient is True
        assert decision.reason_codes == [
            REASON_VECTOR_SCORE_SUFFICIENT,
            REASON_LEXICAL_SCORE_SUFFICIENT,
            REASON_METADATA_SCORE_SUFFICIENT,
        ]

        # Re-running against the same inputs must reproduce the identical order -
        # a deterministic rule set, no randomness or set-ordering dependence.
        decision_again = gate.evaluate(query="What is diversification?", candidates=[candidate], context=_context())
        assert decision_again.reason_codes == decision.reason_codes

    def test_reason_codes_are_duplicate_free(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        first = _candidate(vector_score=0.9, lexical_score=0.0, metadata_score=0.1)
        second = _candidate(vector_score=0.8, lexical_score=0.0, metadata_score=0.1)

        decision = gate.evaluate(query="What is diversification?", candidates=[first, second], context=_context())

        assert decision.reason_codes == [REASON_VECTOR_SCORE_SUFFICIENT]
        assert len(set(decision.reason_codes)) == len(decision.reason_codes)


class TestThresholdConfigurationValidation:
    def test_non_finite_vector_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="minimum_vector_score"):
            RuleBasedKnowledgeSufficiencyGate(minimum_vector_score=float("nan"))

    def test_infinite_lexical_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="minimum_lexical_score"):
            RuleBasedKnowledgeSufficiencyGate(minimum_lexical_score=float("inf"))

    def test_infinite_metadata_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="minimum_context_metadata_score"):
            RuleBasedKnowledgeSufficiencyGate(minimum_context_metadata_score=float("-inf"))

    def test_out_of_range_vector_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="minimum_vector_score"):
            RuleBasedKnowledgeSufficiencyGate(minimum_vector_score=1.5)

    def test_negative_lexical_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="minimum_lexical_score"):
            RuleBasedKnowledgeSufficiencyGate(minimum_lexical_score=-0.1)

    def test_out_of_range_metadata_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="minimum_context_metadata_score"):
            RuleBasedKnowledgeSufficiencyGate(minimum_context_metadata_score=1.1)

    def test_calibrated_defaults_are_accepted(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        assert gate._minimum_vector_score == 0.52  # noqa: SLF001 - test-only introspection
        assert gate._minimum_lexical_score == 0.05  # noqa: SLF001
        assert gate._minimum_context_metadata_score == 0.90  # noqa: SLF001


class TestCurrentInformationClassifier:
    @pytest.mark.parametrize(
        "question",
        [
            "What is NVIDIA's current share price today?",
            "What is the Federal Reserve's current target interest rate?",
            "What is the exact 2026 Roth IRA contribution limit?",
            "What are the latest Israeli capital gains tax rules?",
            "What is the exchange rate right now?",
            "What is the interest rate as of today?",
            "What is the stock price currently?",
        ],
    )
    def test_identifies_current_information_requests(self, question: str) -> None:
        assert is_current_information_request(question) is True

    @pytest.mark.parametrize(
        "question",
        [
            "What is the current ratio?",
            "How does the current ratio measure short-term liquidity?",
            "What does current yield mean?",
            "How is current yield different from yield to maturity?",
        ],
    )
    def test_does_not_misclassify_stable_finance_terms(self, question: str) -> None:
        assert is_current_information_request(question) is False

    @pytest.mark.parametrize(
        "question",
        [
            "What is compound interest?",
            "What is diversification?",
            "What is inflation?",
            "Stocks versus bonds - what's the difference?",
            "What is an ETF expense ratio?",
            "Explain a synthetic CDO waterfall.",
        ],
    )
    def test_does_not_misclassify_stable_educational_questions(self, question: str) -> None:
        assert is_current_information_request(question) is False

    def test_gate_short_circuits_on_current_information_before_scoring(self) -> None:
        gate = RuleBasedKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.99, lexical_score=0.99, metadata_score=0.99)

        decision = gate.evaluate(
            query="What is NVIDIA's current share price today?", candidates=[candidate], context=_context()
        )

        assert decision.sufficient is False
        assert decision.reason_codes == [REASON_CURRENT_INFORMATION_REQUEST]
        assert decision.best_vector_score is None
        assert decision.best_lexical_score is None
        assert decision.best_metadata_score is None

    def test_classifier_never_calls_out_to_a_model_or_network(self) -> None:
        # Deterministic-only guarantee: same input, same output, called
        # many times, no external dependency involved.
        results = {is_current_information_request("What is diversification?") for _ in range(50)}
        assert results == {False}


class TestDisabledGate:
    """`DisabledKnowledgeSufficiencyGate` is what
    `GroundedAITutorService` uses whenever
    `TUTOR_KNOWLEDGE_SUFFICIENCY_GATE_ENABLED=false` (the default). It is
    still evaluated exactly once per `ask()` - there is no separate
    empty-candidate branch in the service - so it must itself reproduce
    the pre-Phase-E1 legacy rule: an empty candidate list is
    insufficient, and any non-empty list is unconditionally sufficient,
    regardless of score or query."""

    def test_empty_candidates_is_insufficient_with_no_candidates_reason(self) -> None:
        gate = DisabledKnowledgeSufficiencyGate()

        decision = gate.evaluate(query="anything at all", candidates=[], context=_context())

        assert decision.sufficient is False
        assert decision.reason_codes == [REASON_NO_CANDIDATES]
        assert decision.policy_version == DISABLED_POLICY_VERSION
        assert decision.best_vector_score is None
        assert decision.best_lexical_score is None
        assert decision.best_metadata_score is None

    def test_non_empty_candidates_is_sufficient_regardless_of_query_or_scores(self) -> None:
        gate = DisabledKnowledgeSufficiencyGate()
        candidate = _candidate(vector_score=0.0, lexical_score=0.0, metadata_score=0.0)

        decision = gate.evaluate(
            query="What is NVIDIA's current share price today?", candidates=[candidate], context=_context()
        )

        assert decision.sufficient is True
        assert decision.reason_codes == [REASON_GATE_DISABLED]
        assert decision.policy_version == DISABLED_POLICY_VERSION
        assert decision.best_vector_score is None
        assert decision.best_lexical_score is None
        assert decision.best_metadata_score is None
