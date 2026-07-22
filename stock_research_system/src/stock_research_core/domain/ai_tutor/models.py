"""Domain models for the FinQuest grounded AI tutor and knowledge base.

Technology-independent: no SQLAlchemy, FastAPI, pgvector,
sentence-transformers, OpenAI/Anthropic/Ollama/Perplexity, LangGraph, n8n,
pandas, NumPy, or yfinance import may appear here. Raw embedding vectors
never appear on a domain model - `KnowledgeChunkEmbedding` only carries
lineage (model, version, dimension), never the vector itself.

This is an **educational tutor**, not a source of stock predictions or
personalized investment advice - several validators below exist purely to
make that boundary structurally hard to violate (e.g. fallback answers
must use the exact approved sentence, refusal/fallback guardrail
decisions must carry an English override).
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pydantic import Field, ValidationInfo, field_validator, model_validator

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
from stock_research_core.domain.models import DomainModel, utc_now

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# Deterministic, conservative heuristics only - not a security control.
# Good enough to keep obvious secrets (API keys, private key blocks,
# password= assignments) out of stored knowledge/learner content.
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\b(api[_-]?key|secret|password|passwd)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

EXACT_INSUFFICIENT_EVIDENCE_FALLBACK = (
    "I don’t have enough approved FinQuest material to answer that reliably."
)
EXACT_ADVICE_REFUSAL = (
    "I can explain the concepts, risks, and educational examples, but I can’t tell you "
    "what to buy, sell, or personally invest in."
)
EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL = (
    "I can help you evaluate the risks, time horizon, diversification, and information "
    "available at the decision point, but I can’t reveal the future outcome or identify "
    "the correct option."
)


def _reject_secrets(value: str, field_name: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"{field_name} appears to contain a secret and cannot be stored")
    return value


def _validate_content_hash(value: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ValueError("content_hash must be a lowercase hexadecimal SHA-256 digest")
    return normalized


def _validate_optional_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("canonical_url must be a valid http(s) URL")
    return value


def _normalize_unique_headings(values: list[str]) -> list[str]:
    trimmed = [value.strip() for value in values]
    if any(not value for value in trimmed):
        raise ValueError("heading_path entries cannot be blank")
    if len(set(trimmed)) != len(trimmed):
        raise ValueError("heading_path entries must be unique")
    return trimmed


def _validate_unique_uuids(values: list[UUID], field_name: str) -> list[UUID]:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


class KnowledgeSource(DomainModel):
    """An approved (or pending-approval) origin of retrievable FinQuest content."""

    source_id: UUID = Field(default_factory=uuid4)
    source_type: KnowledgeSourceType
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)

    approval_status: KnowledgeApprovalStatus = KnowledgeApprovalStatus.DRAFT
    canonical_url: str | None = None
    publisher: str | None = Field(default=None, max_length=300)
    license_note: str | None = Field(default=None, max_length=1000)

    default_language: str = Field(default="en", min_length=2, max_length=10)
    trusted: bool = False

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("canonical_url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        return _validate_optional_url(value)

    @field_validator("description", "license_note")
    @classmethod
    def _validate_free_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None:
            _reject_secrets(value, info.field_name)
        return value


class KnowledgeDocument(DomainModel):
    """One approved, retrievable unit of FinQuest educational content."""

    document_id: UUID = Field(default_factory=uuid4)
    source_id: UUID

    title: str = Field(min_length=1, max_length=300)
    content_text: str = Field(min_length=1)
    content_hash: str
    language: str = Field(default="en", min_length=2, max_length=10)

    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.PENDING
    approval_status: KnowledgeApprovalStatus = KnowledgeApprovalStatus.DRAFT

    published_at: datetime | None = None
    available_at: datetime
    effective_until: datetime | None = None

    lesson_id: UUID | None = None
    exercise_id: UUID | None = None
    scenario_id: UUID | None = None
    portfolio_context_code: str | None = Field(default=None, max_length=100)

    skill_ids: list[UUID] = Field(default_factory=list)

    document_version: str = Field(default="v1", min_length=1, max_length=50)
    parser_version: str = Field(min_length=1, max_length=50)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("content_hash")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        return _validate_content_hash(value)

    @field_validator("content_text")
    @classmethod
    def _validate_content(cls, value: str, info: ValidationInfo) -> str:
        return _reject_secrets(value, info.field_name)

    @field_validator("skill_ids")
    @classmethod
    def _validate_skill_ids(cls, value: list[UUID]) -> list[UUID]:
        return _validate_unique_uuids(value, "skill_ids")

    @model_validator(mode="after")
    def _validate_document(self) -> KnowledgeDocument:
        if self.status == KnowledgeDocumentStatus.PROCESSED and not self.content_text.strip():
            raise ValueError("a PROCESSED document must have non-empty content_text")
        if self.effective_until is not None and self.effective_until < self.available_at:
            raise ValueError("effective_until cannot precede available_at")
        return self


class KnowledgeChunk(DomainModel):
    """One deterministically-produced, retrievable slice of a `KnowledgeDocument`."""

    chunk_id: UUID = Field(default_factory=uuid4)
    document_id: UUID

    chunk_index: int = Field(ge=0)
    heading_path: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1)
    content_hash: str

    word_count: int = Field(gt=0)
    estimated_token_count: int = Field(gt=0)

    available_at: datetime
    effective_until: datetime | None = None

    chunking_version: str = Field(min_length=1, max_length=50)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("content_hash")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        return _validate_content_hash(value)

    @field_validator("heading_path")
    @classmethod
    def _validate_headings(cls, value: list[str]) -> list[str]:
        return _normalize_unique_headings(value)

    @model_validator(mode="after")
    def _validate_chunk(self) -> KnowledgeChunk:
        if self.effective_until is not None and self.effective_until < self.available_at:
            raise ValueError("effective_until cannot precede available_at")
        return self


class KnowledgeChunkEmbedding(DomainModel):
    """Lineage of a chunk's stored embedding. The raw vector never appears here."""

    embedding_id: UUID = Field(default_factory=uuid4)
    chunk_id: UUID

    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_version: str = Field(min_length=1, max_length=50)
    embedding_dimension: int = Field(gt=0)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TutorConversation(DomainModel):
    """A learner's conversation thread with the grounded AI tutor."""

    conversation_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    status: TutorConversationStatus = TutorConversationStatus.ACTIVE
    context_type: TutorContextType

    lesson_id: UUID | None = None
    exercise_id: UUID | None = None
    scenario_id: UUID | None = None
    portfolio_id: UUID | None = None

    knowledge_cutoff_at: datetime | None = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_conversation(self) -> TutorConversation:
        if self.status == TutorConversationStatus.CLOSED and self.closed_at is None:
            raise ValueError("a CLOSED conversation requires closed_at")
        if self.status != TutorConversationStatus.CLOSED and self.closed_at is not None:
            raise ValueError("closed_at may only be set when status is CLOSED")
        if self.context_type == TutorContextType.LESSON_HELP and self.lesson_id is None:
            raise ValueError("LESSON_HELP context requires lesson_id")
        if self.context_type == TutorContextType.EXERCISE_HELP and self.exercise_id is None:
            raise ValueError("EXERCISE_HELP context requires exercise_id")
        if self.context_type in (
            TutorContextType.SCENARIO_BEFORE_DECISION,
            TutorContextType.SCENARIO_AFTER_REVEAL,
        ):
            if self.scenario_id is None:
                raise ValueError(f"{self.context_type.value} context requires scenario_id")
        if self.context_type == TutorContextType.SCENARIO_BEFORE_DECISION and self.knowledge_cutoff_at is None:
            raise ValueError("SCENARIO_BEFORE_DECISION context requires knowledge_cutoff_at")
        if self.context_type == TutorContextType.PORTFOLIO_EXPLANATION and self.portfolio_id is None:
            raise ValueError("PORTFOLIO_EXPLANATION context requires portfolio_id")
        return self


