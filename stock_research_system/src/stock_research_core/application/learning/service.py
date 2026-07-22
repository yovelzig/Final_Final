"""Application service orchestrating the learning platform.

This module depends only on domain models, application result models,
and `Protocol` contracts (`UnitOfWorkPort`, `MasteryCalculatorPort`). It
never instantiates a concrete engine, session, or repository -
everything is supplied by the caller (the CLI).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import UUID

from stock_research_core.application.exceptions import (
    ExerciseAttemptNotFoundError,
    ExerciseNotFoundError,
    InvalidGradingRequestError,
    LearnerNotFoundError,
    LessonNotFoundError,
)
from stock_research_core.application.learning.grading import grade_answer
from stock_research_core.application.learning.mastery import (
    DeterministicMasteryCalculator,
    MasteryCalculatorPort,
)
from stock_research_core.application.learning.models import (
    LearnerDashboard,
    LearningActivityResult,
    LessonWithExercises,
)
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.learning.enums import (
    AttemptStatus,
    ConfidenceLevel,
    DifficultyLevel,
    ProgressStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseAttempt,
    LearnerProfile,
    Lesson,
    SkillMastery,
    UserProgress,
)
from stock_research_core.domain.models import utc_now


class LearningService:
    """Orchestrates learner, curriculum, attempt, mastery, and progress data."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        mastery_calculator: MasteryCalculatorPort | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._mastery_calculator = mastery_calculator or DeterministicMasteryCalculator()

    async def create_learner(
        self,
        *,
        display_name: str,
        preferred_language: str = "en",
        experience_level: DifficultyLevel = DifficultyLevel.BEGINNER,
        daily_goal_minutes: int = 10,
    ) -> LearnerProfile:
        learner = LearnerProfile(
            display_name=display_name,
            preferred_language=preferred_language,
            financial_experience_level=experience_level,
            daily_goal_minutes=daily_goal_minutes,
        )
        async with self._unit_of_work_factory() as uow:
            created = await uow.learners.create(learner)
            await uow.commit()
        return created

    async def get_lesson_with_exercises(self, lesson_id: UUID) -> LessonWithExercises:
        async with self._unit_of_work_factory() as uow:
            lesson = await uow.curriculum.get_lesson(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(f"No lesson found with id '{lesson_id}'.")
            exercises = await uow.curriculum.list_exercises(lesson_id)
            options_by_exercise = {
                exercise.exercise_id: await uow.curriculum.list_options(exercise.exercise_id)
                for exercise in exercises
            }
        return LessonWithExercises(
            lesson=lesson, exercises=exercises, options_by_exercise=options_by_exercise
        )

    async def start_exercise_attempt(
        self,
        *,
        learner_id: UUID,
        exercise_id: UUID,
        confidence_level: ConfidenceLevel | None = None,
    ) -> ExerciseAttempt:
        async with self._unit_of_work_factory() as uow:
            exercise = await uow.curriculum.get_exercise(exercise_id)
            if exercise is None:
                raise ExerciseNotFoundError(f"No exercise found with id '{exercise_id}'.")

            previous_attempts = await uow.attempts.list_attempts(learner_id, exercise_id)
            attempt_number = len(previous_attempts) + 1

            attempt = ExerciseAttempt(
                learner_id=learner_id,
                exercise_id=exercise_id,
                maximum_score=exercise.maximum_score,
                attempt_number=attempt_number,
                confidence_level=confidence_level,
            )
            created = await uow.attempts.create_attempt(attempt)
            await uow.commit()
        return created

    async def submit_answer(
        self, *, attempt_id: UUID, answer: ExerciseAnswer
    ) -> LearningActivityResult:
        now = utc_now()
        async with self._unit_of_work_factory() as uow:
            attempt = await uow.attempts.get_attempt(attempt_id)
            if attempt is None:
                raise ExerciseAttemptNotFoundError(
                    f"No exercise attempt found with id '{attempt_id}'."
                )
            if answer.attempt_id != attempt_id:
                raise InvalidGradingRequestError(
                    "answer.attempt_id must match the attempt being submitted."
                )

            exercise = await uow.curriculum.get_exercise(attempt.exercise_id)
            if exercise is None:
                raise ExerciseNotFoundError(f"No exercise found with id '{attempt.exercise_id}'.")

            options = await uow.curriculum.list_options(exercise.exercise_id)
            outcome = grade_answer(exercise, options, answer)

            if outcome.graded:
                assert outcome.score is not None and outcome.is_correct is not None
                stored_attempt, saved_answer, updated_mastery, updated_progress = (
                    await self._finalize_graded_attempt(
                        uow,
                        attempt=attempt,
                        exercise=exercise,
                        answer=answer,
                        is_correct=outcome.is_correct,
                        score=outcome.score,
                        grading_version=None,
                        now=now,
                    )
                )
            else:
                saved_answer = await uow.attempts.save_answer(answer)
                submitted_at = max(answer.submitted_at, attempt.started_at)
                updated_attempt = ExerciseAttempt(
                    **{
                        **attempt.model_dump(),
                        "submitted_at": submitted_at,
                        "status": AttemptStatus.SUBMITTED,
                    }
                )
                stored_attempt = await uow.attempts.update_attempt(updated_attempt)
                updated_mastery = []
                updated_progress = None

            await uow.commit()

        return LearningActivityResult(
            attempt=stored_attempt,
            answer=saved_answer,
            updated_mastery=updated_mastery,
            updated_progress=updated_progress,
        )

    async def submit_externally_graded_answer(
        self,
        *,
        attempt_id: UUID,
        answer: ExerciseAnswer,
        normalized_score: float,
        is_correct: bool,
        grading_version: str,
    ) -> LearningActivityResult:
        """Grades an attempt using a score computed outside the
        deterministic auto-grading rules in `grading.py` (currently only
        the historical-market-scenario engine's rubric-based decision
        quality). Reuses the exact same answer-persistence, attempt
        transition, mastery-update, and lesson-progress logic as
        `submit_answer` via `_finalize_graded_attempt` - no mastery
        formula is duplicated here.

        `normalized_score` must already be the *decision-quality* score
        (or equivalent), never a realized market return or any other
        outcome-derived value - the caller is responsible for that.
        """
        if not 0.0 <= normalized_score <= 1.0:
            raise InvalidGradingRequestError("normalized_score must be between 0 and 1.")

        now = utc_now()
        async with self._unit_of_work_factory() as uow:
            attempt = await uow.attempts.get_attempt(attempt_id)
            if attempt is None:
                raise ExerciseAttemptNotFoundError(
                    f"No exercise attempt found with id '{attempt_id}'."
                )
            if answer.attempt_id != attempt_id:
                raise InvalidGradingRequestError(
                    "answer.attempt_id must match the attempt being submitted."
                )

            exercise = await uow.curriculum.get_exercise(attempt.exercise_id)
            if exercise is None:
                raise ExerciseNotFoundError(f"No exercise found with id '{attempt.exercise_id}'.")

            score = normalized_score * exercise.maximum_score
            stored_attempt, saved_answer, updated_mastery, updated_progress = (
                await self._finalize_graded_attempt(
                    uow,
                    attempt=attempt,
                    exercise=exercise,
                    answer=answer,
                    is_correct=is_correct,
                    score=score,
                    grading_version=grading_version,
                    now=now,
                )
            )
            await uow.commit()

        return LearningActivityResult(
            attempt=stored_attempt,
            answer=saved_answer,
            updated_mastery=updated_mastery,
            updated_progress=updated_progress,
        )

    async def _finalize_graded_attempt(
        self,
        uow: UnitOfWorkPort,
        *,
        attempt: ExerciseAttempt,
        exercise: Exercise,
        answer: ExerciseAnswer,
        is_correct: bool,
        score: float,
        grading_version: str | None,
        now: datetime,
    ) -> tuple[ExerciseAttempt, ExerciseAnswer, list[SkillMastery], UserProgress]:
        """Shared by `submit_answer` (auto-graded path) and
        `submit_externally_graded_answer`: save the answer, transition
        the attempt to GRADED, update skill mastery, and update lesson
        progress - exactly once, in exactly one place.
        """
        saved_answer = await uow.attempts.save_answer(answer)

        submitted_at = max(answer.submitted_at, attempt.started_at)
        graded_attempt = ExerciseAttempt(
            **{
                **attempt.model_dump(),
                "submitted_at": submitted_at,
                "status": AttemptStatus.GRADED,
                "graded_at": now,
                "score": score,
                "is_correct": is_correct,
                "grading_version": grading_version,
            }
        )
        stored_attempt = await uow.attempts.update_attempt(graded_attempt)

        normalized_score = score / exercise.maximum_score
        updated_mastery: list[SkillMastery] = []
        for skill_id in exercise.skill_ids:
            previous_mastery = await uow.mastery.get(attempt.learner_id, skill_id)
            new_mastery = self._mastery_calculator.update(
                learner_id=attempt.learner_id,
                skill_id=skill_id,
                previous=previous_mastery,
                latest_score_normalized=normalized_score,
                is_correct=is_correct,
                now=now,
            )
            updated_mastery.append(await uow.mastery.upsert(new_mastery))

        updated_progress = await self._update_lesson_progress(
            uow,
            learner_id=attempt.learner_id,
            exercise=exercise,
            is_correct=is_correct,
            score=score,
            now=now,
        )

        return stored_attempt, saved_answer, updated_mastery, updated_progress

    async def get_learner_dashboard(self, learner_id: UUID) -> LearnerDashboard:
        async with self._unit_of_work_factory() as uow:
            learner = await uow.learners.get(learner_id)
            if learner is None:
                raise LearnerNotFoundError(f"No learner found with id '{learner_id}'.")

            published_paths = await uow.curriculum.list_paths(published_only=True)
            active_path = published_paths[0] if published_paths else None

            progress_rows = await uow.progress.list_for_learner(learner_id)
            completed_lesson_ids = {
                progress.lesson_id
                for progress in progress_rows
                if progress.lesson_id is not None
                and progress.status in (ProgressStatus.COMPLETED, ProgressStatus.MASTERED)
            }

            path_lesson_ids: list[UUID] = []
            current_lesson: Lesson | None = None

            if active_path is not None:
                for module in await uow.curriculum.list_modules(active_path.path_id):
                    for lesson in await uow.curriculum.list_lessons(module.module_id):
                        path_lesson_ids.append(lesson.lesson_id)
                        if current_lesson is None and lesson.lesson_id not in completed_lesson_ids:
                            current_lesson = lesson

            skill_mastery = await uow.mastery.list_for_learner(learner_id)
            active_misconceptions = await uow.misconceptions.list_active(learner_id)

        return LearnerDashboard(
            learner=learner,
            active_path=active_path,
            current_lesson=current_lesson,
            completed_lessons=len(set(path_lesson_ids) & completed_lesson_ids),
            total_lessons=len(path_lesson_ids),
            current_streak_days=0,
            total_xp=0,
            skill_mastery=skill_mastery,
            active_misconceptions=active_misconceptions,
        )

    @staticmethod
    async def _update_lesson_progress(
        uow: UnitOfWorkPort,
        *,
        learner_id: UUID,
        exercise: Exercise,
        is_correct: bool,
        score: float,
        now: datetime,
    ) -> UserProgress:
        """Deterministic MVP rule: a lesson is COMPLETED once the learner has
        at least one correct graded attempt on every exercise it contains.
        `best_score` tracks the best single-exercise score seen for this
        lesson (exercises may use different scales).
        """
        lesson_id = exercise.lesson_id
        existing = await uow.progress.get_lesson_progress(learner_id, lesson_id)

        lesson_exercises = await uow.curriculum.list_exercises(lesson_id)
        lesson_exercise_ids = {ex.exercise_id for ex in lesson_exercises}

        learner_attempts = await uow.attempts.list_attempts(learner_id)
        passed_exercise_ids = {
            a.exercise_id
            for a in learner_attempts
            if a.exercise_id in lesson_exercise_ids
            and a.status == AttemptStatus.GRADED
            and a.is_correct
        }
        if is_correct:
            passed_exercise_ids.add(exercise.exercise_id)

        total = len(lesson_exercise_ids)
        completion_percentage = 100.0 * len(passed_exercise_ids) / total if total > 0 else 0.0
        status = (
            ProgressStatus.COMPLETED
            if completion_percentage >= 100.0
            else ProgressStatus.IN_PROGRESS
        )

        if existing is None:
            progress = UserProgress(
                learner_id=learner_id,
                lesson_id=lesson_id,
                status=status,
                completion_percentage=completion_percentage,
                best_score=score,
                attempt_count=1,
                first_started_at=now,
                completed_at=now if status == ProgressStatus.COMPLETED else None,
                last_activity_at=now,
                updated_at=now,
            )
        else:
            progress = UserProgress(
                **{
                    **existing.model_dump(),
                    "status": status,
                    "completion_percentage": completion_percentage,
                    "best_score": max(existing.best_score or 0.0, score),
                    "attempt_count": existing.attempt_count + 1,
                    "first_started_at": existing.first_started_at or now,
                    "completed_at": existing.completed_at
                    or (now if status == ProgressStatus.COMPLETED else None),
                    "last_activity_at": now,
                    "updated_at": now,
                }
            )

        return await uow.progress.upsert(progress)
