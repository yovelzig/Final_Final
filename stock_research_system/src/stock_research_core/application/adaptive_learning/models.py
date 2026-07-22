"""Application-level result models for the adaptive learning engine.

Composite views assembled from learning-domain and adaptive-domain
objects. Plain Pydantic models; no SQLAlchemy or other infrastructure
dependency here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from stock_research_core.domain.adaptive_learning.enums import DiagnosticSkillResult
from stock_research_core.domain.adaptive_learning.models import (
    AdaptiveDecision,
    DiagnosticAssessment,
    DiagnosticAssessmentItem,
    ExerciseAdaptiveProfile,
    LearningSession,
    LearningSessionActivity,
    SkillReviewSchedule,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAttempt,
    LearnerProfile,
    Lesson,
    Misconception,
    SkillMastery,
    UserProgress,
)
from stock_research_core.domain.models import DomainModel


class AdaptiveLearnerState(DomainModel):
    """A snapshot of everything the adaptive policy needs to know about a learner."""

    learner: LearnerProfile
    mastery: list[SkillMastery] = Field(default_factory=list)
    progress: list[UserProgress] = Field(default_factory=list)
    active_misconceptions: list[Misconception] = Field(default_factory=list)
    review_schedules: list[SkillReviewSchedule] = Field(default_factory=list)
    recent_attempts: list[ExerciseAttempt] = Field(default_factory=list)
    current_session: LearningSession | None = None


class ExerciseCandidate(DomainModel):
    """One exercise being evaluated by the adaptive policy for recommendation.

    `lesson_position` (the candidate's lesson's position within its
    module) is not in the original field list but is required by the
    documented deterministic tie-breaking rule ("lower lesson position"
    ranks before "lower exercise position") - `Exercise` itself only
    knows its own position, not its lesson's, so the service supplies
    this when building candidates.
    """

    exercise: Exercise
    adaptive_profile: ExerciseAdaptiveProfile
    lesson_position: int = Field(ge=0)
    skill_mastery_scores: dict[UUID, float] = Field(default_factory=dict)
    recent_attempt_count: int = Field(default=0, ge=0)
    recent_correct_rate: float | None = Field(default=None, ge=0, le=1)
    last_attempt_at: datetime | None = None
    is_overdue_review: bool = False
    has_active_misconception: bool = False
    prerequisites_satisfied: bool = True

    @model_validator(mode="after")
    def _validate_candidate(self) -> ExerciseCandidate:
        if any(not (0.0 <= score <= 1.0) for score in self.skill_mastery_scores.values()):
            raise ValueError("skill_mastery_scores values must be between 0 and 1")
        if self.exercise.exercise_id != self.adaptive_profile.exercise_id:
            raise ValueError("exercise and adaptive_profile IDs must match")
        return self


class ExerciseRecommendation(DomainModel):
    """The result of one `recommend_next` call: a decision plus its referenced content."""

    decision: AdaptiveDecision
    exercise: Exercise | None = None
    lesson: Lesson | None = None
    adaptive_profile: ExerciseAdaptiveProfile | None = None

    @model_validator(mode="after")
    def _validate_references(self) -> ExerciseRecommendation:
        if (
            self.exercise is not None
            and self.decision.recommended_exercise_id is not None
            and self.exercise.exercise_id != self.decision.recommended_exercise_id
        ):
            raise ValueError("exercise does not match decision.recommended_exercise_id")
        if (
            self.lesson is not None
            and self.decision.recommended_lesson_id is not None
            and self.lesson.lesson_id != self.decision.recommended_lesson_id
        ):
            raise ValueError("lesson does not match decision.recommended_lesson_id")
        if (
            self.adaptive_profile is not None
            and self.exercise is not None
            and self.adaptive_profile.exercise_id != self.exercise.exercise_id
        ):
            raise ValueError("adaptive_profile does not match exercise")
        return self


class DiagnosticSummary(DomainModel):
    """Per-skill results and starting recommendations for a diagnostic assessment."""

    assessment: DiagnosticAssessment
    items: list[DiagnosticAssessmentItem] = Field(default_factory=list)
    skill_results: dict[UUID, DiagnosticSkillResult] = Field(default_factory=dict)
    skill_scores: dict[UUID, float] = Field(default_factory=dict)
    recommended_starting_skill_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_summary(self) -> DiagnosticSummary:
        assessment_skill_ids = set(self.assessment.skill_ids)
        if any(not (0.0 <= score <= 1.0) for score in self.skill_scores.values()):
            raise ValueError("skill_scores values must be between 0 and 1")
        if not set(self.skill_results.keys()) <= assessment_skill_ids:
            raise ValueError("skill_results keys must belong to the assessment's skill_ids")
        if not set(self.skill_scores.keys()) <= assessment_skill_ids:
            raise ValueError("skill_scores keys must belong to the assessment's skill_ids")
        if not set(self.recommended_starting_skill_ids) <= assessment_skill_ids:
            raise ValueError(
                "recommended_starting_skill_ids must belong to the assessment's skill_ids"
            )
        return self


class SessionSummary(DomainModel):
    """A summary of one learning session's outcomes."""

    session: LearningSession
    activities: list[LearningSessionActivity] = Field(default_factory=list)
    mastery_changes: dict[UUID, float] = Field(default_factory=dict)
    reviews_scheduled: list[SkillReviewSchedule] = Field(default_factory=list)
