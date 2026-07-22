"""Request/response DTOs for `/api/v1/coach` (spec sections 24-25).

Every response model here is built only from a `LearningOrchestratorThread`
/ `Run` / `Event` / the graph's own `final_response` dict - never a raw
checkpoint, a checkpoint id, prompt text, chain-of-thought, the internal
tool/action registry, or a provider API key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import (
    LearnerApprovalDecision,
    LearningIntent,
    LearningOrchestratorEventType,
    LearningOrchestratorRoute,
    LearningOrchestratorRunStatus,
    LearningOrchestratorThreadStatus,
)
from stock_research_core.domain.learning_orchestrator.models import (
    LearningOrchestratorEvent,
    LearningOrchestratorRun,
    LearningOrchestratorThread,
)

_MAX_CONTEXT_REFERENCE_VALUE_LENGTH = 64


class CreateThreadRequest(ApiSchema):
    title: str = Field(default="New conversation", min_length=1, max_length=200)
    initial_context_type: TutorContextType = TutorContextType.GENERAL_EDUCATION


class LearningCoachThreadResponse(ApiSchema):
    thread_id: UUID
    status: LearningOrchestratorThreadStatus
    title: str
    current_context_type: TutorContextType
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None

    @staticmethod
    def from_domain(thread: LearningOrchestratorThread) -> LearningCoachThreadResponse:
        return LearningCoachThreadResponse(
            thread_id=thread.thread_id, status=thread.status, title=thread.title,
            current_context_type=thread.current_context_type, created_at=thread.created_at,
            updated_at=thread.updated_at, closed_at=thread.closed_at,
        )


class LearningCoachThreadListResponse(ApiSchema):
    items: list[LearningCoachThreadResponse]
    total: int
    limit: int
    offset: int


class StartRunRequest(ApiSchema):
    user_input: str = Field(min_length=1, max_length=4_000)
    context_references: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_context_references(self) -> StartRunRequest:
        for key, value in self.context_references.items():
            if len(value) > _MAX_CONTEXT_REFERENCE_VALUE_LENGTH:
                raise ValueError(f"context_references['{key}'] is too long.")
            try:
                UUID(value)
            except ValueError as exc:
                raise ValueError(f"context_references['{key}'] must be a UUID string.") from exc
        return self


class LearningCoachRunResponse(ApiSchema):
    run_id: UUID
    thread_id: UUID
    status: LearningOrchestratorRunStatus
    intent: LearningIntent | None
    route: LearningOrchestratorRoute | None
    step_count: int
    maximum_steps: int
    created_at: datetime
    started_at: datetime | None
    waiting_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    failure_code: str | None

    @staticmethod
    def from_domain(run: LearningOrchestratorRun) -> LearningCoachRunResponse:
        return LearningCoachRunResponse(
            run_id=run.run_id, thread_id=run.thread_id, status=run.status, intent=run.intent, route=run.route,
            step_count=run.step_count, maximum_steps=run.maximum_steps, created_at=run.created_at,
            started_at=run.started_at, waiting_at=run.waiting_at, completed_at=run.completed_at,
            cancelled_at=run.cancelled_at, failure_code=run.failure_code,
        )


class LearningCoachEventResponse(ApiSchema):
    event_id: UUID
    event_type: LearningOrchestratorEventType
    sequence_number: int
    learner_message: str
    metadata: dict[str, Any]
    created_at: datetime

    @staticmethod
    def from_domain(event: LearningOrchestratorEvent) -> LearningCoachEventResponse:
        return LearningCoachEventResponse(
            event_id=event.event_id, event_type=event.event_type, sequence_number=event.sequence_number,
            learner_message=event.learner_message, metadata=event.metadata, created_at=event.created_at,
        )


class LearningCoachApprovalRequest(ApiSchema):
    proposal_id: UUID
    decision: LearnerApprovalDecision
    edited_parameters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_edit_requires_parameters(self) -> LearningCoachApprovalRequest:
        if self.decision == LearnerApprovalDecision.EDIT and not self.edited_parameters:
            raise ValueError("edited_parameters is required when decision is EDIT.")
        return self
