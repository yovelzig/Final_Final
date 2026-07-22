"""Request/response DTOs for `/api/v1` curriculum, attempt, and answer endpoints.

`ExerciseOptionResponse`/`ExerciseResponse` never carry `is_correct` or
`feedback` - the only place a correct-answer signal ever appears is
`SubmitAnswerResponse.is_correct`, which reflects the learner's *own*
just-submitted attempt, not the underlying option data.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.api.schemas.learners import ProgressResponse, SkillMasteryResponse
from stock_research_core.domain.learning.enums import AttemptStatus, ConfidenceLevel, DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAttempt,
    ExerciseOption,
    LearningModule,
    LearningPath,
    Lesson,
)


class LearningPathResponse(ApiSchema):
    path_id: UUID
    code: str
    title: str
    description: str
    difficulty: DifficultyLevel
    position: int
    estimated_minutes: int
    published: bool

    @staticmethod
    def from_domain(path: LearningPath) -> LearningPathResponse:
        return LearningPathResponse(
            path_id=path.path_id, code=path.code, title=path.title, description=path.description,
            difficulty=path.difficulty, position=path.position, estimated_minutes=path.estimated_minutes,
            published=path.published,
        )


class LearningModuleResponse(ApiSchema):
    module_id: UUID
    path_id: UUID
    code: str
    title: str
    description: str
    position: int
    estimated_minutes: int
    published: bool

    @staticmethod
    def from_domain(module: LearningModule) -> LearningModuleResponse:
        return LearningModuleResponse(
            module_id=module.module_id, path_id=module.path_id, code=module.code, title=module.title,
            description=module.description, position=module.position,
            estimated_minutes=module.estimated_minutes, published=module.published,
        )


class LessonResponse(ApiSchema):
    lesson_id: UUID
    module_id: UUID
    code: str
    title: str
    summary: str
    content_markdown: str
    difficulty: DifficultyLevel
    position: int
    estimated_minutes: int
    primary_skill_id: UUID
    secondary_skill_ids: list[UUID]

    @staticmethod
    def from_domain(lesson: Lesson) -> LessonResponse:
        return LessonResponse(
            lesson_id=lesson.lesson_id, module_id=lesson.module_id, code=lesson.code, title=lesson.title,
            summary=lesson.summary, content_markdown=lesson.content_markdown, difficulty=lesson.difficulty,
            position=lesson.position, estimated_minutes=lesson.estimated_minutes,
            primary_skill_id=lesson.primary_skill_id, secondary_skill_ids=list(lesson.secondary_skill_ids),
        )


class ExerciseOptionResponse(ApiSchema):
    """Learner-safe: never carries `is_correct` or `feedback`."""

    option_id: UUID
    option_key: str
    content: str
    position: int

    @staticmethod
    def from_domain(option: ExerciseOption) -> ExerciseOptionResponse:
        return ExerciseOptionResponse(
            option_id=option.option_id, option_key=option.option_key, content=option.content,
            position=option.position,
        )


class ExerciseResponse(ApiSchema):
    """Learner-safe: never carries `explanation` or any option's `is_correct`/`feedback`."""

    exercise_id: UUID
    lesson_id: UUID
    exercise_type: ExerciseType
    prompt: str
    difficulty: DifficultyLevel
    position: int
    skill_ids: list[UUID]
    maximum_score: float
    passing_score: float
    options: list[ExerciseOptionResponse]

    @staticmethod
    def from_domain(exercise: Exercise, options: list[ExerciseOption]) -> ExerciseResponse:
        return ExerciseResponse(
            exercise_id=exercise.exercise_id, lesson_id=exercise.lesson_id,
            exercise_type=exercise.exercise_type, prompt=exercise.prompt, difficulty=exercise.difficulty,
            position=exercise.position, skill_ids=list(exercise.skill_ids),
            maximum_score=exercise.maximum_score, passing_score=exercise.passing_score,
            options=[ExerciseOptionResponse.from_domain(option) for option in options],
        )


class StartAttemptRequest(ApiSchema):
    confidence_level: ConfidenceLevel | None = None


class AttemptResponse(ApiSchema):
    attempt_id: UUID
    exercise_id: UUID
    status: AttemptStatus
    started_at: datetime
    submitted_at: datetime | None
    graded_at: datetime | None
    score: float | None
    maximum_score: float
    is_correct: bool | None
    confidence_level: ConfidenceLevel | None
    attempt_number: int

    @staticmethod
    def from_domain(attempt: ExerciseAttempt) -> AttemptResponse:
        return AttemptResponse(
            attempt_id=attempt.attempt_id, exercise_id=attempt.exercise_id, status=attempt.status,
            started_at=attempt.started_at, submitted_at=attempt.submitted_at, graded_at=attempt.graded_at,
            score=attempt.score, maximum_score=attempt.maximum_score, is_correct=attempt.is_correct,
            confidence_level=attempt.confidence_level, attempt_number=attempt.attempt_number,
        )


class SubmitAnswerRequest(ApiSchema):
    selected_option_ids: list[UUID] = Field(default_factory=list)
    numeric_answer: float | None = None
    text_answer: str | None = Field(default=None, max_length=5000)
    ordered_option_ids: list[UUID] = Field(default_factory=list)


class SubmitAnswerResponse(ApiSchema):
    attempt: AttemptResponse
    updated_mastery: list[SkillMasteryResponse]
    updated_progress: ProgressResponse | None
