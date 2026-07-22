"""Request/response DTOs for `/api/v1/adaptive` sessions, decisions, and diagnostics.

`AdaptiveDecisionResponse` never carries `input_snapshot` - it is an
internal policy-debugging artifact, not learner-facing data.
`ExerciseRecommendationResponse` reuses the same learner-safe
`ExerciseResponse` from the curriculum schemas, so a recommended
exercise never leaks `is_correct`/`feedback`/`explanation` either.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.api.schemas.curriculum import AttemptResponse, ExerciseResponse, LessonResponse
from stock_research_core.domain.adaptive_learning.enums import (
    AdaptiveDecisionStatus,
    DiagnosticAssessmentStatus,
    DiagnosticSkillResult,
    LearningSessionStatus,
    LearningSessionType,
    RecommendationReason,
    RecommendationType,
    ReviewScheduleStatus,
)
from stock_research_core.domain.adaptive_learning.models import (
    AdaptiveDecision,
    DiagnosticAssessment,
    DiagnosticAssessmentItem,
    LearningSession,
    LearningSessionActivity,
    SkillReviewSchedule,
)
from stock_research_core.domain.learning.enums import ConfidenceLevel


class StartSessionRequest(ApiSchema):
    session_type: LearningSessionType = LearningSessionType.DAILY_PRACTICE
    goal_minutes: int | None = Field(default=None, ge=5, le=180)


class LearningSessionResponse(ApiSchema):
    session_id: UUID
    session_type: LearningSessionType
    status: LearningSessionStatus
    goal_minutes: int
    started_at: datetime
    last_activity_at: datetime
    completed_at: datetime | None
    recommended_item_count: int
    completed_item_count: int
    correct_item_count: int
    total_score: float
    maximum_score: float

    @staticmethod
    def from_domain(session: LearningSession) -> LearningSessionResponse:
        return LearningSessionResponse(
            session_id=session.session_id, session_type=session.session_type, status=session.status,
            goal_minutes=session.goal_minutes, started_at=session.started_at,
            last_activity_at=session.last_activity_at, completed_at=session.completed_at,
            recommended_item_count=session.recommended_item_count,
            completed_item_count=session.completed_item_count, correct_item_count=session.correct_item_count,
            total_score=session.total_score, maximum_score=session.maximum_score,
        )


class SessionActivityResponse(ApiSchema):
    activity_id: UUID
    session_id: UUID
    exercise_id: UUID
    attempt_id: UUID | None
    decision_id: UUID
    position: int
    recommended_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    skipped_at: datetime | None

    @staticmethod
    def from_domain(activity: LearningSessionActivity) -> SessionActivityResponse:
        return SessionActivityResponse(
            activity_id=activity.activity_id, session_id=activity.session_id,
            exercise_id=activity.exercise_id, attempt_id=activity.attempt_id,
            decision_id=activity.decision_id, position=activity.position,
            recommended_at=activity.recommended_at, started_at=activity.started_at,
            completed_at=activity.completed_at, skipped_at=activity.skipped_at,
        )


class ReviewScheduleResponse(ApiSchema):
    schedule_id: UUID
    skill_id: UUID
    status: ReviewScheduleStatus
    last_reviewed_at: datetime | None
    next_review_at: datetime | None
    review_interval_days: int
    successful_review_count: int
    failed_review_count: int
    consecutive_successful_reviews: int

    @staticmethod
    def from_domain(schedule: SkillReviewSchedule) -> ReviewScheduleResponse:
        return ReviewScheduleResponse(
            schedule_id=schedule.schedule_id, skill_id=schedule.skill_id, status=schedule.status,
            last_reviewed_at=schedule.last_reviewed_at, next_review_at=schedule.next_review_at,
            review_interval_days=schedule.review_interval_days,
            successful_review_count=schedule.successful_review_count,
            failed_review_count=schedule.failed_review_count,
            consecutive_successful_reviews=schedule.consecutive_successful_reviews,
        )


class SessionSummaryResponse(ApiSchema):
    session: LearningSessionResponse
    activities: list[SessionActivityResponse]
    mastery_changes: dict[UUID, float]
    reviews_scheduled: list[ReviewScheduleResponse]


class AdaptiveDecisionResponse(ApiSchema):
    """Never carries `input_snapshot` - that's an internal policy-debugging artifact."""

    decision_id: UUID
    session_id: UUID | None
    recommendation_type: RecommendationType
    status: AdaptiveDecisionStatus
    recommended_exercise_id: UUID | None
    recommended_lesson_id: UUID | None
    target_skill_ids: list[UUID]
    reason_codes: list[RecommendationReason]
    priority_score: float
    recommended_difficulty_score: float | None
    explanation: str
    generated_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    skipped_at: datetime | None

    @staticmethod
    def from_domain(decision: AdaptiveDecision) -> AdaptiveDecisionResponse:
        return AdaptiveDecisionResponse(
            decision_id=decision.decision_id, session_id=decision.session_id,
            recommendation_type=decision.recommendation_type, status=decision.status,
            recommended_exercise_id=decision.recommended_exercise_id,
            recommended_lesson_id=decision.recommended_lesson_id,
            target_skill_ids=list(decision.target_skill_ids), reason_codes=list(decision.reason_codes),
            priority_score=decision.priority_score,
            recommended_difficulty_score=decision.recommended_difficulty_score,
            explanation=decision.explanation, generated_at=decision.generated_at,
            accepted_at=decision.accepted_at, completed_at=decision.completed_at,
            skipped_at=decision.skipped_at,
        )