class TutorMessage(DomainModel):
    """One immutable message within a `TutorConversation`.

    Message content is conversation *context*, never treated as an
    approved factual source by the retrieval or answering layers.
    """

    message_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    role: TutorMessageRole
    content: str = Field(min_length=1, max_length=10_000)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str, info: ValidationInfo) -> str:
        return _reject_secrets(value, info.field_name)


class TutorCitation(DomainModel):
    """One citation on a `TutorAnswer`, pointing to an exact retrieved chunk."""

    citation_id: UUID = Field(default_factory=uuid4)
    answer_id: UUID
    chunk_id: UUID

    citation_number: int = Field(gt=0)
    quoted_excerpt: str = Field(min_length=1, max_length=500)
    source_title: str = Field(min_length=1, max_length=300)
    document_title: str = Field(min_length=1, max_length=300)
    heading_path: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("heading_path")
    @classmethod
    def _validate_headings(cls, value: list[str]) -> list[str]:
        return _normalize_unique_headings(value)


class TutorAnswer(DomainModel):
    """The tutor's response to one learner message, with full lineage."""

    answer_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    request_message_id: UUID

    status: TutorAnswerStatus = TutorAnswerStatus.GENERATED
    provider_type: TutorProviderType

    answer_markdown: str = Field(min_length=1)
    request_category: TutorRequestCategory
    grounding_status: GroundingStatus

    retrieval_run_id: UUID | None = None
    guardrail_decision_id: UUID

    tutor_policy_version: str = Field(min_length=1, max_length=50)
    prompt_version: str = Field(min_length=1, max_length=50)
    model_name: str = Field(min_length=1, max_length=200)
    model_response_id: str | None = Field(default=None, max_length=200)

    created_at: datetime = Field(default_factory=utc_now)
    validated_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_answer(self) -> TutorAnswer:
        if self.status == TutorAnswerStatus.VALIDATED and self.validated_at is None:
            raise ValueError("a VALIDATED answer requires validated_at")
        if self.grounding_status == GroundingStatus.GROUNDED and self.retrieval_run_id is None:
            raise ValueError("a GROUNDED answer requires a retrieval_run_id")
        if self.status == TutorAnswerStatus.FALLBACK and self.answer_markdown != EXACT_INSUFFICIENT_EVIDENCE_FALLBACK:
            raise ValueError("a FALLBACK answer must use the exact approved fallback text")
        return self


