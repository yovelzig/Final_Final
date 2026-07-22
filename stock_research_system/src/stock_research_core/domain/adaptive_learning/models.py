"""Domain models for the FinQuest adaptive learning engine.

Technology-independent: no SQLAlchemy, FastAPI, machine-learning,
pandas, NumPy, SciPy, yfinance, LangGraph, n8n, or LLM/RAG library may
be imported here. This module does not import the learning domain
(`stock_research_core.domain.learning`) either - it only references
learner/skill/exercise/lesson IDs as plain UUIDs, keeping the adaptive
domain independently testable and decoupled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from stock_research_core.domain.adaptive_learning.enums import (
    AdaptiveDecisionStatus,
    DiagnosticAssessmentStatus,
    LearningSessionStatus,
    LearningSessionType,
    RecommendationReason,
    RecommendationType,
    ReviewScheduleStatus,
)
from stock_research_core.domain.models import DomainModel, utc_now

_NO_TARGET_REQUIRED_TYPES = frozenset(
    {RecommendationType.SESSION_COMPLETE, RecommendationType.NO_ELIGIBLE_CONTENT}
)


class ExerciseAdaptiveProfile(DomainModel):
    """Adaptive metadata for an existing `Exercise`.

    Deliberately does not duplicate the exercise's prompt, answer
    options, or skill relations - those live on `Exercise` itself.
    """

    profile_id: UUID = Field(default_factory=uuid4)
    exercise_id: UUID
    base_difficulty_score: float = Field(ge=0, le=1)
    estimated_seconds: int = Field(ge=10, le=3600)
    diagnostic_eligible: bool = False
    review_eligible: bool = False
    remediation_eligible: bool = False
    minimum_mastery_score: float | None = Field(default=None, ge=0, le=1)
    maximum_mastery_score: float | None = Field(default=None, ge=0, le=1)
    recommended_prerequisite_skill_ids: list[UUID] = Field(default_factory=list)
    policy_tags: list[str] = Field(default_factory=list)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("policy_tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        normalized = [tag.strip().lower() for tag in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate policy_tags are not allowed")
        return normalized

    @model_validator(mode="after")
    def _validate_profile(self) -> ExerciseAdaptiveProfile:
        if (
            self.minimum_mastery_score is not None
            and self.maximum_mastery_score is not None
            and self.minimum_mastery_score > self.maximum_mastery_score
        ):
            raise ValueError("minimum_mastery_score cannot exceed maximum_mastery_score")
        if len(set(self.recommended_prerequisite_skill_ids)) != len(
            self.recommended_prerequisite_skill_ids
        ):
            raise ValueError("duplicate recommended_prerequisite_skill_ids are not allowed")
        return self


class LearningSession(DomainModel):
    """One learner's bounded practice session (e.g. today's daily practice)."""

    session_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    session_type: LearningSessionType = LearningSessionType.DAILY_PRACTICE
    status: LearningSessionStatus = LearningSessionStatus.STARTED
    goal_minutes: int = Field(ge=5, le=180)
    started_at: datetime = Field(default_factory=utc_now)
    last_activity_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    abandoned_at: datetime | None = None
    recommended_item_count: int = Field(default=0, ge=0)
    completed_item_count: int = Field(default=0, ge=0)
    correct_item_count: int = Field(default=0, ge=0)
    total_score: float = Field(default=0.0, ge=0)
    maximum_score: float = Field(default=0.0, ge=0)
    policy_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_session(self) -> LearningSession:
        if self.correct_item_count > self.completed_item_count:
            raise ValueError("correct_item_count cannot exceed completed_item_count")
        if (
            self.session_type != LearningSessionType.FREE_PRACTICE
            and self.completed_item_count > self.recommended_item_count
        ):
            raise ValueError(
                "completed_item_count cannot exceed recommended_item_count unless "
                "session_type is FREE_PRACTICE"
            )
        if self.total_score > self.maximum_score:
            raise ValueError("total_score cannot exceed maximum_score")
        if self.status == LearningSessionStatus.COMPLETED and self.abandoned_at is not None:
            raise ValueError("a completed session cannot also be abandoned")
        if self.status == LearningSessionStatus.COMPLETED and self.completed_at is None:
            raise ValueError("a completed session must have completed_at")
        if self.status == LearningSessionStatus.ABANDONED and self.abandoned_at is None:
            raise ValueError("an abandoned session must have abandoned_at")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.abandoned_at is not None and self.abandoned_at < self.started_at:
            raise ValueError("abandoned_at cannot precede started_at")
        return self


class LearningSessionActivity(DomainModel):
    """One recommended-and-tracked exercise slot within a `LearningSession`."""

    activity_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    learner_id: UUID
    exercise_id: UUID
    attempt_id: UUID | None = None
    decision_id: UUID
    position: int = Field(gt=0)
    recommended_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    skipped_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_activity(self) -> LearningSessionActivity:
        if self.completed_at is not None and self.skipped_at is not None:
            raise ValueError("an activity cannot be both completed and skipped")
        if self.completed_at is not None and self.completed_at < self.recommended_at:
            raise ValueError("completed_at cannot precede recommended_at")
        if self.skipped_at is not None and self.skipped_at < self.recommended_at:
            raise ValueError("skipped_at cannot precede recommended_at")
        if self.started_at is not None and self.started_at < self.recommended_at:
            raise ValueError("started_at cannot precede recommended_at")
        return self


class DiagnosticAssessment(DomainModel):
    """A diagnostic assessment covering one or more skills."""

    assessment_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    status: DiagnosticAssessmentStatus = DiagnosticAssessmentStatus.CREATED
    skill_ids: list[UUID] = Field(min_length=1)
    maximum_items: int = Field(ge=1, le=100)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    policy_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_assessment(self) -> DiagnosticAssessment:
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("duplicate skill_ids are not allowed")
        if (
            self.status
            in (DiagnosticAssessmentStatus.IN_PROGRESS, DiagnosticAssessmentStatus.COMPLETED)
            and self.started_at is None
        ):
            raise ValueError("in-progress or completed assessments require started_at")
        if self.status == DiagnosticAssessmentStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed assessments require completed_at")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot precede started_at")
        return self


class DiagnosticAssessmentItem(DomainModel):
    """One exercise selected as part of a `DiagnosticAssessment`."""

    item_id: UUID = Field(default_factory=uuid4)
    assessment_id: UUID
    exercise_id: UUID
    skill_ids: list[UUID] = Field(min_length=1)
    position: int = Field(gt=0)
    attempt_id: UUID | None = None
    selected_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    normalized_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _validate_item(self) -> DiagnosticAssessmentItem:
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("duplicate skill_ids are not allowed")
        if self.completed_at is not None:
            if self.attempt_id is None or self.normalized_score is None:
                raise ValueError(
                    "a completed diagnostic item requires attempt_id and normalized_score"
                )
            if self.completed_at < self.selected_at:
                raise ValueError("completed_at cannot precede selected_at")
        return self


class SkillReviewSchedule(DomainModel):
    """A learner's spaced-repetition schedule for one skill."""

    schedule_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    skill_id: UUID
    status: ReviewScheduleStatus = ReviewScheduleStatus.NOT_SCHEDULED
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    review_interval_days: int = Field(ge=0)
    successful_review_count: int = Field(default=0, ge=0)
    failed_review_count: int = Field(default=0, ge=0)
    consecutive_successful_reviews: int = Field(default=0, ge=0)
    ease_factor: float = Field(ge=1.0, le=3.0)
    calculation_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_schedule(self) -> SkillReviewSchedule:
        if (
            self.status
            in (ReviewScheduleStatus.SCHEDULED, ReviewScheduleStatus.DUE, ReviewScheduleStatus.OVERDUE)
            and self.next_review_at is None
        ):
            raise ValueError("scheduled, due, and overdue statuses require next_review_at")
        if (
            self.last_reviewed_at is not None
            and self.next_review_at is not None
            and self.next_review_at < self.last_reviewed_at
        ):
            raise ValueError("next_review_at cannot precede last_reviewed_at")
        return self


