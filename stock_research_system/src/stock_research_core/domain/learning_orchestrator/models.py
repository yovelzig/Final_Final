"""Domain models for the FinQuest personalized learning orchestrator
(Phase 12: LangGraph-based interactive learning coach).

This module has no knowledge of any infrastructure (databases, LangGraph,
queues, HTTP frameworks, etc.) - the same rule every other `domain/*`
package follows. These models are the *public, auditable* FinQuest
product state; the LangGraph checkpoint (orchestration runtime state) is
a separate, infrastructure-owned concern - see
`infrastructure.learning_orchestrator.postgres_checkpointer`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import (
    IntentClassificationMethod,
    LearnerApprovalDecision,
    LearningActionProposalStatus,
    LearningActionType,
    LearningIntent,
    LearningOrchestratorEventType,
    LearningOrchestratorRoute,
    LearningOrchestratorRunStatus,
    LearningOrchestratorThreadStatus,
)
from stock_research_core.domain.models import DomainModel, utc_now
from stock_research_core.domain.operations.sanitization import (
    contains_credential_leak,
    contains_traceback,
    find_sensitive_keys,
)

#: Keys `IntentClassification.context_references` is allowed to carry -
#: never an arbitrary caller-supplied key.
ALLOWED_CONTEXT_REFERENCE_KEYS = frozenset(
    {
        "lesson_id", "exercise_id", "scenario_id", "scenario_submission_id", "portfolio_id",
        "conversation_id", "decision_id", "session_id", "assessment_id",
    }
)

_MAX_VECTOR_SHAPED_LIST_LENGTH = 50


def _reject_sensitive_mapping(data: dict[str, Any] | None, *, field_name: str) -> None:
    if data is None:
        return
    sensitive_paths = find_sensitive_keys(data)
    if sensitive_paths:
        raise ValueError(f"{field_name} must not contain sensitive fields (found: {', '.join(sensitive_paths)})")
    if contains_traceback(data):
        raise ValueError(f"{field_name} must not contain a raw traceback")


def _reject_vector_shaped_values(data: dict[str, Any], *, field_name: str) -> None:
    for key, value in data.items():
        if isinstance(value, list) and len(value) > _MAX_VECTOR_SHAPED_LIST_LENGTH:
            if all(isinstance(item, (int, float)) for item in value):
                raise ValueError(f"{field_name}.{key} looks like a raw embedding vector, which must never be stored")


def _validate_english_bounded_text(value: str, *, field_name: str) -> str:
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be plain English (ASCII) text") from exc
    if contains_traceback(value) or contains_credential_leak(value):
        raise ValueError(f"{field_name} must not contain a traceback or credential-shaped content")
    return value


class LearningOrchestratorThread(DomainModel):
    """A durable, learner-owned coaching thread. Maps 1:1 to one LangGraph
    `thread_id` - never contains checkpoint bytes or graph state itself."""

    thread_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    status: LearningOrchestratorThreadStatus = LearningOrchestratorThreadStatus.ACTIVE

    title: str = Field(min_length=1, max_length=200)
    current_context_type: TutorContextType = TutorContextType.GENERAL_EDUCATION
    linked_tutor_conversation_id: UUID | None = None

    graph_name: str = Field(min_length=1, max_length=100)
    graph_version: str = Field(min_length=1, max_length=50)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_closed_requires_timestamp(self) -> LearningOrchestratorThread:
        if self.status == LearningOrchestratorThreadStatus.CLOSED and self.closed_at is None:
            raise ValueError("a CLOSED thread requires closed_at")
        return self


class LearningOrchestratorRun(DomainModel):
    """One durable execution of the learning-coach graph against a thread."""

    run_id: UUID = Field(default_factory=uuid4)
    thread_id: UUID
    learner_id: UUID

    status: LearningOrchestratorRunStatus = LearningOrchestratorRunStatus.CREATED

    input_message_id: UUID | None = None
    output_tutor_answer_id: UUID | None = None

    intent: LearningIntent | None = None
    route: LearningOrchestratorRoute | None = None

    idempotency_key: str = Field(min_length=1, max_length=200)
    correlation_id: str = Field(min_length=1, max_length=128)

    step_count: int = Field(default=0, ge=0)
    maximum_steps: int = Field(default=30, ge=1, le=100)

    started_at: datetime | None = None
    waiting_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None

    failure_code: str | None = Field(default=None, max_length=100)
    failure_message: str | None = Field(default=None, max_length=1000)

    graph_version: str = Field(min_length=1, max_length=50)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("failure_message")
    @classmethod
    def _validate_failure_message(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if contains_traceback(value):
            raise ValueError("failure_message must not contain a raw traceback")
        if contains_credential_leak(value):
            raise ValueError("failure_message must not contain credential-shaped content")
        return value

    @model_validator(mode="after")
    def _validate_step_count(self) -> LearningOrchestratorRun:
        if self.step_count > self.maximum_steps:
            raise ValueError("step_count cannot exceed maximum_steps")
        return self

    @model_validator(mode="after")
    def _validate_lifecycle_timestamps(self) -> LearningOrchestratorRun:
        if self.status == LearningOrchestratorRunStatus.RUNNING and self.started_at is None:
            raise ValueError("a RUNNING run requires started_at")
        if self.status == LearningOrchestratorRunStatus.WAITING_FOR_LEARNER and self.waiting_at is None:
            raise ValueError("a WAITING_FOR_LEARNER run requires waiting_at")
        if self.status == LearningOrchestratorRunStatus.SUCCEEDED and self.completed_at is None:
            raise ValueError("a SUCCEEDED run requires completed_at")
        if self.status == LearningOrchestratorRunStatus.CANCELLED and self.cancelled_at is None:
            raise ValueError("a CANCELLED run requires cancelled_at")
        if self.status == LearningOrchestratorRunStatus.FAILED:
            if self.completed_at is None:
                raise ValueError("a FAILED run requires completed_at")
            if not self.failure_code or not self.failure_message:
                raise ValueError("a FAILED run requires a sanitized failure_code and failure_message")
        return self


class LearningOrchestratorEvent(DomainModel):
    """An immutable, learner-safe audit event for one orchestrator run."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, protected_namespaces=(), frozen=True,
    )

    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    thread_id: UUID
    event_type: LearningOrchestratorEventType

    sequence_number: int = Field(gt=0)
    learner_message: str = Field(min_length=1, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("learner_message")
    @classmethod
    def _validate_learner_message(cls, value: str) -> str:
        return _validate_english_bounded_text(value, field_name="learner_message")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="metadata")
        _reject_vector_shaped_values(value, field_name="metadata")
        return value


