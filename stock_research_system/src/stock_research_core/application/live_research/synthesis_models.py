"""Grounded Live Research synthesis request/result models (spec G2D2/H1
correction pass, section 6) - parallel to, and never interchangeable
with, `ai_tutor.models.TutorModelRequest`/`TutorModelResult`.

Live Research citations are persisted `EvidenceItem` IDs from a
verified, run-scoped `ResearchRun` - never Tutor knowledge-chunk IDs.
`ResearchModelProviderType` lives here (application layer), not in
`domain.live_research.enums`, because that module's own docstring is
explicit that it "has no knowledge of any provider ... OpenAI" - the
domain layer for this bounded context stays provider-neutral.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from stock_research_core.domain.live_research.enums import ResearchScope
from stock_research_core.domain.models import DomainModel


class ResearchModelProviderType(StrEnum):
    OLLAMA_CLOUD = "OLLAMA_CLOUD"
    OPENAI_REASONING = "OPENAI_REASONING"


class ResearchEvidenceInput(DomainModel):
    """One verified `EvidenceItem`, reduced to exactly the fields the
    synthesis model needs to see - never the full ORM/domain row, never
    internal provenance fields the model has no business reading."""

    evidence_id: UUID
    source_title: str = Field(min_length=1, max_length=1000)
    publisher: str = Field(min_length=1, max_length=250)
    excerpt: str = Field(default="", max_length=5000)
    official: bool = False


class ResearchSynthesisRequest(DomainModel):
    system_instructions: str = Field(min_length=1)
    user_question: str = Field(min_length=1, max_length=10_000)
    scope: ResearchScope
    #: Only verified, run-scoped `EvidenceItem`s - never model-generated,
    #: never sourced from a resume payload.
    evidence_items: list[ResearchEvidenceInput] = Field(default_factory=list, max_length=50)
    prompt_version: str = Field(min_length=1, max_length=50)
    maximum_output_tokens: int = Field(gt=0, default=800)


class ResearchSynthesisResult(DomainModel):
    answer_markdown: str = Field(min_length=1, max_length=20_000)
    #: Must be re-verified by `ResearchEvidenceCitationVerifier` before
    #: use - this model only guarantees internal shape (no duplicates),
    #: never that a cited id actually belongs to the verified run.
    cited_evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)
    provider_type: ResearchModelProviderType
    model_name: str = Field(min_length=1, max_length=200)
    model_response_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _validate_citations(self) -> ResearchSynthesisResult:
        if len(set(self.cited_evidence_ids)) != len(self.cited_evidence_ids):
            raise ValueError("cited_evidence_ids must not contain duplicates")
        return self
