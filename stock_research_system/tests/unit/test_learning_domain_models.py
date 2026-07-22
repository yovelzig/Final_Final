"""Unit tests for the FinQuest learning domain models. No database required."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.learning.enums import (
    AttemptStatus,
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    MisconceptionStatus,
    ProgressStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseAttempt,
    LearnerProfile,
    Lesson,
    Misconception,
    Skill,
    SkillMastery,
    UserProgress,
)

NOW = datetime.now(timezone.utc)


def test_learner_daily_goal_must_be_between_5_and_180_minutes() -> None:
    with pytest.raises(ValidationError):
        LearnerProfile(display_name="Amit", daily_goal_minutes=3)
    with pytest.raises(ValidationError):
        LearnerProfile(display_name="Amit", daily_goal_minutes=200)
    assert LearnerProfile(display_name="Amit", daily_goal_minutes=15).daily_goal_minutes == 15


def test_learner_preferred_language_defaults_to_en() -> None:
    learner = LearnerProfile(display_name="Amit")
    assert learner.preferred_language == "en"


def test_learner_preferred_language_is_normalized() -> None:
    learner = LearnerProfile(display_name="Amit", preferred_language="EN")
    assert learner.preferred_language == "en"


def test_skill_code_must_be_uppercase_snake_case() -> None:
    with pytest.raises(ValidationError):
        Skill(
            code="money-basics",
            name="Money Basics",
            description="desc",
            category=FinancialSkillCategory.MONEY_BASICS,
            difficulty=DifficultyLevel.BEGINNER,
        )
    valid = Skill(
        code="MONEY_BASICS",
        name="Money Basics",
        description="desc",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    assert valid.code == "MONEY_BASICS"


def test_skill_cannot_depend_on_itself() -> None:
    skill_id = uuid4()
    with pytest.raises(ValidationError):
        Skill(
            skill_id=skill_id,
            code="RISK_AND_RETURN",
            name="Risk and Return",
            description="desc",
            category=FinancialSkillCategory.RISK_AND_RETURN,
            difficulty=DifficultyLevel.BEGINNER,
            prerequisite_skill_ids=[skill_id],
        )


def test_skill_rejects_duplicate_prerequisites() -> None:
    duplicate_id = uuid4()
    with pytest.raises(ValidationError):
        Skill(
            code="DIVERSIFICATION",
            name="Diversification",
            description="desc",
            category=FinancialSkillCategory.DIVERSIFICATION,
            difficulty=DifficultyLevel.BEGINNER,
            prerequisite_skill_ids=[duplicate_id, duplicate_id],
        )


def _lesson_kwargs(**overrides: object) -> dict:
    defaults = dict(
        module_id=uuid4(),
        code="what-money-is-for",
        title="What Money Is For",
        summary="summary",
        content_markdown="# content",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        estimated_minutes=15,
        primary_skill_id=uuid4(),
    )
    defaults.update(overrides)
    return defaults


def test_lesson_primary_skill_cannot_also_be_secondary() -> None:
    skill_id = uuid4()
    with pytest.raises(ValidationError):
        Lesson(**_lesson_kwargs(primary_skill_id=skill_id, secondary_skill_ids=[skill_id]))


def test_lesson_rejects_duplicate_secondary_skills() -> None:
    duplicate_id = uuid4()
    with pytest.raises(ValidationError):
        Lesson(**_lesson_kwargs(secondary_skill_ids=[duplicate_id, duplicate_id]))


def _exercise_kwargs(**overrides: object) -> dict:
    defaults = dict(
        lesson_id=uuid4(),
        exercise_type=ExerciseType.SINGLE_CHOICE,
        prompt="prompt",
        explanation="explanation",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        skill_ids=[uuid4()],
        maximum_score=1.0,
        passing_score=1.0,
    )
    defaults.update(overrides)
    return defaults


def test_exercise_passing_score_cannot_exceed_maximum_score() -> None:
    with pytest.raises(ValidationError):
        Exercise(**_exercise_kwargs(maximum_score=1.0, passing_score=1.5))


def test_exercise_requires_at_least_one_skill() -> None:
    with pytest.raises(ValidationError):
        Exercise(**_exercise_kwargs(skill_ids=[]))


def _attempt_kwargs(**overrides: object) -> dict:
    defaults = dict(
        learner_id=uuid4(),
        exercise_id=uuid4(),
        maximum_score=1.0,
        attempt_number=1,
    )
    defaults.update(overrides)
    return defaults


def test_attempt_submitted_at_cannot_precede_started_at() -> None:
    started_at = NOW
    with pytest.raises(ValidationError):
        ExerciseAttempt(
            **_attempt_kwargs(
                status=AttemptStatus.SUBMITTED,
                started_at=started_at,
                submitted_at=started_at - timedelta(seconds=1),
            )
        )


def test_attempt_graded_at_cannot_precede_submitted_at() -> None:
    started_at = NOW
    submitted_at = started_at + timedelta(seconds=10)
    with pytest.raises(ValidationError):
        ExerciseAttempt(
            **_attempt_kwargs(
                status=AttemptStatus.GRADED,
                started_at=started_at,
                submitted_at=submitted_at,
                graded_at=submitted_at - timedelta(seconds=1),
                score=1.0,
                is_correct=True,
            )
        )


def test_graded_attempt_requires_graded_at_score_and_is_correct() -> None:
    started_at = NOW
    submitted_at = started_at + timedelta(seconds=10)
    with pytest.raises(ValidationError):
        ExerciseAttempt(
            **_attempt_kwargs(
                status=AttemptStatus.GRADED,
                started_at=started_at,
                submitted_at=submitted_at,
            )
        )


def test_answer_requires_at_least_one_response_representation() -> None:
    with pytest.raises(ValidationError):
        ExerciseAnswer(attempt_id=uuid4())


def test_answer_rejects_duplicate_selected_options() -> None:
    duplicate_id = uuid4()
    with pytest.raises(ValidationError):
        ExerciseAnswer(attempt_id=uuid4(), selected_option_ids=[duplicate_id, duplicate_id])


def test_answer_rejects_duplicate_ordered_options() -> None:
    duplicate_id = uuid4()
    with pytest.raises(ValidationError):
        ExerciseAnswer(attempt_id=uuid4(), ordered_option_ids=[duplicate_id, duplicate_id])


def test_mastery_correct_attempts_cannot_exceed_total_attempts() -> None:
    with pytest.raises(ValidationError):
        SkillMastery(
            learner_id=uuid4(),
            skill_id=uuid4(),
            mastery_score=0.5,
            correct_attempts=5,
            total_attempts=2,
            calculation_version="mastery-v1",
        )


def test_completed_progress_requires_completed_at() -> None:
    with pytest.raises(ValidationError):
        UserProgress(learner_id=uuid4(), lesson_id=uuid4(), status=ProgressStatus.COMPLETED)


def test_progress_requires_at_least_one_target_id() -> None:
    with pytest.raises(ValidationError):
        UserProgress(learner_id=uuid4())


def test_resolved_misconception_requires_resolved_at() -> None:
    with pytest.raises(ValidationError):
        Misconception(
            learner_id=uuid4(),
            skill_id=uuid4(),
            code="GUARANTEED_RETURN_MYTH",
            description="Believes diversification guarantees profit.",
            status=MisconceptionStatus.RESOLVED,
            confidence_score=0.8,
            detector_version="misconception-v1",
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        LearnerProfile(display_name="Amit", unknown_field="not allowed")