class LearningActionProposal(DomainModel):
    """A proposed, explicitly-approvable educational action - never a
    trade, never an operational job, never an admin action (see
    `LearningActionType` for the closed allow-list)."""

    proposal_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    thread_id: UUID
    learner_id: UUID

    action_type: LearningActionType
    status: LearningActionProposalStatus = LearningActionProposalStatus.PROPOSED

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)

    parameters: dict[str, Any] = Field(default_factory=dict)
    result_reference: dict[str, Any] | None = None

    approval_decision: LearnerApprovalDecision | None = None
    approval_payload: dict[str, Any] | None = None

    idempotency_key: str = Field(min_length=1, max_length=200)

    proposed_at: datetime = Field(default_factory=utc_now)
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    executed_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        return _validate_english_bounded_text(value, field_name="title")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _validate_english_bounded_text(value, field_name="description")

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _validate_english_bounded_text(value, field_name="reason")

    @field_validator("parameters")
    @classmethod
    def _validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="parameters")
        return value

    @field_validator("result_reference")
    @classmethod
    def _validate_result_reference(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        _reject_sensitive_mapping(value, field_name="result_reference")
        return value

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> LearningActionProposal:
        if self.status == LearningActionProposalStatus.APPROVED and self.approved_at is None:
            raise ValueError("an APPROVED proposal requires approved_at")
        if self.status == LearningActionProposalStatus.REJECTED and self.rejected_at is None:
            raise ValueError("a REJECTED proposal requires rejected_at")
        if self.status == LearningActionProposalStatus.SUCCEEDED:
            if self.result_reference is None:
                raise ValueError("a SUCCEEDED proposal requires a result_reference")
            if self.completed_at is None:
                raise ValueError("a SUCCEEDED proposal requires completed_at")
        return self


class IntentClassification(DomainModel):
    """The deterministic (or bounded, single-call model-assisted)
    classification of one learner message."""

    intent: LearningIntent
    confidence: float = Field(ge=0, le=1)
    method: IntentClassificationMethod

    context_references: dict[str, UUID] = Field(default_factory=dict)
    matched_rule_codes: list[str] = Field(default_factory=list)

    requires_grounded_tutor: bool = False
    requires_action_approval: bool = False

    classifier_version: str = Field(min_length=1, max_length=50)

    @field_validator("matched_rule_codes")
    @classmethod
    def _validate_unique_rule_codes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("matched_rule_codes must not contain duplicates")
        return value

    @field_validator("context_references")
    @classmethod
    def _validate_context_reference_keys(cls, value: dict[str, UUID]) -> dict[str, UUID]:
        disallowed = set(value.keys()) - ALLOWED_CONTEXT_REFERENCE_KEYS
        if disallowed:
            raise ValueError(f"context_references contains disallowed keys: {sorted(disallowed)}")
        return value
