"""Unit tests for `DeterministicReviewSchedulingPolicy` (review-schedule-v1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from stock_research_core.application.adaptive_learning.policies import (
    DeterministicReviewSchedulingPolicy,
)
from stock_research_core.domain.adaptive_learning.enums import ReviewScheduleStatus
from stock_research_core.domain.learning.enums import ConfidenceLevel

POLICY = DeterministicReviewSchedulingPolicy()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_policy_version_is_stable() -> None:
    assert POLICY.policy_version == "review-schedule-v1"


def test_first_review_incorrect_schedules_one_day() -> None:
    schedule = POLICY.update_schedule(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        normalized_score=0.2,
        confidence_level=None,
        practiced_at=NOW,
    )
    assert schedule.review_interval_days == 1
    assert schedule.next_review_at == NOW + timedelta(days=1)
    assert schedule.status == ReviewScheduleStatus.SCHEDULED
    assert schedule.failed_review_count == 1
    assert schedule.successful_review_count == 0
    assert schedule.consecutive_successful_reviews == 0
    assert schedule.ease_factor == 2.0
    assert schedule.calculation_version == "review-schedule-v1"


def test_first_review_partial_schedules_two_days() -> None:
    schedule = POLICY.update_schedule(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        normalized_score=0.65,
        confidence_level=None,
        practiced_at=NOW,
    )
    assert schedule.review_interval_days == 2
    assert schedule.failed_review_count == 1
    assert schedule.successful_review_count == 0


def test_first_review_correct_schedules_by_confidence() -> None:
    low_confidence = POLICY.update_schedule(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        normalized_score=0.9,
        confidence_level=None,
        practiced_at=NOW,
    )
    assert low_confidence.review_interval_days == 3

    medium_confidence = POLICY.update_schedule(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        normalized_score=0.9,
        confidence_level=ConfidenceLevel.MEDIUM,
        practiced_at=NOW,
    )
    assert medium_confidence.review_interval_days == 5

    high_confidence = POLICY.update_schedule(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        normalized_score=0.9,
        confidence_level=ConfidenceLevel.HIGH,
        practiced_at=NOW,
    )
    assert high_confidence.review_interval_days == 7
    assert high_confidence.successful_review_count == 1
    assert high_confidence.consecutive_successful_reviews == 1


def test_successful_followup_grows_interval_using_ease_factor() -> None:
    learner_id, skill_id = uuid4(), uuid4()
    first = POLICY.update_schedule(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=None,
        normalized_score=0.9,
        confidence_level=None,
        practiced_at=NOW,
    )
    second = POLICY.update_schedule(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=first,
        normalized_score=0.85,
        confidence_level=None,
        practiced_at=NOW + timedelta(days=3),
    )
    assert second.ease_factor == first.ease_factor  # not a strong (high-confidence) result
    assert second.review_interval_days == round(first.review_interval_days * second.ease_factor)
    assert second.successful_review_count == 2
    assert second.consecutive_successful_reviews == 2
    assert second.schedule_id == first.schedule_id


def test_strong_confidence_success_increases_ease_factor() -> None:
    learner_id, skill_id = uuid4(), uuid4()
    first = POLICY.update_schedule(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=None,
        normalized_score=0.9,
        confidence_level=None,
        practiced_at=NOW,
    )
    second = POLICY.update_schedule(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=first,
        normalized_score=0.95,
        confidence_level=ConfidenceLevel.VERY_HIGH,
        practiced_at=NOW + timedelta(days=3),
    )
    assert second.ease_factor == first.ease_factor + 0.10


def test_failure_after_previous_success_resets_streak() -> None:
    learner_id, skill_id = uuid4(), uuid4()
    first = POLICY.update_schedule(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=None,
        normalized_score=0.9,
        confidence_level=None,
        practiced_at=NOW,
    )
    failed = POLICY.update_schedule(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=first,
        normalized_score=0.2,
        confidence_level=None,
        practiced_at=NOW + timedelta(days=3),
    )
    assert failed.review_interval_days == 1
    assert failed.consecutive_successful_reviews == 0
    assert failed.failed_review_count == first.failed_review_count + 1
    assert failed.ease_factor == first.ease_factor - 0.20


def test_partial_failure_decreases_ease_factor_less_than_incorrect() -> None:
    learner_id, skill_id = uuid4(), uuid4()
    first = POLICY.update_schedule(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=None,
        normalized_score=0.9,
        confidence_level=None,
        practiced_at=NOW,
    )
    partial = POLICY.update_schedule(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=first,
        normalized_score=0.65,
        confidence_level=None,
        practiced_at=NOW + timedelta(days=3),
    )
    assert partial.ease_factor == first.ease_factor - 0.10


def test_ease_factor_is_clamped_to_bounds() -> None:
    learner_id, skill_id = uuid4(), uuid4()
    schedule = None
    practiced_at = NOW
    # Repeated incorrect results should never push ease factor below 1.3.
    for _ in range(20):
        schedule = POLICY.update_schedule(
            learner_id=learner_id,
            skill_id=skill_id,
            previous=schedule,
            normalized_score=0.1,
            confidence_level=None,
            practiced_at=practiced_at,
        )
        practiced_at += timedelta(days=1)
    assert schedule.ease_factor >= 1.3

    schedule = None
    practiced_at = NOW
    # The first call seeds ease_factor at the 2.0 default (no increment);
    # each of the next 8 strong-confidence successes adds +0.10, reaching
    # the 2.8 ceiling exactly. Interval also compounds each round, so keep
    # the loop short to avoid an unrealistic multi-century `next_review_at`
    # that would overflow `datetime`.
    for _ in range(9):
        schedule = POLICY.update_schedule(
            learner_id=learner_id,
            skill_id=skill_id,
            previous=schedule,
            normalized_score=0.99,
            confidence_level=ConfidenceLevel.VERY_HIGH,
            practiced_at=practiced_at,
        )
        practiced_at += timedelta(days=1)
    assert schedule.ease_factor == 2.8


def test_update_is_deterministic_for_identical_inputs() -> None:
    learner_id, skill_id = uuid4(), uuid4()
    kwargs = dict(
        learner_id=learner_id,
        skill_id=skill_id,
        previous=None,
        normalized_score=0.8,
        confidence_level=ConfidenceLevel.MEDIUM,
        practiced_at=NOW,
    )
    first = POLICY.update_schedule(**kwargs)
    second = POLICY.update_schedule(**kwargs)
    assert first.model_dump(exclude={"schedule_id"}) == second.model_dump(exclude={"schedule_id"})
