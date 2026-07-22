"""Domain models for the FinQuest learning platform.

These models are technology-independent: no SQLAlchemy, FastAPI,
pandas, yfinance, LangGraph, n8n, or LLM/RAG library may be imported
here. They intentionally do not import anything from the market-data
domain (`stock_research_core.domain.models`) except the shared
`DomainModel` base class and `utc_now` helper, which are pure Pydantic
configuration, not market-data concepts - the learning domain and the
market-data domain stay conceptually separate. A future market-scenario
feature may *reference* a `Security` by ID from its own model, but
ordinary lessons and exercises never require one.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from stock_research_core.domain.learning.enums import (
    AttemptStatus,
    ConfidenceLevel,
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
    MasteryLevel,
    MisconceptionStatus,
    ProgressStatus,
)
from stock_research_core.domain.models import DomainModel, utc_now

_SKILL_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _normalize_code(value: str) -> str:
    """Normalize a human-entered code into a stable, URL-safe slug."""
    return value.strip().lower().replace(" ", "-")


class LearnerProfile(DomainModel):
    """A learner using the platform. Never stores credentials directly."""

    learner_id: UUID = Field(default_factory=uuid4)
    display_name: str = Field(min_length=1, max_length=150)
    preferred_language: str = Field(default="en", min_length=2, max_length=10)
    financial_experience_level: DifficultyLevel = DifficultyLevel.BEGINNER
    daily_goal_minutes: int = Field(default=10, ge=5, le=180)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    active: bool = True

    @field_validator("preferred_language")
    @classmethod
    def _normalize_language(cls, value: str) -> str:
        return value.strip().lower()


class Skill(DomainModel):
    """A discrete, testable financial-literacy skill."""

    skill_id: UUID = Field(default_factory=uuid4)
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    category: FinancialSkillCategory
    difficulty: DifficultyLevel
    prerequisite_skill_ids: list[UUID] = Field(default_factory=list)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not _SKILL_CODE_PATTERN.fullmatch(value):
            raise ValueError(
                "code must be uppercase snake_case (e.g. 'PORTFOLIO_CONSTRUCTION')"
            )
        return value

    @model_validator(mode="after")
    def _validate_prerequisites(self) -> Skill:
        if self.skill_id in self.prerequisite_skill_ids:
            raise ValueError("a skill cannot list itself as a prerequisite")
        if len(set(self.prerequisite_skill_ids)) != len(self.prerequisite_skill_ids):
            raise ValueError("duplicate prerequisite_skill_ids are not allowed")
        return self


class LearningPath(DomainModel):
    """The top level of the curriculum hierarchy: path -> module -> lesson."""

    path_id: UUID = Field(default_factory=uuid4)
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    difficulty: DifficultyLevel
    position: int = Field(ge=0)
    estimated_minutes: int = Field(gt=0)
    published: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("code")
    @classmethod
    def _normalize_code_field(cls, value: str) -> str:
        return _normalize_code(value)


class LearningModule(DomainModel):
    """A themed group of lessons within a `LearningPath`."""

    module_id: UUID = Field(default_factory=uuid4)
    path_id: UUID
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    position: int = Field(ge=0)
    estimated_minutes: int = Field(gt=0)
    published: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("code")
    @classmethod
    def _normalize_code_field(cls, value: str) -> str:
        return _normalize_code(value)


class Lesson(DomainModel):
    """A single short lesson within a `LearningModule`."""

    lesson_id: UUID = Field(default_factory=uuid4)
    module_id: UUID
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    content_markdown: str = Field(min_length=1)
    difficulty: DifficultyLevel
    status: LessonStatus = LessonStatus.DRAFT
    position: int = Field(ge=0)
    estimated_minutes: int = Field(gt=0)
    primary_skill_id: UUID
    secondary_skill_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("code")
    @classmethod
    def _normalize_code_field(cls, value: str) -> str:
        return _normalize_code(value)

    @model_validator(mode="after")
    def _validate_skills(self) -> Lesson:
        if self.primary_skill_id in self.secondary_skill_ids:
            raise ValueError("primary_skill_id cannot also appear in secondary_skill_ids")
        if len(set(self.secondary_skill_ids)) != len(self.secondary_skill_ids):
            raise ValueError("duplicate secondary_skill_ids are not allowed")
        return self


class Exercise(DomainModel):
    """A gradeable exercise attached to a `Lesson`.

    `configuration` may hold exercise-type-specific grading parameters
    (e.g. numeric tolerance for `NUMERIC_INPUT`), but core relationships
    (which skills an exercise practices, which options it offers) are
    modeled as real relations, not JSON.
    """

    exercise_id: UUID = Field(default_factory=uuid4)
    lesson_id: UUID
    exercise_type: ExerciseType
    prompt: str = Field(min_length=1, max_length=3000)
    explanation: str = Field(min_length=1, max_length=3000)
    difficulty: DifficultyLevel
    position: int = Field(ge=0)
    skill_ids: list[UUID] = Field(min_length=1)
    maximum_score: float = Field(gt=0)
    passing_score: float = Field(ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_scores(self) -> Exercise:
        if self.passing_score > self.maximum_score:
            raise ValueError("passing_score cannot exceed maximum_score")
        return self


class ExerciseOption(DomainModel):
    """One answer option for exercise types that support options."""

    option_id: UUID = Field(default_factory=uuid4)
    exercise_id: UUID
    option_key: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=2000)
    position: int = Field(ge=0)
    is_correct: bool = False
    feedback: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExerciseAttempt(DomainModel):
    """One learner's attempt at an exercise."""

    attempt_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    exercise_id: UUID
    status: AttemptStatus = AttemptStatus.STARTED
    started_at: datetime = Field(default_factory=utc_now)
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    score: float | None = None
    maximum_score: float = Field(gt=0)
    is_correct: bool | None = None
    confidence_level: ConfidenceLevel | None = None
    response_time_seconds: int | None = Field(default=None, ge=0)
    attempt_number: int = Field(gt=0)
    grading_version: str | None = Field(default=None, max_length=50)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_attempt(self) -> ExerciseAttempt:
        if self.score is not None and not (0 <= self.score <= self.maximum_score):
            raise ValueError("score must be between 0 and maximum_score")
        if (
            self.status in (AttemptStatus.SUBMITTED, AttemptStatus.GRADED)
            and self.submitted_at is None
        ):
            raise ValueError("a submitted or graded attempt must have submitted_at")
        if self.status == AttemptStatus.GRADED and (
            self.graded_at is None or self.score is None or self.is_correct is None
        ):
            raise ValueError("a graded attempt must have graded_at, score, and is_correct")
        if self.submitted_at is not None and self.submitted_at < self.started_at:
            raise ValueError("submitted_at cannot precede started_at")
        if (
            self.graded_at is not None
            and self.submitted_at is not None
            and self.graded_at < self.submitted_at
        ):
            raise ValueError("graded_at cannot precede submitted_at")
        return self


