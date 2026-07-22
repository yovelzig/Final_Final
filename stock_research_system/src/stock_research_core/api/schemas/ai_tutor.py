"""Request/response DTOs for `/api/v1/tutor`.

`AskResponse` is built only from `TutorResponse`/`LearnerSafeCitation` -
never a chunk ID, embedding vector, or raw prompt text crosses into a
response here, matching the guarantee `LearnerSafeCitation` already
makes at the application layer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.application.ai_tutor.models import LearnerSafeCitation, TutorResponse
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    TutorAnswerStatus,
    TutorContextType,
    TutorConversationStatus,
    TutorGuardrailAction,
    TutorMessageRole,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import TutorConversation, TutorMessage


class CreateConversationRequest(ApiSchema):
    context_type: TutorContextType
    lesson_id: UUID | None = None
    exercise_id: UUID | None = None
    scenario_id: UUID | None = None
    submission_id: UUID | None = None
    portfolio_id: UUID | None = None
    as_of: datetime | None = None

    @model_validator(mode="after")
    def _validate_required_fields(self) -> CreateConversationRequest:
        required: dict[TutorContextType, tuple[str, ...]] = {
            TutorContextType.LESSON_HELP: ("lesson_id",),
            TutorContextType.EXERCISE_HELP: ("exercise_id",),
            TutorContextType.SCENARIO_BEFORE_DECISION: ("scenario_id", "submission_id"),
            TutorContextType.SCENARIO_AFTER_REVEAL: ("submission_id",),
            TutorContextType.PORTFOLIO_EXPLANATION: ("portfolio_id",),
        }
        for field_name in required.get(self.context_type, ()):
            if getattr(self, field_name) is None:
                raise ValueError(f"'{field_name}' is required for context_type '{self.context_type.value}'.")
        return self


class TutorConversationResponse(ApiSchema):
    conversation_id: UUID
    status: TutorConversationStatus
    context_type: TutorContextType
    lesson_id: UUID | None
    exercise_id: UUID | None
    scenario_id: UUID | None
    portfolio_id: UUID | None
    created_at: datetime
    closed_at: datetime | None

    @staticmethod
    def from_domain(conversation: TutorConversation) -> TutorConversationResponse:
        return TutorConversationResponse(
            conversation_id=conversation.conversation_id, status=conversation.status,
            context_type=conversation.context_type, lesson_id=conversation.lesson_id,
            exercise_id=conversation.exercise_id, scenario_id=conversation.scenario_id,
            portfolio_id=conversation.portfolio_id, created_at=conversation.created_at,
            closed_at=conversation.closed_at,
        )


class TutorMessageResponse(ApiSchema):
    message_id: UUID
    role: TutorMessageRole
    content: str
    created_at: datetime

    @staticmethod
    def from_domain(message: TutorMessage) -> TutorMessageResponse:
        return TutorMessageResponse(
            message_id=message.message_id, role=message.role, content=message.content,
            created_at=message.created_at,
        )


class AskQuestionRequest(ApiSchema):
    question: str = Field(min_length=1, max_length=10_000)
    exercise_submitted: bool = False
    as_of: datetime | None = None
    top_k: int = Field(default=8, ge=1, le=50)


class CitationResponse(ApiSchema):
    """Learner-safe: no `chunk_id`, vector, or raw prompt text."""

    citation_number: int
    source_title: str
    document_title: str
    heading_path: list[str]
    excerpt: str

    @staticmethod
    def from_domain(citation: LearnerSafeCitation) -> CitationResponse:
        return CitationResponse(
            citation_number=citation.citation_number, source_title=citation.source_title,
            document_title=citation.document_title, heading_path=list(citation.heading_path),
            excerpt=citation.excerpt,
        )


class AskResponse(ApiSchema):
    answer_markdown: str
    status: TutorAnswerStatus
    grounding_status: GroundingStatus
    request_category: TutorRequestCategory
    guardrail_action: TutorGuardrailAction
    citations: list[CitationResponse]
    created_at: datetime

    @staticmethod
    def from_domain(response: TutorResponse) -> AskResponse:
        return AskResponse(
            answer_markdown=response.answer.answer_markdown, status=response.answer.status,
            grounding_status=response.answer.grounding_status,
            request_category=response.answer.request_category, guardrail_action=response.guardrail.action,
            citations=[CitationResponse.from_domain(c) for c in response.citations],
            created_at=response.answer.created_at,
        )
