"""Unit tests for adaptive-learning ORM-to-domain mapper functions.

ORM classes are instantiated as plain Python objects (no database
connection, no PostgreSQL required).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.adaptive_learning.enums import (
    AdaptiveDecisionStatus,
    DiagnosticAssessmentStatus,
    LearningSessionStatus,
    LearningSessionType,
    RecommendationReason,
    RecommendationType,
    ReviewScheduleStatus,
)
from stock_research_core.infrastructure.database.mappers.adaptive_learning_mappers import (
    adaptive_decision_orm_to_domain,
    diagnostic_assessment_item_orm_to_domain,
    diagnostic_assessment_orm_to_domain,
    exercise_adaptive_profile_orm_to_domain,
    learning_session_activity_orm_to_domain,
    learning_session_orm_to_domain,
    skill_review_schedule_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.adaptive_decision import AdaptiveDecisionORM
from stock_research_core.infrastructure.database.orm.diagnostic_assessment import (
    DiagnosticAssessmentORM,
)
from stock_research_core.infrastructure.database.orm.diagnostic_assessment_item import (
    DiagnosticAssessmentItemORM,
)
from stock_research_core.infrastructure.database.orm.exercise_adaptive_profile import (
    ExerciseAdaptiveProfileORM,
)
from stock_research_core.infrastructure.database.orm.learning_session import LearningSessionORM
from stock_research_core.infrastructure.database.orm.learning_session_activity import (
    LearningSessionActivityORM,
)
from stock_research_core.infrastructure.database.orm.skill_review_schedule import (
    SkillReviewScheduleORM,
)

UTC_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_exercise_adaptive_profile_orm_to_domain_maps_arrays_and_decimals() -> None:
    prerequisite_id = uuid4()
    row = ExerciseAdaptiveProfileORM(
        profile_id=uuid4(),
        exercise_id=uuid4(),
        base_difficulty_score=Decimal("0.2500"),
        estimated_seconds=45,
        diagnostic_eligible=True,
        review_eligible=True,
        remediation_eligible=False,
        minimum_mastery_score=Decimal("0.1000"),
        maximum_mastery_score=Decimal("0.9000"),
        recommended_prerequisite_skill_ids=[prerequisite_id],
        policy_tags=["foundation", "concept-check"],
        active=True,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    profile = exercise_adaptive_profile_orm_to_domain(row)

    assert profile.base_difficulty_score == 0.25
    assert profile.minimum_mastery_score == 0.10
    assert profile.recommended_prerequisite_skill_ids == [prerequisite_id]
    assert profile.policy_tags == ["foundation", "concept-check"]


def test_exercise_adaptive_profile_orm_to_domain_maps_null_mastery_bounds() -> None:
    row = ExerciseAdaptiveProfileORM(
        profile_id=uuid4(),
        exercise_id=uuid4(),
        base_difficulty_score=Decimal("0.5"),
        estimated_seconds=45,
        diagnostic_eligible=False,
        review_eligible=False,
        remediation_eligible=False,
        minimum_mastery_score=None,
        maximum_mastery_score=None,
        recommended_prerequisite_skill_ids=[],
        policy_tags=[],
        active=True,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    profile = exercise_adaptive_profile_orm_to_domain(row)

    assert profile.minimum_mastery_score is None
    assert profile.maximum_mastery_score is None


def test_exercise_adaptive_profile_orm_to_domain_wraps_invalid_row() -> None:
    row = ExerciseAdaptiveProfileORM(
        profile_id=uuid4(),
        exercise_id=uuid4(),
        base_difficulty_score=Decimal("5.0"),  # out of [0, 1] range
        estimated_seconds=45,
        diagnostic_eligible=False,
        review_eligible=False,
        remediation_eligible=False,
        recommended_prerequisite_skill_ids=[],
        policy_tags=[],
        active=True,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    with pytest.raises(DatabaseMappingError):
        exercise_adaptive_profile_orm_to_domain(row)


def test_learning_session_orm_to_domain_maps_enums_and_scores() -> None:
    row = LearningSessionORM(
        session_id=uuid4(),
        learner_id=uuid4(),
        session_type="DAILY_PRACTICE",
        status="ACTIVE",
        goal_minutes=10,
        started_at=UTC_NOW,
        last_activity_at=UTC_NOW,
        completed_at=None,
        abandoned_at=None,
        recommended_item_count=1,
        completed_item_count=0,
        correct_item_count=0,
        total_score=Decimal("0.0"),
        maximum_score=Decimal("0.0"),
        policy_version="adaptive-policy-v1",
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    session = learning_session_orm_to_domain(row)

    assert session.session_type == LearningSessionType.DAILY_PRACTICE
    assert session.status == LearningSessionStatus.ACTIVE
    assert session.total_score == 0.0


def test_learning_session_orm_to_domain_wraps_invalid_status() -> None:
    row = LearningSessionORM(
        session_id=uuid4(),
        learner_id=uuid4(),
        session_type="DAILY_PRACTICE",
        status="NOT_A_REAL_STATUS",
        goal_minutes=10,
        started_at=UTC_NOW,
        last_activity_at=UTC_NOW,
        recommended_item_count=0,
        completed_item_count=0,
        correct_item_count=0,
        total_score=Decimal("0.0"),
        maximum_score=Decimal("0.0"),
        policy_version="adaptive-policy-v1",
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    with pytest.raises(DatabaseMappingError):
        learning_session_orm_to_domain(row)


def test_learning_session_activity_orm_to_domain_maps_optional_fields() -> None:
    row = LearningSessionActivityORM(
        activity_id=uuid4(),
        session_id=uuid4(),
        learner_id=uuid4(),
        exercise_id=uuid4(),
        attempt_id=None,
        decision_id=uuid4(),
        position=1,
        recommended_at=UTC_NOW,
        started_at=None,
        completed_at=None,
        skipped_at=None,
        created_at=UTC_NOW,
    )

    activity = learning_session_activity_orm_to_domain(row)

    assert activity.position == 1
    assert activity.attempt_id is None


def test_diagnostic_assessment_orm_to_domain_maps_skill_ids() -> None:
    skill_id = uuid4()
    row = DiagnosticAssessmentORM(
        assessment_id=uuid4(),
        learner_id=uuid4(),
        status="IN_PROGRESS",
        maximum_items=10,
        started_at=UTC_NOW,
        completed_at=None,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
        policy_version="diagnostic-policy-v1",
    )

    assessment = diagnostic_assessment_orm_to_domain(row, [skill_id])

    assert assessment.status == DiagnosticAssessmentStatus.IN_PROGRESS
    assert assessment.skill_ids == [skill_id]


def test_diagnostic_assessment_item_orm_to_domain_maps_normalized_score() -> None:
    skill_id = uuid4()
    row = DiagnosticAssessmentItemORM(
        item_id=uuid4(),
        assessment_id=uuid4(),
        exercise_id=uuid4(),
        position=1,
        attempt_id=uuid4(),
        selected_at=UTC_NOW,
        completed_at=UTC_NOW,
        normalized_score=Decimal("0.7500"),
    )

    item = diagnostic_assessment_item_orm_to_domain(row, [skill_id])

    assert item.normalized_score == 0.75
    assert item.skill_ids == [skill_id]


def test_skill_review_schedule_orm_to_domain_maps_ease_factor() -> None:
    row = SkillReviewScheduleORM(
        schedule_id=uuid4(),
        learner_id=uuid4(),
        skill_id=uuid4(),
        status="SCHEDULED",
        last_reviewed_at=UTC_NOW,
        next_review_at=UTC_NOW,
        review_interval_days=3,
        successful_review_count=1,
        failed_review_count=0,
        consecutive_successful_reviews=1,
        ease_factor=Decimal("2.00"),
        calculation_version="review-schedule-v1",
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    schedule = skill_review_schedule_orm_to_domain(row)

    assert schedule.status == ReviewScheduleStatus.SCHEDULED
    assert schedule.ease_factor == 2.0


def test_adaptive_decision_orm_to_domain_maps_reasons_and_snapshot() -> None:
    skill_id = uuid4()
    row = AdaptiveDecisionORM(
        decision_id=uuid4(),
        learner_id=uuid4(),
        session_id=uuid4(),
        recommendation_type="PRACTICE_EXERCISE",
        status="GENERATED",
        recommended_exercise_id=uuid4(),
        recommended_lesson_id=uuid4(),
        priority_score=Decimal("0.5000"),
        recommended_difficulty_score=None,
        policy_version="adaptive-policy-v1",
        explanation="explanation",
        input_snapshot={"policy_version": "adaptive-policy-v1"},
        generated_at=UTC_NOW,
        accepted_at=None,
        completed_at=None,
        skipped_at=None,
        expires_at=None,
    )

    decision = adaptive_decision_orm_to_domain(row, [skill_id], ["LOW_MASTERY"])

    assert decision.recommendation_type == RecommendationType.PRACTICE_EXERCISE
    assert decision.status == AdaptiveDecisionStatus.GENERATED
    assert decision.target_skill_ids == [skill_id]
    assert decision.reason_codes == [RecommendationReason.LOW_MASTERY]
    assert decision.input_snapshot == {"policy_version": "adaptive-policy-v1"}


def test_adaptive_decision_orm_to_domain_wraps_invalid_reason_code() -> None:
    row = AdaptiveDecisionORM(
        decision_id=uuid4(),
        learner_id=uuid4(),
        session_id=None,
        recommendation_type="SESSION_COMPLETE",
        status="GENERATED",
        recommended_exercise_id=None,
        recommended_lesson_id=None,
        priority_score=Decimal("1.0000"),
        recommended_difficulty_score=None,
        policy_version="adaptive-policy-v1",
        explanation="explanation",
        input_snapshot={},
        generated_at=UTC_NOW,
        accepted_at=None,
        completed_at=None,
        skipped_at=None,
        expires_at=None,
    )

    with pytest.raises(DatabaseMappingError):
        adaptive_decision_orm_to_domain(row, [], ["NOT_A_REAL_REASON"])