class ExerciseAnswer(DomainModel):
    """A learner's validated, submitted answer. Does not judge correctness."""

    answer_id: UUID = Field(default_factory=uuid4)
    attempt_id: UUID
    selected_option_ids: list[UUID] = Field(default_factory=list)
    numeric_answer: float | None = None
    text_answer: str | None = None
    ordered_option_ids: list[UUID] = Field(default_factory=list)
    submitted_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_answer(self) -> ExerciseAnswer:
        if not (
            self.selected_option_ids
            or self.numeric_answer is not None
            or self.text_answer
            or self.ordered_option_ids
        ):
            raise ValueError("at least one answer representation must be supplied")
        if len(set(self.selected_option_ids)) != len(self.selected_option_ids):
            raise ValueError("duplicate selected_option_ids are not allowed")
        if len(set(self.ordered_option_ids)) != len(self.ordered_option_ids):
            raise ValueError("duplicate ordered_option_ids are not allowed")
        return self


class SkillMastery(DomainModel):
    """A learner's current mastery of one skill. Never computed in this model."""

    mastery_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    skill_id: UUID
    mastery_score: float = Field(ge=0, le=1)
    mastery_level: MasteryLevel = MasteryLevel.NOT_ASSESSED
    correct_attempts: int = Field(default=0, ge=0)
    total_attempts: int = Field(default=0, ge=0)
    consecutive_correct: int = Field(default=0, ge=0)
    last_practiced_at: datetime | None = None
    next_review_at: datetime | None = None
    calculation_version: str = Field(min_length=1)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_counts(self) -> SkillMastery:
        if self.correct_attempts > self.total_attempts:
            raise ValueError("correct_attempts cannot exceed total_attempts")
        return self


class UserProgress(DomainModel):
    """A learner's progress toward a path, module, or lesson."""

    progress_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    path_id: UUID | None = None
    module_id: UUID | None = None
    lesson_id: UUID | None = None
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    completion_percentage: float = Field(default=0.0, ge=0, le=100)
    best_score: float | None = None
    attempt_count: int = Field(default=0, ge=0)
    first_started_at: datetime | None = None
    completed_at: datetime | None = None
    last_activity_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_progress(self) -> UserProgress:
        if not (self.path_id or self.module_id or self.lesson_id):
            raise ValueError("at least one of path_id, module_id, or lesson_id must be present")
        if (
            self.status in (ProgressStatus.COMPLETED, ProgressStatus.MASTERED)
            and self.completed_at is None
        ):
            raise ValueError("completed or mastered progress must have completed_at")
        return self


class Misconception(DomainModel):
    """A known, evidence-backed misconception a learner appears to hold.

    Detection logic (which is out of scope for this phase) may write
    these; this model only validates a well-formed record. It never
    invents a misconception via an LLM.
    """

    misconception_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    skill_id: UUID
    code: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    status: MisconceptionStatus = MisconceptionStatus.ACTIVE
    confidence_score: float = Field(ge=0, le=1)
    evidence_attempt_ids: list[UUID] = Field(default_factory=list)
    first_detected_at: datetime = Field(default_factory=utc_now)
    last_detected_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    detector_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_misconception(self) -> Misconception:
        if len(set(self.evidence_attempt_ids)) != len(self.evidence_attempt_ids):
            raise ValueError("evidence_attempt_ids must be unique")
        if self.last_detected_at < self.first_detected_at:
            raise ValueError("last_detected_at cannot precede first_detected_at")
        if self.status == MisconceptionStatus.RESOLVED and self.resolved_at is None:
            raise ValueError("resolved status must have resolved_at")
        return self
