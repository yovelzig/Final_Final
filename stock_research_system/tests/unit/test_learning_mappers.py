"""Unit tests for learning ORM-to-domain mapper functions.

ORM classes are instantiated as plain Python objects (no database
connection, no PostgreSQL required).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.learning.enums import FinancialSkillCategory, MasteryLevel
from stock_research_core.infrastructure.database.mappers.learning_mappers import (
    exercise_attempt_orm_to_domain,
    exercise_orm_to_domain,
    lesson_orm_to_domain,
    misconception_orm_to_domain,
    skill_mastery_orm_to_domain,
    skill_orm_to_domain,
    user_progress_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.exercise import ExerciseORM
from stock_research_core.infrastructure.database.orm.exercise_attempt import ExerciseAttemptORM
from stock_research_core.infrastructure.database.orm.lesson import LessonORM
from stock_research_core.infrastructure.database.orm.misconception import MisconceptionORM
from stock_research_core.infrastructure.database.orm.skill import FinancialSkillORM
from stock_research_core.infrastructure.database.orm.skill_mastery import SkillMasteryORM
from stock_research_core.infrastructure.database.orm.user_progress import UserProgressORM

UTC_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_skill_orm_to_domain_maps_all_fields_and_prerequisites() -> None:
    prerequisite_id = uuid4()
    row = FinancialSkillORM(
        skill_id=uuid4(),
        code="RISK_AND_RETURN",
        name="Risk and Return",
        description="desc",
        category="RISK_AND_RETURN",
        difficulty="BEGINNER",
        active=True,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    skill = skill_orm_to_domain(row, [prerequisite_id])

    assert skill.code == "RISK_AND_RETURN"
    assert skill.category == FinancialSkillCategory.RISK_AND_RETURN
    assert skill.prerequisite_skill_ids == [prerequisite_id]


def test_skill_orm_to_domain_rejects_invalid_category() -> None:
    row = FinancialSkillORM(
        skill_id=uuid4(),
        code="RISK_AND_RETURN",
        name="Risk and Return",
        description="desc",
        category="NOT_A_REAL_CATEGORY",
        difficulty="BEGINNER",
        active=True,
    )

    with pytest.raises(DatabaseMappingError):
        skill_orm_to_domain(row, [])


def test_lesson_orm_to_domain_maps_secondary_skills() -> None:
    secondary_id = uuid4()
    row = LessonORM(
        lesson_id=uuid4(),
        module_id=uuid4(),
        code="what-money-is-for",
        title="What Money Is For",
        summary="summary",
        content_markdown="# content",
        difficulty="BEGINNER",
        status="PUBLISHED",
        position=0,
        estimated_minutes=15,
        primary_skill_id=uuid4(),
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    lesson = lesson_orm_to_domain(row, [secondary_id])

    assert lesson.secondary_skill_ids == [secondary_id]
    assert lesson.created_at.tzinfo is not None


def test_exercise_orm_to_domain_converts_decimals_to_floats() -> None:
    row = ExerciseORM(
        exercise_id=uuid4(),
        lesson_id=uuid4(),
        exercise_type="SINGLE_CHOICE",
        prompt="prompt",
        explanation="explanation",
        difficulty="BEGINNER",
        position=0,
        maximum_score=Decimal("1.0000"),
        passing_score=Decimal("1.0000"),
        configuration={},
        active=True,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    exercise = exercise_orm_to_domain(row, [uuid4()])

    assert isinstance(exercise.maximum_score, float)
    assert exercise.maximum_score == pytest.approx(1.0)


def test_exercise_attempt_orm_to_domain_preserves_uuid_and_utc_timestamp() -> None:
    attempt_id = uuid4()
    row = ExerciseAttemptORM(
        attempt_id=attempt_id,
        learner_id=uuid4(),
        exercise_id=uuid4(),
        status="STARTED",
        started_at=UTC_NOW,
        maximum_score=Decimal("1.0000"),
        attempt_number=1,
        created_at=UTC_NOW,
    )

    attempt = exercise_attempt_orm_to_domain(row)

    assert attempt.attempt_id == attempt_id
    assert attempt.started_at.tzinfo is not None
    assert attempt.started_at == UTC_NOW


def test_skill_mastery_orm_to_domain_converts_decimal_score() -> None:
    row = SkillMasteryORM(
        mastery_id=uuid4(),
        learner_id=uuid4(),
        skill_id=uuid4(),
        mastery_score=Decimal("0.7500"),
        mastery_level="PROFICIENT",
        correct_attempts=3,
        total_attempts=4,
        consecutive_correct=2,
        calculation_version="mastery-v1",
        updated_at=UTC_NOW,
    )

    mastery = skill_mastery_orm_to_domain(row)

    assert isinstance(mastery.mastery_score, float)
    assert mastery.mastery_score == pytest.approx(0.75)
    assert mastery.mastery_level == MasteryLevel.PROFICIENT


def test_user_progress_orm_to_domain_maps_optional_fields() -> None:
    row = UserProgressORM(
        progress_id=uuid4(),
        learner_id=uuid4(),
        lesson_id=uuid4(),
        status="IN_PROGRESS",
        completion_percentage=Decimal("50.00"),
        attempt_count=2,
        updated_at=UTC_NOW,
    )

    progress = user_progress_orm_to_domain(row)

    assert isinstance(progress.completion_percentage, float)
    assert progress.completion_percentage == pytest.approx(50.0)
    assert progress.best_score is None


def test_misconception_orm_to_domain_maps_evidence_attempts() -> None:
    evidence_id = uuid4()
    row = MisconceptionORM(
        misconception_id=uuid4(),
        learner_id=uuid4(),
        skill_id=uuid4(),
        code="GUARANTEED_RETURN_MYTH",
        description="Believes diversification guarantees profit.",
        status="ACTIVE",
        confidence_score=Decimal("0.9000"),
        first_detected_at=UTC_NOW,
        last_detected_at=UTC_NOW,
        detector_version="misconception-v1",
    )

    misconception = misconception_orm_to_domain(row, [evidence_id])

    assert misconception.evidence_attempt_ids == [evidence_id]
    assert isinstance(misconception.confidence_score, float)
