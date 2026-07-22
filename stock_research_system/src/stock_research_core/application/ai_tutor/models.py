"""Application-level result and request/response models for the grounded AI tutor.

Composite views assembled from ai-tutor-domain objects. Plain Pydantic
models; no SQLAlchemy, pgvector, sentence-transformers, or LLM-SDK
dependency here. `LearnerSafeCitation` is the only citation shape ever
handed to learner-facing callers - it deliberately omits `chunk_id` so
raw internal identifiers never leak into a learner-facing response.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeIngestionRunStatus,
    TutorContextType,
    TutorProviderType,
)
from stock_research_core.domain.ai_tutor.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    TutorAnswer,
    TutorGuardrailDecision,
    TutorMessage,
)
from stock_research_core.domain.models import DomainModel


def _is_finite(value: float) -> bool:
    return math.isfinite(value)


class LearnerSafeCitation(DomainModel):
    """A citation shape safe to return to a learner: no internal chunk ID."""

    citation_number: int = Field(gt=0)
    source_title: str = Field(min_length=1, max_length=300)
    document_title: str = Field(min_length=1, max_length=300)
    heading_path: list[str] = Field(default_factory=list)
    excerpt: str = Field(min_length=1, max_length=500)


class TutorResponse(DomainModel):
    """The full learner-facing result of one `GroundedAITutorService.ask()` call."""

    answer: TutorAnswer
    citations: list[LearnerSafeCitation] = Field(default_factory=list)
    guardrail: TutorGuardrailDecision


class RetrievalCandidate(DomainModel):
    """One ranked candidate chunk produced by a `KnowledgeRetrieverPort`."""

    chunk: KnowledgeChunk
    source: KnowledgeSource
    document: KnowledgeDocument

    vector_score: float | None = None
    lexical_score: float | None = None
    metadata_score: float = Field(ge=0, le=1)
    combined_score: float

    @model_validator(mode="after")
    def _validate_candidate(self) -> RetrievalCandidate:
        for score in (self.vector_score, self.lexical_score, self.combined_score):
            if score is not None and not _is_finite(score):
                raise ValueError("RetrievalCandidate scores must be finite")
        if self.source.approval_status != KnowledgeApprovalStatus.APPROVED:
            raise ValueError("candidate source must be APPROVED")
        if self.document.approval_status != KnowledgeApprovalStatus.APPROVED:
            raise ValueError("candidate document must be APPROVED")
        if self.document.status != KnowledgeDocumentStatus.PROCESSED:
            raise ValueError("candidate document must be PROCESSED")
        if self.chunk.document_id != self.document.document_id:
            raise ValueError("candidate chunk must belong to the supplied document")
        if self.document.source_id != self.source.source_id:
            raise ValueError("candidate document must belong to the supplied source")
        return self


class TutorContext(DomainModel):
    """Sanitized, point-in-time-safe context for one tutor request.

    `structured_context` may only hold already-sanitized educational
    facts (e.g. computed portfolio risk metrics, scenario metadata up
    to the decision cutoff) - never raw database rows, ORM objects, or
    future/hidden information.
    """

    context_type: TutorContextType
    learner_id: UUID

    lesson_id: UUID | None = None
    exercise_id: UUID | None = None
    scenario_id: UUID | None = None
    scenario_submission_id: UUID | None = None
    portfolio_id: UUID | None = None

    knowledge_cutoff_at: datetime | None = None
    target_skill_ids: list[UUID] = Field(default_factory=list)

    structured_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_target_skills(self) -> TutorContext:
        if len(set(self.target_skill_ids)) != len(self.target_skill_ids):
            raise ValueError("target_skill_ids must not contain duplicates")
        return self


class TutorModelRequest(DomainModel):
    """Everything a `TutorModelPort` needs to produce a grounded answer."""

    system_instructions: str = Field(min_length=1)
    user_question: str = Field(min_length=1, max_length=10_000)
    conversation_messages: list[TutorMessage] = Field(default_factory=list)
    retrieved_candidates: list[RetrievalCandidate] = Field(default_factory=list)
    structured_context: dict[str, Any] = Field(default_factory=dict)

    prompt_version: str = Field(min_length=1, max_length=50)
    maximum_output_tokens: int = Field(gt=0, default=800)


class TutorModelResult(DomainModel):
    """The raw result of one `TutorModelPort.generate()` call.

    No hidden-reasoning or chain-of-thought field exists on this model
    by design - a provider adapter must never populate one.
    """

    answer_markdown: str = Field(min_length=1)
    cited_chunk_ids: list[UUID] = Field(default_factory=list)
    provider_type: TutorProviderType
    model_name: str = Field(min_length=1, max_length=200)
    model_response_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _validate_citations(self) -> TutorModelResult:
        if len(set(self.cited_chunk_ids)) != len(self.cited_chunk_ids):
            raise ValueError("cited_chunk_ids must not contain duplicates")
        return self


class KnowledgeIngestionRunRecord(DomainModel):
    """A stored knowledge-ingestion-run audit record, independent of any ORM row."""

    run_id: UUID
    source_id: UUID | None = None
    document_id: UUID | None = None
    status: KnowledgeIngestionRunStatus
    documents_processed: int = Field(ge=0, default=0)
    chunks_created: int = Field(ge=0, default=0)
    embeddings_created: int = Field(ge=0, default=0)
    chunking_version: str = Field(min_length=1, max_length=50)
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_version: str = Field(min_length=1, max_length=50)
    started_at: datetime
    completed_at: datetime | None = None
    error_type: str | None = None
    error_message: str | None = None


class KnowledgeIngestionSummary(DomainModel):
    """The outcome of one `KnowledgeIngestionService` call."""

    run: KnowledgeIngestionRunRecord
    sources_created: int = Field(ge=0, default=0)
    sources_updated: int = Field(ge=0, default=0)
    documents_created: int = Field(ge=0, default=0)
    documents_updated: int = Field(ge=0, default=0)
    documents_archived: int = Field(ge=0, default=0)
    documents_skipped_unchanged: int = Field(ge=0, default=0)
    chunks_created: int = Field(ge=0, default=0)
    embeddings_created: int = Field(ge=0, default=0)


class RetrievalEvaluationResult(DomainModel):
    """One case's outcome from the deterministic retrieval evaluation script."""

    case_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2000)
    expected_document_ids: list[UUID] = Field(default_factory=list)
    returned_document_ids: list[UUID] = Field(default_factory=list)

    hit_at_k: bool
    reciprocal_rank: float = Field(ge=0, le=1)
    citation_valid: bool
    guardrail_correct: bool
    fallback_correct: bool
