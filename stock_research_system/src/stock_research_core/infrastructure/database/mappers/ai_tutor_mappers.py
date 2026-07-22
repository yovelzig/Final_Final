"""Maps between grounded-AI-tutor ORM rows and domain models.

`KnowledgeDocument.skill_ids`, `TutorGuardrailDecision.matched_rule_codes`
(array column), `TutorKnowledgeGap.target_skill_ids`, and
`TutorRetrievalRun.returned_chunk_ids`/`.returned_scores` (association
table) all either live in a separate association table or need
assembling from a related row set - repositories query those
separately and pass the resulting values into these mapper functions,
the same pattern used throughout `virtual_portfolio_mappers.py` and
`market_scenario_mappers.py`. `KnowledgeChunkEmbeddingORM.embedding`
(the raw vector) is never read by its mapper - only lineage fields
cross into the domain model.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    RetrievalMethod,
    TutorAnswerStatus,
    TutorContextType,
    TutorConversationStatus,
    TutorGuardrailAction,
    TutorMessageRole,
    TutorProviderType,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import (
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeDocument,
    KnowledgeSource,
    TutorAnswer,
    TutorCitation,
    TutorConversation,
    TutorGuardrailDecision,
    TutorKnowledgeGap,
    TutorMessage,
    TutorRetrievalRun,
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


def knowledge_source_orm_to_domain(row: KnowledgeSourceORM) -> KnowledgeSource:
    try:
        return KnowledgeSource(
            source_id=row.source_id,
            source_type=KnowledgeSourceType(row.source_type),
            title=row.title,
            description=row.description,
            approval_status=KnowledgeApprovalStatus(row.approval_status),
            canonical_url=row.canonical_url,
            publisher=row.publisher,
            license_note=row.license_note,
            default_language=row.default_language,
            trusted=row.trusted,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored knowledge source row '{row.source_id}' could not be mapped to a domain KnowledgeSource."
        ) from exc


def knowledge_document_orm_to_domain(row: KnowledgeDocumentORM, skill_ids: list[UUID]) -> KnowledgeDocument:
    try:
        return KnowledgeDocument(
            document_id=row.document_id,
            source_id=row.source_id,
            title=row.title,
            content_text=row.content_text,
            content_hash=row.content_hash,
            language=row.language,
            status=KnowledgeDocumentStatus(row.status),
            approval_status=KnowledgeApprovalStatus(row.approval_status),
            published_at=row.published_at,
            available_at=row.available_at,
            effective_until=row.effective_until,
            lesson_id=row.lesson_id,
            exercise_id=row.exercise_id,
            scenario_id=row.scenario_id,
            portfolio_context_code=row.portfolio_context_code,
            skill_ids=skill_ids,
            document_version=row.document_version,
            parser_version=row.parser_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored knowledge document row '{row.document_id}' could not be mapped to a domain "
            "KnowledgeDocument."
        ) from exc


def knowledge_chunk_orm_to_domain(row: KnowledgeChunkORM) -> KnowledgeChunk:
    try:
        return KnowledgeChunk(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            heading_path=list(row.heading_path),
            content=row.content,
            content_hash=row.content_hash,
            word_count=row.word_count,
            estimated_token_count=row.estimated_token_count,
            available_at=row.available_at,
            effective_until=row.effective_until,
            chunking_version=row.chunking_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored knowledge chunk row '{row.chunk_id}' could not be mapped to a domain KnowledgeChunk."
        ) from exc


def knowledge_chunk_embedding_orm_to_domain(row: KnowledgeChunkEmbeddingORM) -> KnowledgeChunkEmbedding:
    """Lineage only - `row.embedding` (the raw vector) never crosses into the domain model."""
    try:
        return KnowledgeChunkEmbedding(
            embedding_id=row.embedding_id,
            chunk_id=row.chunk_id,
            embedding_model=row.embedding_model,
            embedding_version=row.embedding_version,
            embedding_dimension=row.embedding_dimension,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored knowledge chunk embedding row '{row.embedding_id}' could not be mapped to a domain "
            "KnowledgeChunkEmbedding."
        ) from exc


def tutor_conversation_orm_to_domain(row: TutorConversationORM) -> TutorConversation:
    try:
        return TutorConversation(
            conversation_id=row.conversation_id,
            learner_id=row.learner_id,
            status=TutorConversationStatus(row.status),
            context_type=TutorContextType(row.context_type),
            lesson_id=row.lesson_id,
            exercise_id=row.exercise_id,
            scenario_id=row.scenario_id,
            portfolio_id=row.portfolio_id,
            knowledge_cutoff_at=row.knowledge_cutoff_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            closed_at=row.closed_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored tutor conversation row '{row.conversation_id}' could not be mapped to a domain "
            "TutorConversation."
        ) from exc


def tutor_message_orm_to_domain(row: TutorMessageORM) -> TutorMessage:
    try:
        return TutorMessage(
            message_id=row.message_id,
            conversation_id=row.conversation_id,
            role=TutorMessageRole(row.role),
            content=row.content,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored tutor message row '{row.message_id}' could not be mapped to a domain TutorMessage."
        ) from exc


def tutor_citation_orm_to_domain(row: TutorAnswerCitationORM) -> TutorCitation:
    try:
        return TutorCitation(
            citation_id=row.citation_id,
            answer_id=row.answer_id,
            chunk_id=row.chunk_id,
            citation_number=row.citation_number,
            quoted_excerpt=row.quoted_excerpt,
            source_title=row.source_title,
            document_title=row.document_title,
            heading_path=list(row.heading_path),
            created_at=row.created_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored tutor answer citation row '{row.citation_id}' could not be mapped to a domain "
            "TutorCitation."
        ) from exc


def tutor_answer_orm_to_domain(row: TutorAnswerORM) -> TutorAnswer:
    try:
        return TutorAnswer(
            answer_id=row.answer_id,
            conversation_id=row.conversation_id,
            request_message_id=row.request_message_id,
            status=TutorAnswerStatus(row.status),
            provider_type=TutorProviderType(row.provider_type),
            answer_markdown=row.answer_markdown,
            request_category=TutorRequestCategory(row.request_category),
            grounding_status=GroundingStatus(row.grounding_status),
            retrieval_run_id=row.retrieval_run_id,
            guardrail_decision_id=row.guardrail_decision_id,
            tutor_policy_version=row.tutor_policy_version,
            prompt_version=row.prompt_version,
            model_name=row.model_name,
            model_response_id=row.model_response_id,
            created_at=row.created_at,
            validated_at=row.validated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored tutor answer row '{row.answer_id}' could not be mapped to a domain TutorAnswer."
        ) from exc


def tutor_guardrail_decision_orm_to_domain(row: TutorGuardrailDecisionORM) -> TutorGuardrailDecision:
    try:
        return TutorGuardrailDecision(
            decision_id=row.decision_id,
            conversation_id=row.conversation_id,
            message_id=row.message_id,
            request_category=TutorRequestCategory(row.request_category),
            action=TutorGuardrailAction(row.action),
            matched_rule_codes=list(row.matched_rule_codes),
            safe_response_override=row.safe_response_override,
            policy_version=row.policy_version,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored tutor guardrail decision row '{row.decision_id}' could not be mapped to a domain "
            "TutorGuardrailDecision."
        ) from exc


def tutor_retrieval_run_orm_to_domain(
    row: TutorRetrievalRunORM, returned_chunk_ids: list[UUID], returned_scores: list[float]
) -> TutorRetrievalRun:
    try:
        return TutorRetrievalRun(
            retrieval_run_id=row.retrieval_run_id,
            conversation_id=row.conversation_id,
            query_text=row.query_text,
            method=RetrievalMethod(row.method),
            top_k=row.top_k,
            knowledge_cutoff_at=row.knowledge_cutoff_at,
            retrieval_policy_version=row.retrieval_policy_version,
            embedding_model=row.embedding_model,
            embedding_version=row.embedding_version,
            candidate_count=row.candidate_count,
            returned_chunk_ids=returned_chunk_ids,
            returned_scores=returned_scores,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored tutor retrieval run row '{row.retrieval_run_id}' could not be mapped to a domain "
            "TutorRetrievalRun."
        ) from exc


def tutor_knowledge_gap_orm_to_domain(row: TutorKnowledgeGapORM, target_skill_ids: list[UUID]) -> TutorKnowledgeGap:
    try:
        return TutorKnowledgeGap(
            gap_id=row.gap_id,
            learner_id=row.learner_id,
            conversation_id=row.conversation_id,
            message_id=row.message_id,
            normalized_question=row.normalized_question,
            context_type=TutorContextType(row.context_type),
            target_skill_ids=target_skill_ids,
            occurrence_count=row.occurrence_count,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            resolved=row.resolved,
            resolved_at=row.resolved_at,
            resolution_document_id=row.resolution_document_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored tutor knowledge gap row '{row.gap_id}' could not be mapped to a domain TutorKnowledgeGap."
        ) from exc
