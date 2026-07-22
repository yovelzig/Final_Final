"""Maps between learning ORM rows and learning domain models.

Some domain fields (`prerequisite_skill_ids`, `secondary_skill_ids`,
`skill_ids`, `selected_option_ids`, `ordered_option_ids`,
`evidence_attempt_ids`) live in separate association tables, not on the
primary ORM row - repositories query those separately and pass the
resulting ID lists into these mapper functions.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
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
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseAttempt,
    ExerciseOption,
    LearnerProfile,
    LearningModule,
    LearningPath,
    Lesson,
    Misconception,
    Skill,
    SkillMastery,
    UserProgress,
)
from stock_research_core.infrastructure.database.orm.exercise import ExerciseORM
from stock_research_core.infrastructure.database.orm.exercise_answer import ExerciseAnswerORM
from stock_research_core.infrastructure.database.orm.exercise_attempt import ExerciseAttemptORM
from stock_research_core.infrastructure.database.orm.exercise_option import ExerciseOptionORM
from stock_research_core.infrastructure.database.orm.learner_profile import LearnerProfileORM
from stock_research_core.infrastructure.database.orm.learning_module import LearningModuleORM
from stock_research_core.infrastructure.database.orm.learning_path import LearningPathORM
from stock_research_core.infrastructure.database.orm.lesson import LessonORM
from stock_research_core.infrastructure.database.orm.misconception import MisconceptionORM
from stock_research_core.infrastructure.database.orm.skill import FinancialSkillORM
from stock_research_core.infrastructure.database.orm.skill_mastery import SkillMasteryORM
from stock_research_core.infrastructure.database.orm.user_progress import UserProgressORM


def learner_profile_orm_to_domain(row: LearnerProfileORM) -> LearnerProfile:
    try:
        return LearnerProfile(
            learner_id=row.learner_id,
            display_name=row.display_name,
            preferred_language=row.preferred_language,
            financial_experience_level=DifficultyLevel(row.financial_experience_level),
            daily_goal_minutes=row.daily_goal_minutes,
            created_at=row.created_at,
            updated_at=row.updated_at,
            active=row.active,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored learner row '{row.learner_id}' could not be mapped to a domain LearnerProfile."
        ) from exc


def skill_orm_to_domain(row: FinancialSkillORM, prerequisite_skill_ids: list[UUID]) -> Skill:
    try:
        return Skill(
            skill_id=row.skill_id,
            code=row.code,
            name=row.name,
            description=row.description,
            category=FinancialSkillCategory(row.category),
            difficulty=DifficultyLevel(row.difficulty),
            prerequisite_skill_ids=prerequisite_skill_ids,
            active=row.active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored skill row '{row.skill_id}' could not be mapped to a domain Skill."
        ) from exc


def learning_path_orm_to_domain(row: LearningPathORM) -> LearningPath:
    try:
        return LearningPath(
            path_id=row.path_id,
            code=row.code,
            title=row.title,
            description=row.description,
            difficulty=DifficultyLevel(row.difficulty),
            position=row.position,
            estimated_minutes=row.estimated_minutes,
            published=row.published,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored learning path row '{row.path_id}' could not be mapped to a domain LearningPath."
        ) from exc


def learning_module_orm_to_domain(row: LearningModuleORM) -> LearningModule:
    try:
        return LearningModule(
            module_id=row.module_id,
            path_id=row.path_id,
            code=row.code,
            title=row.title,
            description=row.description,
            position=row.position,
            estimated_minutes=row.estimated_minutes,
            published=row.published,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored learning module row '{row.module_id}' could not be mapped to a domain LearningModule."
        ) from exc


def lesson_orm_to_domain(row: LessonORM, secondary_skill_ids: list[UUID]) -> Lesson:
    try:
        return Lesson(
            lesson_id=row.lesson_id,
            module_id=row.module_id,
            code=row.code,
            title=row.title,
            summary=row.summary,
            content_markdown=row.content_markdown,
            difficulty=DifficultyLevel(row.difficulty),
            status=LessonStatus(row.status),
            position=row.position,
            estimated_minutes=row.estimated_minutes,
            primary_skill_id=row.primary_skill_id,
            secondary_skill_ids=secondary_skill_ids,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored lesson row '{row.lesson_id}' could not be mapped to a domain Lesson."
        ) from exc


def exercise_orm_to_domain(row: ExerciseORM, skill_ids: list[UUID]) -> Exercise:
    try:
        return Exercise(
            exercise_id=row.exercise_id,
            lesson_id=row.lesson_id,
            exercise_type=ExerciseType(row.exercise_type),
            prompt=row.prompt,
            explanation=row.explanation,
            difficulty=DifficultyLevel(row.difficulty),
            position=row.position,
            skill_ids=skill_ids,
            maximum_score=float(row.maximum_score),
            passing_score=float(row.passing_score),
            configuration=dict(row.configuration or {}),
            active=row.active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored exercise row '{row.exercise_id}' could not be mapped to a domain Exercise."
        ) from exc


def exercise_option_orm_to_domain(row: ExerciseOptionORM) -> ExerciseOption:
    try:
        return ExerciseOption(
            option_id=row.option_id,
            exercise_id=row.exercise_id,
            option_key=row.option_key,
            content=row.content,
            position=row.position,
            is_correct=row.is_correct,
            feedback=row.feedback,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored exercise option row '{row.option_id}' could not be mapped to a domain ExerciseOption."
        ) from exc


def exercise_attempt_orm_to_domain(row: ExerciseAttemptORM) -> ExerciseAttempt:
    try:
        return ExerciseAttempt(
            attempt_id=row.attempt_id,
            learner_id=row.learner_id,
            exercise_id=row.exercise_id,
            status=AttemptStatus(row.status),
            started_at=row.started_at,
            submitted_at=row.submitted_at,
            graded_at=row.graded_at,
            score=float(row.score) if row.score is not None else None,
            maximum_score=float(row.maximum_score),
            is_correct=row.is_correct,
            confidence_level=ConfidenceLevel(row.confidence_level) if row.confidence_level else None,
            response_time_seconds=row.response_time_seconds,
            attempt_number=row.attempt_number,
            grading_version=row.grading_version,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored exercise attempt row '{row.attempt_id}' could not be mapped to a domain ExerciseAttempt."
        ) from exc


def exercise_answer_orm_to_domain(
    row: ExerciseAnswerORM,
    selected_option_ids: list[UUID],
    ordered_option_ids: list[UUID],
) -> ExerciseAnswer:
    try:
        return ExerciseAnswer(
            answer_id=row.answer_id,
            attempt_id=row.attempt_id,
            selected_option_ids=selected_option_ids,
            numeric_answer=float(row.numeric_answer) if row.numeric_answer is not None else None,
            text_answer=row.text_answer,
            ordered_option_ids=ordered_option_ids,
            submitted_at=row.submitted_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored exercise answer row '{row.answer_id}' could not be mapped to a domain ExerciseAnswer."
        ) from exc


def skill_mastery_orm_to_domain(row: SkillMasteryORM) -> SkillMastery:
    try:
        return SkillMastery(
            mastery_id=row.mastery_id,
            learner_id=row.learner_id,
            skill_id=row.skill_id,
            mastery_score=float(row.mastery_score),
            mastery_level=MasteryLevel(row.mastery_level),
            correct_attempts=row.correct_attempts,
            total_attempts=row.total_attempts,
            consecutive_correct=row.consecutive_correct,
            last_practiced_at=row.last_practiced_at,
            next_review_at=row.next_review_at,
            calculation_version=row.calculation_version,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored skill mastery row '{row.mastery_id}' could not be mapped to a domain SkillMastery."
        ) from exc


def user_progress_orm_to_domain(row: UserProgressORM) -> UserProgress:
    try:
        return UserProgress(
            progress_id=row.progress_id,
            learner_id=row.learner_id,
            path_id=row.path_id,
            module_id=row.module_id,
            lesson_id=row.lesson_id,
            status=ProgressStatus(row.status),
            completion_percentage=float(row.completion_percentage),
            best_score=float(row.best_score) if row.best_score is not None else None,
            attempt_count=row.attempt_count,
            first_started_at=row.first_started_at,
            completed_at=row.completed_at,
            last_activity_at=row.last_activity_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored progress row '{row.progress_id}' could not be mapped to a domain UserProgress."
        ) from exc


def misconception_orm_to_domain(
    row: MisconceptionORM, evidence_attempt_ids: list[UUID]
) -> Misconception:
    try:
        return Misconception(
            misconception_id=row.misconception_id,
            learner_id=row.learner_id,
            skill_id=row.skill_id,
            code=row.code,
            description=row.description,
            status=MisconceptionStatus(row.status),
            confidence_score=float(row.confidence_score),
            evidence_attempt_ids=evidence_attempt_ids,
            first_detected_at=row.first_detected_at,
            last_detected_at=row.last_detected_at,
            resolved_at=row.resolved_at,
            detector_version=row.detector_version,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored misconception row '{row.misconception_id}' could not be mapped to a domain Misconception."
        ) from exc
