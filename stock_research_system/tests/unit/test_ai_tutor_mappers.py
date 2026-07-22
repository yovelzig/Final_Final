"""Unit tests for grounded-AI-tutor ORM-to-domain mapper functions.

ORM classes are instantiated as plain Python objects (no database
connection, no PostgreSQL required).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.infrastructure.database.mappers.ai_tutor_mappers import (
    knowledge_chunk_embedding_orm_to_domain,
    knowledge_chunk_orm_to_domain,
    knowledge_document_orm_to_domain,
    knowledge_source_orm_to_domain,
    tutor_answer_orm_to_domain,
    tutor_citation_orm_to_domain,
    tutor_conversation_orm_to_domain,
    tutor_guardrail_decision_orm_to_domain,
    tutor_knowledge_gap_orm_to_domain,
    tutor_message_orm_to_domain,
    tutor_retrieval_run_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.knowledge_chunk import KnowledgeChunkORM
from stock_research_core.infrastructure.database.orm.knowledge_chunk_embedding import (
    KnowledgeChunkEmbeddingORM,
)
from stock_research_core.infrastructure.database.orm.knowledge_document import KnowledgeDocumentORM
from stock_research_core.infrastructure.database.orm.knowledge_source import KnowledgeSourceORM
from stock_research_core.infrastructure.database.orm.tutor_answer import TutorAnswerORM
from stock_research_core.infrastructure.database.orm.tutor_answer_citation import TutorAnswerCitationORM
from stock_research_core.infrastructure.database.orm.tutor_conversation import TutorConversationORM
from stock_research_core.infrastructure.database.orm.tutor_guardrail_decision import (
    TutorGuardrailDecisionORM,
)
from stock_research_core.infrastructure.database.orm.tutor_knowledge_gap import TutorKnowledgeGapORM
from stock_research_core.infrastructure.database.orm.tutor_message import TutorMessageORM
from stock_research_core.infrastructure.database.orm.tutor_retrieval_run import TutorRetrievalRunORM

UTC_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()


def test_knowledge_source_orm_to_domain() -> None:
    row = KnowledgeSourceORM(
        source_id=uuid4(), source_type="LOCAL_MARKDOWN", title="Source", description=None,
        approval_status="APPROVED", canonical_url=None, publisher=None, license_note=None,
        default_language="en", trusted=True, created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    domain = knowledge_source_orm_to_domain(row)
    assert domain.source_id == row.source_id
    assert domain.trusted is True


def test_knowledge_source_orm_to_domain_raises_mapping_error_on_bad_enum() -> None:
    row = KnowledgeSourceORM(
        source_id=uuid4(), source_type="NOT_A_REAL_TYPE", title="Source", description=None,
        approval_status="APPROVED", canonical_url=None, publisher=None, license_note=None,
        default_language="en", trusted=True, created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    with pytest.raises(DatabaseMappingError):
        knowledge_source_orm_to_domain(row)


def test_knowledge_document_orm_to_domain_with_skill_ids() -> None:
    skill_ids = [uuid4(), uuid4()]
    row = KnowledgeDocumentORM(
        document_id=uuid4(), source_id=uuid4(), title="Doc", content_text="content", content_hash=_HASH,
        language="en", status="PROCESSED", approval_status="APPROVED", published_at=None,
        available_at=UTC_NOW, effective_until=None, lesson_id=None, exercise_id=None, scenario_id=None,
        portfolio_context_code=None, document_version="v1", parser_version="v1",
        created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    domain = knowledge_document_orm_to_domain(row, skill_ids)
    assert domain.skill_ids == skill_ids


def test_knowledge_chunk_orm_to_domain() -> None:
    row = KnowledgeChunkORM(
        chunk_id=uuid4(), document_id=uuid4(), chunk_index=0, heading_path=["A", "B"], content="text",
        content_hash=_HASH, word_count=1, estimated_token_count=1, available_at=UTC_NOW,
        effective_until=None, chunking_version="heading-word-chunker-v1", created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    domain = knowledge_chunk_orm_to_domain(row)
    assert domain.heading_path == ["A", "B"]


def test_knowledge_chunk_embedding_orm_to_domain_never_exposes_vector() -> None:
    row = KnowledgeChunkEmbeddingORM(
        embedding_id=uuid4(), chunk_id=uuid4(), embedding_model="m", embedding_version="v1",
        embedding_dimension=3, embedding=[0.1, 0.2, 0.3], created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    domain = knowledge_chunk_embedding_orm_to_domain(row)
    assert not hasattr(domain, "embedding")
    assert domain.embedding_dimension == 3


def test_tutor_conversation_orm_to_domain() -> None:
    row = TutorConversationORM(
        conversation_id=uuid4(), learner_id=uuid4(), status="ACTIVE", context_type="GENERAL_EDUCATION",
        lesson_id=None, exercise_id=None, scenario_id=None, portfolio_id=None, knowledge_cutoff_at=None,
        created_at=UTC_NOW, updated_at=UTC_NOW, closed_at=None,
    )
    domain = tutor_conversation_orm_to_domain(row)
    assert domain.conversation_id == row.conversation_id


def test_tutor_message_orm_to_domain() -> None:
    row = TutorMessageORM(
        message_id=uuid4(), conversation_id=uuid4(), role="USER", content="hello", created_at=UTC_NOW
    )
    domain = tutor_message_orm_to_domain(row)
    assert domain.content == "hello"


def test_tutor_citation_orm_to_domain() -> None:
    row = TutorAnswerCitationORM(
        citation_id=uuid4(), answer_id=uuid4(), chunk_id=uuid4(), citation_number=1,
        quoted_excerpt="excerpt", source_title="Source", document_title="Doc", heading_path=["A"],
        created_at=UTC_NOW,
    )
    domain = tutor_citation_orm_to_domain(row)
    assert domain.citation_number == 1


def test_tutor_answer_orm_to_domain() -> None:
    row = TutorAnswerORM(
        answer_id=uuid4(), conversation_id=uuid4(), request_message_id=uuid4(), status="VALIDATED",
        provider_type="EXTRACTIVE", answer_markdown="answer", request_category="ALLOWED_EDUCATION",
        grounding_status="GROUNDED", retrieval_run_id=uuid4(), guardrail_decision_id=uuid4(),
        tutor_policy_version="v1", prompt_version="v1", model_name="extractive-tutor-v1",
        model_response_id=None, created_at=UTC_NOW, validated_at=UTC_NOW,
    )
    domain = tutor_answer_orm_to_domain(row)
    assert domain.status.value == "VALIDATED"


def test_tutor_guardrail_decision_orm_to_domain() -> None:
    row = TutorGuardrailDecisionORM(
        decision_id=uuid4(), conversation_id=uuid4(), message_id=uuid4(), request_category="BUY_SELL_REQUEST",
        action="REFUSE", matched_rule_codes=["BUY_SELL_INSTRUCTION"], safe_response_override="refusal text",
        policy_version="v1", created_at=UTC_NOW,
    )
    domain = tutor_guardrail_decision_orm_to_domain(row)
    assert domain.matched_rule_codes == ["BUY_SELL_INSTRUCTION"]


def test_tutor_retrieval_run_orm_to_domain_with_chunks() -> None:
    row = TutorRetrievalRunORM(
        retrieval_run_id=uuid4(), conversation_id=uuid4(), query_text="q", method="HYBRID", top_k=8,
        knowledge_cutoff_at=None, retrieval_policy_version="v1", embedding_model="m", embedding_version="v1",
        candidate_count=2, created_at=UTC_NOW,
    )
    chunk_ids = [uuid4(), uuid4()]
    scores = [0.9, 0.5]
    domain = tutor_retrieval_run_orm_to_domain(row, chunk_ids, scores)
    assert domain.returned_chunk_ids == chunk_ids
    assert domain.returned_scores == scores


def test_tutor_knowledge_gap_orm_to_domain_with_skills() -> None:
    row = TutorKnowledgeGapORM(
        gap_id=uuid4(), learner_id=uuid4(), conversation_id=uuid4(), message_id=uuid4(),
        normalized_question="what is x", context_type="GENERAL_EDUCATION", occurrence_count=2,
        first_seen_at=UTC_NOW, last_seen_at=UTC_NOW, resolved=False, resolved_at=None,
        resolution_document_id=None, created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    skill_ids = [uuid4()]
    domain = tutor_knowledge_gap_orm_to_domain(row, skill_ids)
    assert domain.target_skill_ids == skill_ids
    assert domain.occurrence_count == 2