class TutorGuardrailDecision(DomainModel):
    """The deterministic guardrail evaluation for one learner message."""

    decision_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    message_id: UUID

    request_category: TutorRequestCategory
    action: TutorGuardrailAction
    matched_rule_codes: list[str] = Field(default_factory=list)

    safe_response_override: str | None = Field(default=None, max_length=2000)
    policy_version: str = Field(min_length=1, max_length=50)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("matched_rule_codes")
    @classmethod
    def _validate_rule_codes(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("matched_rule_codes must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _validate_decision(self) -> TutorGuardrailDecision:
        if self.action in (TutorGuardrailAction.REFUSE, TutorGuardrailAction.FALLBACK):
            if not self.safe_response_override:
                raise ValueError(f"{self.action.value} requires a safe_response_override")
        return self


class TutorRetrievalRun(DomainModel):
    """An audit record of one retrieval query issued on behalf of the tutor."""

    retrieval_run_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    query_text: str = Field(min_length=1, max_length=2000)

    method: RetrievalMethod = RetrievalMethod.HYBRID
    top_k: int = Field(ge=1, le=50)
    knowledge_cutoff_at: datetime | None = None

    retrieval_policy_version: str = Field(min_length=1, max_length=50)
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_version: str = Field(min_length=1, max_length=50)

    candidate_count: int = Field(ge=0)
    returned_chunk_ids: list[UUID] = Field(default_factory=list)
    returned_scores: list[float] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("query_text")
    @classmethod
    def _validate_query(cls, value: str, info: ValidationInfo) -> str:
        return _reject_secrets(value, info.field_name)

    @model_validator(mode="after")
    def _validate_run(self) -> TutorRetrievalRun:
        if len(self.returned_chunk_ids) != len(self.returned_scores):
            raise ValueError("returned_chunk_ids and returned_scores must have equal lengths")
        if any(not _is_finite(score) for score in self.returned_scores):
            raise ValueError("returned_scores must all be finite")
        return self


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


class TutorKnowledgeGap(DomainModel):
    """A tracked, normalized instance of an unanswerable learner question."""

    gap_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    conversation_id: UUID
    message_id: UUID

    normalized_question: str = Field(min_length=1, max_length=2000)
    context_type: TutorContextType
    target_skill_ids: list[UUID] = Field(default_factory=list)

    occurrence_count: int = Field(gt=0, default=1)
    first_seen_at: datetime
    last_seen_at: datetime

    resolved: bool = False
    resolved_at: datetime | None = None
    resolution_document_id: UUID | None = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("normalized_question")
    @classmethod
    def _validate_question(cls, value: str, info: ValidationInfo) -> str:
        return _reject_secrets(value, info.field_name)

    @field_validator("target_skill_ids")
    @classmethod
    def _validate_skill_ids(cls, value: list[UUID]) -> list[UUID]:
        return _validate_unique_uuids(value, "target_skill_ids")

    @model_validator(mode="after")
    def _validate_gap(self) -> TutorKnowledgeGap:
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at cannot precede first_seen_at")
        if self.resolved and self.resolved_at is None:
            raise ValueError("a resolved gap requires resolved_at")
        if not self.resolved and self.resolved_at is not None:
            raise ValueError("resolved_at may only be set when resolved is True")
        return self
