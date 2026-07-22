"""Maps between adaptive-learning ORM rows and adaptive-learning domain models.

`DiagnosticAssessment.skill_ids`, `DiagnosticAssessmentItem.skill_ids`,
`AdaptiveDecision.target_skill_ids`, and `AdaptiveDecision.reason_codes`
live in separate association tables, not on the primary ORM row -
repositories query those separately and pass the resulting lists into
these mapper functions.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

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
from stock_research_core.domain.adaptive_learning.models import (
    AdaptiveDecision,
    DiagnosticAssessment,
    DiagnosticAssessmentItem,
    ExerciseAdaptiveProfile,
    LearningSession,
    LearningSessionActivity,
    SkillReviewSchedule,
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


def exercise_adaptive_profile_orm_to_domain(row: ExerciseAdaptiveProfileORM) -> ExerciseAdaptiveProfile:
    try:
        return ExerciseAdaptiveProfile(
            profile_id=row.profile_id,
            exercise_id=row.exercise_id,
            base_difficulty_score=float(row.base_difficulty_score),
            estimated_seconds=row.estimated_seconds,
            diagnostic_eligible=row.diagnostic_eligible,
            review_eligible=row.review_eligible,
            remediation_eligible=row.remediation_eligible,
            minimum_mastery_score=(
                float(row.minimum_mastery_score) if row.minimum_mastery_score is not None else None
            ),
            maximum_mastery_score=(
                float(row.maximum_mastery_score) if row.maximum_mastery_score is not None else None
            ),
            recommended_prerequisite_skill_ids=list(row.recommended_prerequisite_skill_ids or []),
            policy_tags=list(row.policy_tags or []),
            active=row.active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored adaptive profile row '{row.profile_id}' could not be mapped to a "
            "domain ExerciseAdaptiveProfile."
        ) from exc


def learning_session_orm_to_domain(row: LearningSessionORM) -> LearningSession:
    try:
        return LearningSession(
            session_id=row.session_id,
            learner_id=row.learner_id,
            session_type=LearningSessionType(row.session_type),
            status=LearningSessionStatus(row.status),
            goal_minutes=row.goal_minutes,
            started_at=row.started_at,
            last_activity_at=row.last_activity_at,
            completed_at=row.completed_at,
            abandoned_at=row.abandoned_at,
            recommended_item_count=row.recommended_item_count,
            completed_item_count=row.completed_item_count,
            correct_item_count=row.correct_item_count,
            total_score=float(row.total_score),
            maximum_score=float(row.maximum_score),
            policy_version=row.policy_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored learning session row '{row.session_id}' could not be mapped to a "
            "domain LearningSession."
        ) from exc


def learning_session_activity_orm_to_domain(
    row: LearningSessionActivityORM,
) -> LearningSessionActivity:
    try:
        return LearningSessionActivity(
            activity_id=row.activity_id,
            session_id=row.session_id,
            learner_id=row.learner_id,
            exercise_id=row.exercise_id,
            attempt_id=row.attempt_id,
            decision_id=row.decision_id,
            position=row.position,
            recommended_at=row.recommended_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            skipped_at=row.skipped_at,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored session activity row '{row.activity_id}' could not be mapped to a "
            "domain LearningSessionActivity."
        ) from exc


def diagnostic_assessment_orm_to_domain(
    row: DiagnosticAssessmentORM, skill_ids: list[UUID]
) -> DiagnosticAssessment:
    try:
        return DiagnosticAssessment(
            assessment_id=row.assessment_id,
            learner_id=row.learner_id,
            status=DiagnosticAssessmentStatus(row.status),
            skill_ids=skill_ids,
            maximum_items=row.maximum_items,
            started_at=row.started_at,
            completed_at=row.completed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            policy_version=row.policy_version,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored diagnostic assessment row '{row.assessment_id}' could not be mapped to "
            "a domain DiagnosticAssessment."
        ) from exc


def diagnostic_assessment_item_orm_to_domain(
    row: DiagnosticAssessmentItemORM, skill_ids: list[UUID]
) -> DiagnosticAssessmentItem:
    try:
        return DiagnosticAssessmentItem(
            item_id=row.item_id,
            assessment_id=row.assessment_id,
            exercise_id=row.exercise_id,
            skill_ids=skill_ids,
            position=row.position,
            attempt_id=row.attempt_id,
            selected_at=row.selected_at,
            completed_at=row.completed_at,
            normalized_score=(
                float(row.normalized_score) if row.normalized_score is not None else None
            ),
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored diagnostic item row '{row.item_id}' could not be mapped to a domain "
            "DiagnosticAssessmentItem."
        ) from exc


def skill_review_schedule_orm_to_domain(row: SkillReviewScheduleORM) -> SkillReviewSchedule:
    try:
        return SkillReviewSchedule(
            schedule_id=row.schedule_id,
            learner_id=row.learner_id,
            skill_id=row.skill_id,
            status=ReviewScheduleStatus(row.status),
            last_reviewed_at=row.last_reviewed_at,
            next_review_at=row.next_review_at,
            review_interval_days=row.review_interval_days,
            successful_review_count=row.successful_review_count,
            failed_review_count=row.failed_review_count,
            consecutive_successful_reviews=row.consecutive_successful_reviews,
            ease_factor=float(row.ease_factor),
            calculation_version=row.calculation_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored review schedule row '{row.schedule_id}' could not be mapped to a domain "
            "SkillReviewSchedule."
        ) from exc


def adaptive_decision_orm_to_domain(
    row: AdaptiveDecisionORM,
    target_skill_ids: list[UUID],
    reason_codes: list[str],
) -> AdaptiveDecision:
    try:
        return AdaptiveDecision(
            decision_id=row.decision_id,
            learner_id=row.learner_id,
            session_id=row.session_id,
            recommendation_type=RecommendationType(row.recommendation_type),
            status=AdaptiveDecisionStatus(row.status),
            recommended_exercise_id=row.recommended_exercise_id,
            recommended_lesson_id=row.recommended_lesson_id,
            target_skill_ids=target_skill_ids,
            reason_codes=[RecommendationReason(code) for code in reason_codes],
            priority_score=float(row.priority_score),
            recommended_difficulty_score=(
                float(row.recommended_difficulty_score)
                if row.recommended_difficulty_score is not None
                else None
            ),
            policy_version=row.policy_version,
            explanation=row.explanation,
            input_snapshot=dict(row.input_snapshot or {}),
            generated_at=row.generated_at,
            accepted_at=row.accepted_at,
            completed_at=row.completed_at,
            skipped_at=row.skipped_at,
            expires_at=row.expires_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored adaptive decision row '{row.decision_id}' could not be mapped to a "
            "domain AdaptiveDecision."
        ) from exc
