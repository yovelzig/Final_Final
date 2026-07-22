"""Request/response DTOs for `/api/v1/learners/*`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    MasteryLevel,
    MisconceptionStatus,
    ProgressStatus,
)
from stock_research_core.domain.learning.models import LearnerProfile, Misconception, SkillMastery, UserProgress


class LearnerProfileResponse(ApiSchema):
    learner_id: UUID
    display_name: str
    preferred_language: str
    financial_experience_level: DifficultyLevel
    daily_goal_minutes: int
    active: bool
    created_at: datetime

    @staticmethod
    def from_domain(learner: LearnerProfile) -> LearnerProfileResponse:
        return LearnerProfileResponse(
            learner_id=learner.learner_id, display_name=learner.display_name,
            preferred_language=learner.preferred_language,
            financial_experience_level=learner.financial_experience_level,
            daily_goal_minutes=learner.daily_goal_minutes, active=learner.active,
            created_at=learner.created_at,
        )


class LearnerUpdateRequest(ApiSchema):
    """PATCH body: display name, daily goal, and preferred language only.
    Role and account status can never be changed through this endpoint."""

    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    daily_goal_minutes: int | None = Field(default=None, ge=5, le=180)
    preferred_language: str | None = Field(default=None, min_length=2, max_length=10)


class SkillMasteryResponse(ApiSchema):
    skill_id: UUID
    mastery_score: float
    mastery_level: MasteryLevel
    correct_attempts: int
    total_attempts: int
    last_practiced_at: datetime | None
    next_review_at: datetime | None

    @staticmethod
    def from_domain(mastery: SkillMastery) -> SkillMasteryResponse:
        return SkillMasteryResponse(
            skill_id=mastery.skill_id, mastery_score=mastery.mastery_score, mastery_level=mastery.mastery_level,
            correct_attempts=mastery.correct_attempts, total_attempts=mastery.total_attempts,
            last_practiced_at=mastery.last_practiced_at, next_review_at=mastery.next_review_at,
        )


class ProgressResponse(ApiSchema):
    progress_id: UUID
    path_id: UUID | None
    module_id: UUID | None
    lesson_id: UUID | None
    status: ProgressStatus
    completion_percentage: float
    best_score: float | None
    attempt_count: int
    completed_at: datetime | None

    @staticmethod
    def from_domain(progress: UserProgress) -> ProgressResponse:
        return ProgressResponse(
            progress_id=progress.progress_id, path_id=progress.path_id, module_id=progress.module_id,
            lesson_id=progress.lesson_id, status=progress.status,
            completion_percentage=progress.completion_percentage, best_score=progress.best_score,
            attempt_count=progress.attempt_count, completed_at=progress.completed_at,
        )


class MisconceptionResponse(ApiSchema):
    misconception_id: UUID
    skill_id: UUID
    description: str
    status: MisconceptionStatus
    confidence_score: float
    first_detected_at: datetime
    resolved_at: datetime | None

    @staticmethod
    def from_domain(misconception: Misconception) -> MisconceptionResponse:
        return MisconceptionResponse(
            misconception_id=misconception.misconception_id, skill_id=misconception.skill_id,
            description=misconception.description, status=misconception.status,
            confidence_score=misconception.confidence_score, first_detected_at=misconception.first_detected_at,
            resolved_at=misconception.resolved_at,
        )


class DashboardResponse(ApiSchema):
    learner: LearnerProfileResponse
    active_path_id: UUID | None
    current_lesson_id: UUID | None
    completed_lessons: int
    total_lessons: int
    current_streak_days: int
    total_xp: int
    skill_mastery: list[SkillMasteryResponse]
    active_misconceptions: list[MisconceptionResponse]
