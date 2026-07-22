"""Unit tests for the grounded-AI-tutor domain models.

No SQLAlchemy, no database - pure Pydantic validation checks.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorAnswerStatus,
    TutorContextType,
    TutorConversationStatus,
    TutorGuardrailAction,
    TutorMessageRole,
    TutorProviderType,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    TutorAnswer,
    TutorConversation,
    TutorGuardrailDecision,
    TutorKnowledgeGap,
    TutorMessage,
    TutorRetrievalRun,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"content").hexdigest()


def _document(**overrides) -> KnowledgeDocument:
    defaults = dict(
        source_id=uuid4(),
        title="Doc",
        content_text="Some approved content.",
        content_hash=_HASH,
        status=KnowledgeDocumentStatus.PROCESSED,
        approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW,
        parser_version="v1",
    )
    defaults.update(overrides)
    return KnowledgeDocument(**defaults)


class TestKnowledgeSource:
    def test_rejects_invalid_url(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeSource(source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="X", canonical_url="not-a-url")

    def test_trusted_does_not_imply_approved(self) -> None:
        source = KnowledgeSource(source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="X", trusted=True)
        assert source.approval_status == KnowledgeApprovalStatus.DRAFT

    def test_rejects_secret_in_description(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeSource(
                source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="X",
                description="api_key=sk-abcdefghijklmnopqrstuvwx",
            )


class TestKnowledgeDocument:
    def test_content_hash_must_be_lowercase_sha256(self) -> None:
        with pytest.raises(ValidationError):
            _document(content_hash="not-a-hash")

    def test_processed_document_requires_nonempty_content(self) -> None:
        with pytest.raises(ValidationError):
            _document(status=KnowledgeDocumentStatus.PROCESSED, content_text="   ")

    def test_effective_until_cannot_precede_available_at(self) -> None:
        with pytest.raises(ValidationError):
            _document(available_at=NOW, effective_until=NOW - timedelta(days=1))

    def test_duplicate_skill_ids_rejected(self) -> None:
        skill_id = uuid4()
        with pytest.raises(ValidationError):
            _document(skill_ids=[skill_id, skill_id])

    def test_rejects_secret_in_content(self) -> None:
        with pytest.raises(ValidationError):
            _document(content_text="-----BEGIN PRIVATE KEY-----\nsecretstuff\n-----END PRIVATE KEY-----")


class TestKnowledgeChunk:
    def test_duplicate_heading_path_entries_rejected(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeChunk(
                document_id=uuid4(), chunk_index=0, heading_path=["A", "A"], content="text",
                content_hash=_HASH, word_count=1, estimated_token_count=1, available_at=NOW,
                chunking_version="heading-word-chunker-v1",
            )

    def test_negative_chunk_index_rejected(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeChunk(
                document_id=uuid4(), chunk_index=-1, content="text", content_hash=_HASH,
                word_count=1, estimated_token_count=1, available_at=NOW,
                chunking_version="heading-word-chunker-v1",
            )


class TestTutorConversation:
    def test_closed_status_requires_closed_at(self) -> None:
        with pytest.raises(ValidationError):
            TutorConversation(
                learner_id=uuid4(), context_type=TutorContextType.GENERAL_EDUCATION,
                status=TutorConversationStatus.CLOSED,
            )

    def test_lesson_help_requires_lesson_id(self) -> None:
        with pytest.raises(ValidationError):
            TutorConversation(learner_id=uuid4(), context_type=TutorContextType.LESSON_HELP)

    def test_scenario_before_decision_requires_cutoff(self) -> None:
        with pytest.raises(ValidationError):
            TutorConversation(
                learner_id=uuid4(), context_type=TutorContextType.SCENARIO_BEFORE_DECISION,
                scenario_id=uuid4(),
            )

    def test_portfolio_explanation_requires_portfolio_id(self) -> None:
        with pytest.raises(ValidationError):
            TutorConversation(learner_id=uuid4(), context_type=TutorContextType.PORTFOLIO_EXPLANATION)

    def test_valid_general_conversation(self) -> None:
        conversation = TutorConversation(learner_id=uuid4(), context_type=TutorContextType.GENERAL_EDUCATION)
        assert conversation.status == TutorConversationStatus.ACTIVE


class TestTutorMessage:
    def test_rejects_secret_content(self) -> None:
        with pytest.raises(ValidationError):
            TutorMessage(
                conversation_id=uuid4(), role=TutorMessageRole.USER,
                content="my password: hunter22222",
            )

    def test_content_length_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TutorMessage(conversation_id=uuid4(), role=TutorMessageRole.USER, content="x" * 10_001)


class TestTutorAnswer:
    def _base_kwargs(self, **overrides) -> dict:
        defaults = dict(
            conversation_id=uuid4(), request_message_id=uuid4(), provider_type=TutorProviderType.EXTRACTIVE,
            answer_markdown="An answer [1].", request_category=TutorRequestCategory.ALLOWED_EDUCATION,
            grounding_status=GroundingStatus.GROUNDED, retrieval_run_id=uuid4(), guardrail_decision_id=uuid4(),
            tutor_policy_version="v1", prompt_version="v1", model_name="extractive-tutor-v1",
        )
        defaults.update(overrides)
        return defaults

    def test_grounded_requires_retrieval_run_id(self) -> None:
        with pytest.raises(ValidationError):
            TutorAnswer(**self._base_kwargs(retrieval_run_id=None))

    def test_validated_requires_validated_at(self) -> None:
        with pytest.raises(ValidationError):
            TutorAnswer(**self._base_kwargs(status=TutorAnswerStatus.VALIDATED))

    def test_fallback_requires_exact_text(self) -> None:
        with pytest.raises(ValidationError):
            TutorAnswer(
                **self._base_kwargs(
                    status=TutorAnswerStatus.FALLBACK, answer_markdown="wrong text",
                    grounding_status=GroundingStatus.INSUFFICIENT_EVIDENCE, retrieval_run_id=None,
                )
            )
        # exact text is accepted
        TutorAnswer(
            **self._base_kwargs(
                status=TutorAnswerStatus.FALLBACK, answer_markdown=EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
                grounding_status=GroundingStatus.INSUFFICIENT_EVIDENCE, retrieval_run_id=None,
            )
        )


class TestTutorGuardrailDecision:
    def test_refuse_requires_override(self) -> None:
        with pytest.raises(ValidationError):
            TutorGuardrailDecision(
                conversation_id=uuid4(), message_id=uuid4(),
                request_category=TutorRequestCategory.BUY_SELL_REQUEST, action=TutorGuardrailAction.REFUSE,
                policy_version="tutor-guardrail-v1",
            )

    def test_refuse_accepts_override(self) -> None:
        decision = TutorGuardrailDecision(
            conversation_id=uuid4(), message_id=uuid4(),
            request_category=TutorRequestCategory.BUY_SELL_REQUEST, action=TutorGuardrailAction.REFUSE,
            safe_response_override=EXACT_ADVICE_REFUSAL, policy_version="tutor-guardrail-v1",
        )
        assert decision.action == TutorGuardrailAction.REFUSE

    def test_duplicate_rule_codes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TutorGuardrailDecision(
                conversation_id=uuid4(), message_id=uuid4(),
                request_category=TutorRequestCategory.ALLOWED_EDUCATION, action=TutorGuardrailAction.ALLOW,
                matched_rule_codes=["X", "X"], policy_version="v1",
            )


class TestTutorRetrievalRun:
    def test_mismatched_chunk_ids_and_scores_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TutorRetrievalRun(
                conversation_id=uuid4(), query_text="q", top_k=8, retrieval_policy_version="v1",
                embedding_model="m", embedding_version="v1", candidate_count=1,
                returned_chunk_ids=[uuid4()], returned_scores=[],
            )

    def test_non_finite_scores_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TutorRetrievalRun(
                conversation_id=uuid4(), query_text="q", top_k=8, retrieval_policy_version="v1",
                embedding_model="m", embedding_version="v1", candidate_count=1,
                returned_chunk_ids=[uuid4()], returned_scores=[float("nan")],
            )

    def test_top_k_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TutorRetrievalRun(
                conversation_id=uuid4(), query_text="q", top_k=0, retrieval_policy_version="v1",
                embedding_model="m", embedding_version="v1", candidate_count=0,
            )


class TestTutorKnowledgeGap:
    def test_last_seen_cannot_precede_first_seen(self) -> None:
        with pytest.raises(ValidationError):
            TutorKnowledgeGap(
                learner_id=uuid4(), conversation_id=uuid4(), message_id=uuid4(),
                normalized_question="q", context_type=TutorContextType.GENERAL_EDUCATION,
                first_seen_at=NOW, last_seen_at=NOW - timedelta(minutes=1),
            )

    def test_resolved_requires_resolved_at(self) -> None:
        with pytest.raises(ValidationError):
            TutorKnowledgeGap(
                learner_id=uuid4(), conversation_id=uuid4(), message_id=uuid4(),
                normalized_question="q", context_type=TutorContextType.GENERAL_EDUCATION,
                first_seen_at=NOW, last_seen_at=NOW, resolved=True,
            )