class AdaptiveDecision(DomainModel):
    """One auditable adaptive-engine recommendation.

    `input_snapshot` must hold only sanitized, JSON-safe decision
    inputs (e.g. component scores) - never a full learner/exercise
    object or any credential.
    """

    decision_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    session_id: UUID | None = None
    recommendation_type: RecommendationType
    status: AdaptiveDecisionStatus = AdaptiveDecisionStatus.GENERATED
    recommended_exercise_id: UUID | None = None
    recommended_lesson_id: UUID | None = None
    target_skill_ids: list[UUID] = Field(default_factory=list)
    reason_codes: list[RecommendationReason] = Field(default_factory=list)
    priority_score: float = Field(ge=0, le=1)
    recommended_difficulty_score: float | None = Field(default=None, ge=0, le=1)
    policy_version: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=utc_now)
    accepted_at: datetime | None = None
    completed_at: datetime | None = None
    skipped_at: datetime | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_decision(self) -> AdaptiveDecision:
        if (
            self.recommendation_type not in _NO_TARGET_REQUIRED_TYPES
            and self.recommended_exercise_id is None
            and self.recommended_lesson_id is None
        ):
            raise ValueError(
                "at least one of recommended_exercise_id or recommended_lesson_id is "
                "required unless recommendation_type is SESSION_COMPLETE or NO_ELIGIBLE_CONTENT"
            )
        if len(set(self.target_skill_ids)) != len(self.target_skill_ids):
            raise ValueError("duplicate target_skill_ids are not allowed")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("duplicate reason_codes are not allowed")
        if self.status == AdaptiveDecisionStatus.ACCEPTED and self.accepted_at is None:
            raise ValueError("accepted status requires accepted_at")
        if self.status == AdaptiveDecisionStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed status requires completed_at")
        if self.status == AdaptiveDecisionStatus.SKIPPED and self.skipped_at is None:
            raise ValueError("skipped status requires skipped_at")
        if self.completed_at is not None and self.skipped_at is not None:
            raise ValueError("a decision cannot be both completed and skipped")
        return self