class ExerciseRecommendationResponse(ApiSchema):
    decision: AdaptiveDecisionResponse
    exercise: ExerciseResponse | None
    lesson: LessonResponse | None


class StartRecommendedExerciseRequest(ApiSchema):
    confidence_level: ConfidenceLevel | None = None


class SubmitDecisionAnswerRequest(ApiSchema):
    selected_option_ids: list[UUID] = Field(default_factory=list)
    numeric_answer: float | None = None
    text_answer: str | None = Field(default=None, max_length=5000)
    ordered_option_ids: list[UUID] = Field(default_factory=list)


class StartDiagnosticRequest(ApiSchema):
    skill_ids: list[UUID] | None = None
    maximum_items: int = Field(default=10, ge=1, le=100)


class DiagnosticItemResponse(ApiSchema):
    item_id: UUID
    assessment_id: UUID
    exercise_id: UUID
    skill_ids: list[UUID]
    position: int
    attempt_id: UUID | None
    selected_at: datetime
    completed_at: datetime | None
    normalized_score: float | None

    @staticmethod
    def from_domain(item: DiagnosticAssessmentItem) -> DiagnosticItemResponse:
        return DiagnosticItemResponse(
            item_id=item.item_id, assessment_id=item.assessment_id, exercise_id=item.exercise_id,
            skill_ids=list(item.skill_ids), position=item.position, attempt_id=item.attempt_id,
            selected_at=item.selected_at, completed_at=item.completed_at,
            normalized_score=item.normalized_score,
        )


class DiagnosticAssessmentResponse(ApiSchema):
    assessment_id: UUID
    status: DiagnosticAssessmentStatus
    skill_ids: list[UUID]
    maximum_items: int
    started_at: datetime | None
    completed_at: datetime | None

    @staticmethod
    def from_domain(assessment: DiagnosticAssessment) -> DiagnosticAssessmentResponse:
        return DiagnosticAssessmentResponse(
            assessment_id=assessment.assessment_id, status=assessment.status,
            skill_ids=list(assessment.skill_ids), maximum_items=assessment.maximum_items,
            started_at=assessment.started_at, completed_at=assessment.completed_at,
        )


class DiagnosticSummaryResponse(ApiSchema):
    assessment: DiagnosticAssessmentResponse
    items: list[DiagnosticItemResponse]
    skill_results: dict[UUID, DiagnosticSkillResult]
    skill_scores: dict[UUID, float]
    recommended_starting_skill_ids: list[UUID]


class DiagnosticStatusResponse(ApiSchema):
    """A plain point-in-time view of a diagnostic (no re-derived skill summary)."""

    assessment: DiagnosticAssessmentResponse
    items: list[DiagnosticItemResponse]


class StartDiagnosticItemRequest(ApiSchema):
    confidence_level: ConfidenceLevel | None = None


class SubmitDiagnosticResultRequest(ApiSchema):
    selected_option_ids: list[UUID] = Field(default_factory=list)
    numeric_answer: float | None = None
    text_answer: str | None = Field(default=None, max_length=5000)
    ordered_option_ids: list[UUID] = Field(default_factory=list)
