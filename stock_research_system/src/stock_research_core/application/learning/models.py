"""Application-level result models for the learning platform.

Composite views assembled from multiple learning-domain objects. Plain
Pydantic models; no SQLAlchemy or other infrastructure dependency here.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseAttempt,
    ExerciseOption,
    LearnerProfile,
    LearningPath,
    Lesson,
    Misconception,
    SkillMastery,
    UserProgress,
)
from stock_research_core.domain.models import DomainModel


class LessonWithExercises(DomainModel):
    """A lesson bundled with its exercises and each exercise's options."""

    lesson: Lesson
    exercises: list[Exercise] = Field(default_factory=list)
    options_by_exercise: dict[UUID, list[ExerciseOption]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_options_belong_to_result(self) -> LessonWithExercises:
        exercise_ids = {exercise.exercise_id for exercise in self.exercises}
        for exercise_id, options in self.options_by_exercise.items():
            if exercise_id not in exercise_ids:
                raise ValueError(
                    f"options_by_exercise references exercise '{exercise_id}', which is "
                    "not among the result's exercises"
                )
            if any(option.exercise_id != exercise_id for option in options):
                raise ValueError(
                    f"an option under exercise '{exercise_id}' does not belong to that exercise"
                )
        return self


class LearnerDashboard(DomainModel):
    """A learner's at-a-glance progress summary.

    `current_streak_days` and `total_xp` are gamification placeholders
    for a later phase and are always zero for now.
    """

    learner: LearnerProfile
    active_path: LearningPath | None = None
    current_lesson: Lesson | None = None
    completed_lessons: int = Field(default=0, ge=0)
    total_lessons: int = Field(default=0, ge=0)
    current_streak_days: int = Field(default=0, ge=0)
    total_xp: int = Field(default=0, ge=0)
    skill_mastery: list[SkillMastery] = Field(default_factory=list)
    active_misconceptions: list[Misconception] = Field(default_factory=list)


class LearningActivityResult(DomainModel):
    """The outcome of submitting an answer to an exercise attempt."""

    attempt: ExerciseAttempt
    answer: ExerciseAnswer
    updated_mastery: list[SkillMastery] = Field(default_factory=list)
    updated_progress: UserProgress | None = None
