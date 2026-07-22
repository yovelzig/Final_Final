"""Application-level Protocols for the grounded AI tutor and knowledge base.

Pure `Protocol` definitions - no SQLAlchemy, pgvector, sentence-transformers,
or LLM-SDK import here. Concrete implementations live under
`stock_research_core.infrastructure.ai_tutor` (embeddings, tutor models,
document parsers) and `stock_research_core.infrastructure.database`
(repositories).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.application.ai_tutor.models import (
    KnowledgeIngestionRunRecord,
    RetrievalCandidate,
    TutorContext,
    TutorModelRequest,
    TutorModelResult,
)
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    KnowledgeIngestionRunStatus,
    TutorAnswerStatus,
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


class EmbeddingPort(Protocol):
    """Turns text into vectors. Never imported by the domain layer."""

    @property
    def model_name(self) -> str: ...

    @property
    def embedding_version(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class KnowledgeChunkerPort(Protocol):
    """Deterministically splits a `KnowledgeDocument` into `KnowledgeChunk`s."""

    @property
    def chunking_version(self) -> str: ...

    def chunk(
        self, *, document: KnowledgeDocument, chunking_version: str
    ) -> list[KnowledgeChunk]: ...


class KnowledgeRetrieverPort(Protocol):
    """Retrieves approved knowledge relevant to one tutor query."""

    async def retrieve(
        self, *, query: str, context: TutorContext, top_k: int
    ) -> tuple[TutorRetrievalRun, list[RetrievalCandidate]]: ...


class TutorModelPort(Protocol):
    """Generates a grounded answer from a fully-built `TutorModelRequest`."""

    async def generate(self, request: TutorModelRequest) -> TutorModelResult: ...


class TutorGuardrailPort(Protocol):
    """Deterministic input/output safety policy for the tutor."""

    def evaluate_input(
        self, *, conversation_id: UUID, message: TutorMessage, context: TutorContext
    ) -> TutorGuardrailDecision: ...

    def validate_output(
        self,
        *,
        answer_text: str,
        cited_chunk_ids: list[UUID],
        retrieved_candidates: list[RetrievalCandidate],
        context: TutorContext,
    ) -> tuple[GroundingStatus, list[str]]: ...


class TutorPromptBuilderPort(Protocol):
    """Builds the model-ready `TutorModelRequest` for one question."""

    def build(
        self,
        *,
        question: str,
        conversation_messages: list[TutorMessage],
        candidates: list[RetrievalCandidate],
        context: TutorContext,
    ) -> TutorModelRequest: ...


class KnowledgeRepositoryPort(Protocol):
    """Persists and queries knowledge sources, documents, chunks, and embeddings."""

    async def upsert_source(self, source: KnowledgeSource) -> KnowledgeSource: ...

    async def get_source(self, source_id: UUID) -> KnowledgeSource | None: ...

    async def upsert_document(self, document: KnowledgeDocument) -> KnowledgeDocument: ...

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None: ...

    async def get_document_by_hash(
        self, *, source_id: UUID, content_hash: str
    ) -> KnowledgeDocument | None: ...

    async def list_approved_documents(
        self,
        *,
        language: str | None = None,
        lesson_id: UUID | None = None,
        exercise_id: UUID | None = None,
        scenario_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> list[KnowledgeDocument]: ...

    async def archive_document(self, document_id: UUID) -> KnowledgeDocument: ...

    async def upsert_chunks(self, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]: ...

    async def list_chunks_for_document(self, document_id: UUID) -> list[KnowledgeChunk]: ...

    async def upsert_embeddings(
        self, embeddings: list[KnowledgeChunkEmbedding], vectors: list[list[float]]
    ) -> list[KnowledgeChunkEmbedding]: ...

    async def get_chunk_with_metadata(self, chunk_id: UUID) -> RetrievalCandidate | None: ...

    async def hybrid_search(
        self,
        *,
        query_embedding: list[float] | None,
        embedding_model: str | None,
        embedding_version: str | None,
        lexical_query: str,
        top_k: int,
        candidate_pool_size: int = 40,
        approved_only: bool = True,
        language: str = "en",
        skill_ids: list[UUID] | None = None,
        lesson_id: UUID | None = None,
        exercise_id: UUID | None = None,
        scenario_id: UUID | None = None,
        portfolio_context_code: str | None = None,
        knowledge_cutoff_at: datetime | None = None,
    ) -> tuple[list[RetrievalCandidate], int]: ...

    async def start_ingestion_run(
        self,
        *,
        source_id: UUID | None,
        document_id: UUID | None,
        chunking_version: str,
        embedding_model: str,
        embedding_version: str,
    ) -> KnowledgeIngestionRunRecord: ...

    async def complete_ingestion_run(
        self,
        run_id: UUID,
        *,
        status: KnowledgeIngestionRunStatus,
        documents_processed: int = 0,
        chunks_created: int = 0,
        embeddings_created: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> KnowledgeIngestionRunRecord: ...

    async def list_recent_ingestion_runs(self, limit: int = 10) -> list[KnowledgeIngestionRunRecord]: ...

    async def list_processed_document_ids(self, *, limit: int = 10_000) -> list[UUID]:
        """All `PROCESSED` (non-archived) document IDs, system-wide.

        Added for Phase 11's `KNOWLEDGE_REEMBED` job's "re-embed
        everything" mode (`document_ids=None`) - an operational,
        system-wide listing, not a learner-facing query."""
        ...

    async def count_sources(self) -> int: ...

    async def count_approved_documents(self) -> int: ...

    async def count_chunks(self) -> int: ...

    async def count_embeddings(self) -> int: ...


class ConversationRepositoryPort(Protocol):
    """Persists and queries tutor conversations and their immutable messages."""

    async def create_conversation(self, conversation: TutorConversation) -> TutorConversation: ...

    async def get_conversation(self, conversation_id: UUID) -> TutorConversation | None: ...

    async def list_active_conversations_for_learner(
        self, learner_id: UUID
    ) -> list[TutorConversation]: ...

    async def add_message(self, message: TutorMessage) -> TutorMessage: ...

    async def list_recent_messages(
        self, conversation_id: UUID, limit: int = 10
    ) -> list[TutorMessage]: ...

    async def close_conversation(
        self, conversation_id: UUID, *, closed_at: datetime
    ) -> TutorConversation: ...


class TutorAnswerRepositoryPort(Protocol):
    """Persists and queries tutor answers and their citations."""

    async def save_answer(self, answer: TutorAnswer) -> TutorAnswer: ...

    async def save_citations(self, citations: list[TutorCitation]) -> list[TutorCitation]: ...

    async def get_answer(self, answer_id: UUID) -> TutorAnswer | None: ...

    async def list_citations_for_answer(self, answer_id: UUID) -> list[TutorCitation]: ...

    async def list_answers_for_conversation(self, conversation_id: UUID) -> list[TutorAnswer]: ...

    async def update_validation_status(
        self,
        answer_id: UUID,
        *,
        status: TutorAnswerStatus,
        grounding_status: GroundingStatus,
        validated_at: datetime | None,
    ) -> TutorAnswer: ...


class GuardrailRepositoryPort(Protocol):
    """Persists and queries guardrail decisions."""

    async def save_decision(self, decision: TutorGuardrailDecision) -> TutorGuardrailDecision: ...

    async def get_decision(self, decision_id: UUID) -> TutorGuardrailDecision | None: ...

    async def list_decisions_for_conversation(
        self, conversation_id: UUID
    ) -> list[TutorGuardrailDecision]: ...


class RetrievalAuditRepositoryPort(Protocol):
    """Persists and queries retrieval-run audit records."""

    async def save_run(
        self, run: TutorRetrievalRun, candidates: list[RetrievalCandidate]
    ) -> TutorRetrievalRun: ...

    async def get_run(self, retrieval_run_id: UUID) -> TutorRetrievalRun | None: ...

    async def list_recent_runs(self, conversation_id: UUID, limit: int = 10) -> list[TutorRetrievalRun]: ...


class KnowledgeGapRepositoryPort(Protocol):
    """Persists and queries tracked knowledge gaps."""

    async def upsert_gap(self, gap: TutorKnowledgeGap) -> TutorKnowledgeGap: ...

    async def get_by_question_and_context(
        self, normalized_question: str, context_type: str
    ) -> TutorKnowledgeGap | None: ...

    async def list_unresolved_gaps(self, limit: int = 50) -> list[TutorKnowledgeGap]: ...

    async def resolve_gap(
        self, gap_id: UUID, *, resolved_at: datetime, resolution_document_id: UUID | None
    ) -> TutorKnowledgeGap: ...

    async def count_repeated_gaps(self, minimum_occurrences: int = 2) -> int: ...
