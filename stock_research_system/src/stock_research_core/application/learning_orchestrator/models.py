"""Action-specific parameter models and application-level result models
for the Phase 12 personalized learning orchestrator.

Every `LearningActionProposal.parameters` dict is validated against
exactly one of these models (selected by `action_type`) before a
proposal is ever persisted - arbitrary unvalidated JSON is never
accepted, and no model here (nor anywhere in this package) represents a
trade, a market-ingestion request, or an operational job.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from stock_research_core.domain.adaptive_learning.enums import LearningSessionType
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.models import LearningOrchestratorRun
from stock_research_core.domain.models import DomainModel


class ActionParameters(DomainModel):
    """Base class for every action-specific parameter model."""


class StartAdaptiveSessionAction(ActionParameters):
    session_type: LearningSessionType = LearningSessionType.DAILY_PRACTICE
    goal_minutes: int | None = Field(default=None, gt=0, le=180)


class StartDiagnosticAction(ActionParameters):
    skill_ids: list[UUID] | None = None
    maximum_items: int = Field(default=10, gt=0, le=50)


class OpenLessonAction(ActionParameters):
    lesson_id: UUID


class OpenScenarioAction(ActionParameters):
    scenario_id: UUID


class OpenPortfolioAction(ActionParameters):
    portfolio_id: UUID


class CreateTutorConversationAction(ActionParameters):
    context_type: TutorContextType
    lesson_id: UUID | None = None
    exercise_id: UUID | None = None
    scenario_id: UUID | None = None
    scenario_submission_id: UUID | None = None
    portfolio_id: UUID | None = None

    @model_validator(mode="after")
    def _validate_context_requires_matching_reference(self) -> CreateTutorConversationAction:
        required_by_context: dict[TutorContextType, str] = {
            TutorContextType.LESSON_HELP: "lesson_id",
            TutorContextType.EXERCISE_HELP: "exercise_id",
            TutorContextType.SCENARIO_BEFORE_DECISION: "scenario_id",
            TutorContextType.SCENARIO_AFTER_REVEAL: "scenario_submission_id",
            TutorContextType.PORTFOLIO_EXPLANATION: "portfolio_id",
        }
        required_field = required_by_context.get(self.context_type)
        if required_field is not None and getattr(self, required_field) is None:
            raise ValueError(f"context_type {self.context_type.value} requires {required_field}")
        return self


class LearningApprovalRequest(DomainModel):
    """The learner-supplied resume payload for an interrupted run."""

    proposal_id: UUID
    decision: str = Field(min_length=1, max_length=20)
    edited_parameters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_decision(self) -> LearningApprovalRequest:
        from stock_research_core.domain.learning_orchestrator.enums import LearnerApprovalDecision

        if self.decision not in {d.value for d in LearnerApprovalDecision}:
            raise ValueError(f"decision must be one of {[d.value for d in LearnerApprovalDecision]}")
        if self.decision == LearnerApprovalDecision.EDIT.value and self.edited_parameters is None:
            raise ValueError("decision=EDIT requires edited_parameters")
        return self


class RunCreationResult(DomainModel):
    run: LearningOrchestratorRun
    created: bool
    duplicate_of_run_id: UUID | None = None


class ProposedActionSummary(DomainModel):
    """The learner-safe shape of a proposal surfaced in a run/event
    response - never the full internal proposal row."""

    proposal_id: UUID
    action_type: str
    title: str
    description: str
    reason: str
    safe_parameters: dict[str, Any] = Field(default_factory=dict)
    expires_at: str | None = None


#: Maps each `LearningActionType` to its parameter model - the single
#: source of truth for "which parameters are valid for which action."
ACTION_PARAMETER_MODELS: dict[str, type[ActionParameters]] = {
    "START_ADAPTIVE_SESSION": StartAdaptiveSessionAction,
    "START_DIAGNOSTIC_ASSESSMENT": StartDiagnosticAction,
    "OPEN_LESSON": OpenLessonAction,
    "OPEN_SCENARIO": OpenScenarioAction,
    "OPEN_PORTFOLIO": OpenPortfolioAction,
    "CREATE_TUTOR_CONVERSATION": CreateTutorConversationAction,
}
