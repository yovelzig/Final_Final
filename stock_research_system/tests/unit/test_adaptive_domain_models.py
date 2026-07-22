"""Unit tests for the adaptive-learning domain models and their validation rules.

Pure Pydantic model tests: no SQLAlchemy, no fakes, no I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

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

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# ExerciseAdaptiveProfile
# ---------------------------------------------------------------------------


def test_adaptive_profile_accepts_valid_fields() -> None:
    profile = ExerciseAdaptiveProfile(
        exercise_id=uuid4(),
        base_difficulty_score=0.5,
        estimated_seconds=60,
        policy_tags=["Foundation", " concept-check "],
    )
    assert profile.policy_tags == ["foundation", "concept-check"]


def test_adaptive_profile_rejects_difficulty_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ExerciseAdaptiveProfile(exercise_id=uuid4(), base_difficulty_score=1.5, estimated_seconds=60)


def test_adaptive_profile_rejects_estimated_seconds_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ExerciseAdaptiveProfile(exercise_id=uuid4(), base_difficulty_score=0.5, estimated_seconds=5)
    with pytest.raises(ValidationError):
        ExerciseAdaptiveProfile(exercise_id=uuid4(), base_difficulty_score=0.5, estimated_seconds=4000)


def test_adaptive_profile_rejects_duplicate_policy_tags() -> None:
    with pytest.raises(ValidationError):
        ExerciseAdaptiveProfile(
            exercise_id=uuid4(),
            base_difficulty_score=0.5,
            estimated_seconds=60,
            policy_tags=["review", "REVIEW"],
        )


def test_adaptive_profile_rejects_inverted_mastery_range() -> None:
    with pytest.raises(ValidationError):
        ExerciseAdaptiveProfile(
            exercise_id=uuid4(),
            base_difficulty_score=0.5,
            estimated_seconds=60,
            minimum_mastery_score=0.8,
            maximum_mastery_score=0.2,
        )


def test_adaptive_profile_rejects_duplicate_prerequisite_skill_ids() -> None:
    skill_id = uuid4()
    with pytest.raises(ValidationError):
        ExerciseAdaptiveProfile(
            exercise_id=uuid4(),
            base_difficulty_score=0.5,
            estimated_seconds=60,
            recommended_prerequisite_skill_ids=[skill_id, skill_id],
        )


# ---------------------------------------------------------------------------
# LearningSession
# ---------------------------------------------------------------------------


def _session(**overrides: object) -> LearningSession:
    defaults: dict = dict(
        learner_id=uuid4(),
        goal_minutes=10,
        started_at=NOW,
        last_activity_at=NOW,
        policy_version="adaptive-policy-v1",
    )
    defaults.update(overrides)
    return LearningSession(**defaults)


def test_session_rejects_correct_exceeding_completed() -> None:
    with pytest.raises(ValidationError):
        _session(completed_item_count=1, correct_item_count=2)


def test_session_rejects_completed_exceeding_recommended_unless_free_practice() -> None:
    with pytest.raises(ValidationError):
        _session(recommended_item_count=1, completed_item_count=2)

    # FREE_PRACTICE is exempt from this rule.
    session = _session(
        session_type=LearningSessionType.FREE_PRACTICE, recommended_item_count=1, completed_item_count=2
    )
    assert session.completed_item_count == 2


def test_session_rejects_score_exceeding_maximum() -> None:
    with pytest.raises(ValidationError):
        _session(total_score=5.0, maximum_score=1.0)


def test_session_completed_requires_completed_at_and_excludes_abandoned_at() -> None:
    with pytest.raises(ValidationError):
        _session(status=LearningSessionStatus.COMPLETED)
    with pytest.raises(ValidationError):
        _session(
            status=LearningSessionStatus.COMPLETED, completed_at=NOW, abandoned_at=NOW
        )
    session = _session(status=LearningSessionStatus.COMPLETED, completed_at=NOW)
    assert session.completed_at == NOW


def test_session_abandoned_requires_abandoned_at() -> None:
    with pytest.raises(ValidationError):
        _session(status=LearningSessionStatus.ABANDONED)


def test_session_rejects_completed_at_before_started_at() -> None:
    with pytest.raises(ValidationError):
        _session(
            status=LearningSessionStatus.COMPLETED,
            completed_at=NOW - timedelta(days=1),
        )


# ---------------------------------------------------------------------------
# LearningSessionActivity
# ---------------------------------------------------------------------------


def _activity(**overrides: object) -> LearningSessionActivity:
    defaults: dict = dict(
        session_id=uuid4(),
        learner_id=uuid4(),
        exercise_id=uuid4(),
        decision_id=uuid4(),
        position=1,
        recommended_at=NOW,
    )
    defaults.update(overrides)
    return LearningSessionActivity(**defaults)


def test_activity_requires_positive_position() -> None:
    with pytest.raises(ValidationError):
        _activity(position=0)


def test_activity_rejects_both_completed_and_skipped() -> None:
    with pytest.raises(ValidationError):
        _activity(completed_at=NOW, skipped_at=NOW)


def test_activity_rejects_timestamps_before_recommended_at() -> None:
    earlier = NOW - timedelta(hours=1)
    with pytest.raises(ValidationError):
        _activity(completed_at=earlier)
    with pytest.raises(ValidationError):
        _activity(skipped_at=earlier)
    with pytest.raises(ValidationError):
        _activity(started_at=earlier)


# ---------------------------------------------------------------------------
# DiagnosticAssessment / DiagnosticAssessmentItem
# ---------------------------------------------------------------------------


def _assessment(**overrides: object) -> DiagnosticAssessment:
    defaults: dict = dict(
        learner_id=uuid4(), skill_ids=[uuid4()], maximum_items=10, policy_version="diagnostic-policy-v1"
    )
    defaults.update(overrides)
    return DiagnosticAssessment(**defaults)


def test_assessment_rejects_duplicate_skill_ids() -> None:
    skill_id = uuid4()
    with pytest.raises(ValidationError):
        _assessment(skill_ids=[skill_id, skill_id])


def test_assessment_in_progress_requires_started_at() -> None:
    with pytest.raises(ValidationError):
        _assessment(status=DiagnosticAssessmentStatus.IN_PROGRESS)
    assessment = _assessment(status=DiagnosticAssessmentStatus.IN_PROGRESS, started_at=NOW)
    assert assessment.started_at == NOW


def test_assessment_completed_requires_completed_at() -> None:
    with pytest.raises(ValidationError):
        _assessment(status=DiagnosticAssessmentStatus.COMPLETED, started_at=NOW)
    assessment = _assessment(
        status=DiagnosticAssessmentStatus.COMPLETED, started_at=NOW, completed_at=NOW
    )
    assert assessment.completed_at == NOW


def _item(**overrides: object) -> DiagnosticAssessmentItem:
    defaults: dict = dict(assessment_id=uuid4(), exercise_id=uuid4(), skill_ids=[uuid4()], position=1)
    defaults.update(overrides)
    return DiagnosticAssessmentItem(**defaults)


def test_item_rejects_duplicate_skill_ids() -> None:
    skill_id = uuid4()
    with pytest.raises(ValidationError):
        _item(skill_ids=[skill_id, skill_id])


def test_item_completed_requires_attempt_id_and_normalized_score() -> None:
    with pytest.raises(ValidationError):
        _item(selected_at=NOW, completed_at=NOW)
    with pytest.raises(ValidationError):
        _item(selected_at=NOW, completed_at=NOW, attempt_id=uuid4())
    item = _item(selected_at=NOW, completed_at=NOW, attempt_id=uuid4(), normalized_score=0.8)
    assert item.normalized_score == 0.8


def test_item_rejects_completed_at_before_selected_at() -> None:
    with pytest.raises(ValidationError):
        _item(
            selected_at=NOW,
            completed_at=NOW - timedelta(hours=1),
            attempt_id=uuid4(),
            normalized_score=0.5,
        )


# ---------------------------------------------------------------------------
# SkillReviewSchedule
# ---------------------------------------------------------------------------


def _schedule(**overrides: object) -> SkillReviewSchedule:
    defaults: dict = dict(
        learner_id=uuid4(),
        skill_id=uuid4(),
        review_interval_days=1,
        ease_factor=2.0,
        calculation_version="review-schedule-v1",
    )
    defaults.update(overrides)
    return SkillReviewSchedule(**defaults)


def test_schedule_rejects_ease_factor_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _schedule(ease_factor=0.5)
    with pytest.raises(ValidationError):
        _schedule(ease_factor=3.5)


def test_schedule_requires_next_review_at_when_scheduled() -> None:
    with pytest.raises(ValidationError):
        _schedule(status=ReviewScheduleStatus.SCHEDULED)
    schedule = _schedule(status=ReviewScheduleStatus.SCHEDULED, next_review_at=NOW)
    assert schedule.next_review_at == NOW


def test_schedule_rejects_next_review_at_before_last_reviewed_at() -> None:
    with pytest.raises(ValidationError):
        _schedule(
            status=ReviewScheduleStatus.SCHEDULED,
            last_reviewed_at=NOW,
            next_review_at=NOW - timedelta(days=1),
        )


# ---------------------------------------------------------------------------
# AdaptiveDecision
# ---------------------------------------------------------------------------


def _decision(**overrides: object) -> AdaptiveDecision:
    defaults: dict = dict(
        learner_id=uuid4(),
        recommendation_type=RecommendationType.PRACTICE_EXERCISE,
        recommended_exercise_id=uuid4(),
        priority_score=0.5,
        policy_version="adaptive-policy-v1",
        explanation="explanation",
    )
    defaults.update(overrides)
    return AdaptiveDecision(**defaults)


def test_decision_requires_a_target_unless_session_complete_or_no_content() -> None:
    with pytest.raises(ValidationError):
        _decision(recommendation_type=RecommendationType.PRACTICE_EXERCISE, recommended_exercise_id=None)

    # These two types are explicitly exempt from requiring a target.
    for recommendation_type in (RecommendationType.SESSION_COMPLETE, RecommendationType.NO_ELIGIBLE_CONTENT):
        decision = _decision(recommendation_type=recommendation_type, recommended_exercise_id=None)
        assert decision.recommended_exercise_id is None


def test_decision_rejects_duplicate_target_skill_ids() -> None:
    skill_id = uuid4()
    with pytest.raises(ValidationError):
        _decision(target_skill_ids=[skill_id, skill_id])


def test_decision_rejects_duplicate_reason_codes() -> None:
    with pytest.raises(ValidationError):
        _decision(
            reason_codes=[RecommendationReason.LOW_MASTERY, RecommendationReason.LOW_MASTERY]
        )


def test_decision_accepted_requires_accepted_at() -> None:
    with pytest.raises(ValidationError):
        _decision(status=AdaptiveDecisionStatus.ACCEPTED)
    decision = _decision(status=AdaptiveDecisionStatus.ACCEPTED, accepted_at=NOW)
    assert decision.accepted_at == NOW


def test_decision_completed_requires_completed_at() -> None:
    with pytest.raises(ValidationError):
        _decision(status=AdaptiveDecisionStatus.COMPLETED)


def test_decision_skipped_requires_skipped_at() -> None:
    with pytest.raises(ValidationError):
        _decision(status=AdaptiveDecisionStatus.SKIPPED)


def test_decision_rejects_both_completed_and_skipped() -> None:
    with pytest.raises(ValidationError):
        _decision(
            status=AdaptiveDecisionStatus.COMPLETED, completed_at=NOW, skipped_at=NOW
        )


def test_decision_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        AdaptiveDecision(
            learner_id=uuid4(),
            recommendation_type=RecommendationType.SESSION_COMPLETE,
            priority_score=1.0,
            policy_version="adaptive-policy-v1",
            explanation="explanation",
            not_a_real_field="oops",
        )
