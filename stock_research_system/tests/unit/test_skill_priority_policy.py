"""Unit tests for `RuleBasedAdaptivePolicy` (adaptive-policy-v1): priority
tiers, weighted scoring, tie-breaking, and explanations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.adaptive_learning.models import (
    AdaptiveLearnerState,
    ExerciseCandidate,
)
from stock_research_core.application.adaptive_learning.policies import (
    COMPONENT_WEIGHTS,
    RuleBasedAdaptivePolicy,
)
from stock_research_core.domain.adaptive_learning.enums import RecommendationType
from stock_research_core.domain.adaptive_learning.models import ExerciseAdaptiveProfile
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import Exercise, LearnerProfile

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = RuleBasedAdaptivePolicy()


def test_component_weights_sum_to_one() -> None:
    assert abs(sum(COMPONENT_WEIGHTS.values()) - 1.0) < 1e-9


def _learner_state(learner_id=None) -> AdaptiveLearnerState:
    return AdaptiveLearnerState(learner=LearnerProfile(learner_id=learner_id or uuid4(), display_name="L"))


def _candidate(
    *,
    lesson_id=None,
    lesson_position: int = 0,
    position: int = 0,
    skill_ids: list | None = None,
    has_active_misconception: bool = False,
    is_overdue_review: bool = False,
    prerequisites_satisfied: bool = True,
    recent_attempt_count: int = 0,
    recent_correct_rate: float | None = None,
    skill_mastery_scores: dict | None = None,
) -> ExerciseCandidate:
    resolved_skill_ids = skill_ids or [uuid4()]
    exercise = Exercise(
        lesson_id=lesson_id or uuid4(),
        exercise_type=ExerciseType.SINGLE_CHOICE,
        prompt="prompt",
        explanation="explanation",
        difficulty=DifficultyLevel.BEGINNER,
        position=position,
        skill_ids=resolved_skill_ids,
        maximum_score=1.0,
        passing_score=1.0,
    )
    profile = ExerciseAdaptiveProfile(
        exercise_id=exercise.exercise_id, base_difficulty_score=0.5, estimated_seconds=45
    )
    # Default to high mastery for every one of the exercise's skills unless
    # the caller overrides it - an *unspecified* mastery score defaults to
    # 0.0 in the policy itself (an unassessed skill looks like a mastery
    # gap by design), which would otherwise make every candidate here look
    # like a LOW_MASTERY tier candidate regardless of what a test intends.
    resolved_mastery_scores = (
        skill_mastery_scores
        if skill_mastery_scores is not None
        else {skill_id: 0.9 for skill_id in resolved_skill_ids}
    )
    return ExerciseCandidate(
        exercise=exercise,
        adaptive_profile=profile,
        lesson_position=lesson_position,
        has_active_misconception=has_active_misconception,
        is_overdue_review=is_overdue_review,
        prerequisites_satisfied=prerequisites_satisfied,
        recent_attempt_count=recent_attempt_count,
        recent_correct_rate=recent_correct_rate,
        skill_mastery_scores=resolved_mastery_scores,
    )


def test_policy_version_is_stable() -> None:
    assert POLICY.policy_version == "adaptive-policy-v1"


@pytest.mark.asyncio
async def test_no_candidates_yields_no_eligible_content() -> None:
    decision = await POLICY.recommend(state=_learner_state(), candidates=[], now=NOW)
    assert decision.recommendation_type == RecommendationType.NO_ELIGIBLE_CONTENT
    assert decision.priority_score == 0.0


@pytest.mark.asyncio
async def test_misconception_candidate_always_wins() -> None:
    misconception_candidate = _candidate(has_active_misconception=True)
    overdue_candidate = _candidate(is_overdue_review=True)
    low_mastery_candidate = _candidate(skill_mastery_scores={})

    decision = await POLICY.recommend(
        state=_learner_state(),
        candidates=[low_mastery_candidate, overdue_candidate, misconception_candidate],
        now=NOW,
    )

    assert decision.recommended_exercise_id == misconception_candidate.exercise.exercise_id
    assert decision.recommendation_type == RecommendationType.MISCONCEPTION_REMEDIATION


@pytest.mark.asyncio
async def test_overdue_review_beats_prerequisite_and_new_content() -> None:
    overdue_candidate = _candidate(is_overdue_review=True)
    prerequisite_candidate = _candidate(prerequisites_satisfied=False)
    new_content_candidate = _candidate()

    decision = await POLICY.recommend(
        state=_learner_state(),
        candidates=[new_content_candidate, prerequisite_candidate, overdue_candidate],
        now=NOW,
    )

    assert decision.recommended_exercise_id == overdue_candidate.exercise.exercise_id
    assert decision.recommendation_type == RecommendationType.REVIEW_EXERCISE


@pytest.mark.asyncio
async def test_prerequisite_gap_beats_recent_failure_and_low_mastery() -> None:
    prerequisite_candidate = _candidate(prerequisites_satisfied=False)
    failure_skill = uuid4()
    failure_candidate = _candidate(
        skill_ids=[failure_skill], recent_attempt_count=3, recent_correct_rate=0.2
    )

    decision = await POLICY.recommend(
        state=_learner_state(), candidates=[failure_candidate, prerequisite_candidate], now=NOW
    )

    assert decision.recommended_exercise_id == prerequisite_candidate.exercise.exercise_id
    assert decision.recommendation_type == RecommendationType.PREREQUISITE_REVIEW


@pytest.mark.asyncio
async def test_recent_failure_beats_low_mastery_and_new_content() -> None:
    failure_skill = uuid4()
    failure_candidate = _candidate(
        skill_ids=[failure_skill],
        recent_attempt_count=3,
        recent_correct_rate=0.2,
        skill_mastery_scores={failure_skill: 0.9},  # high mastery, so it isn't ALSO a low-mastery tier
    )
    new_content_candidate = _candidate()

    decision = await POLICY.recommend(
        state=_learner_state(), candidates=[new_content_candidate, failure_candidate], now=NOW
    )

    assert decision.recommended_exercise_id == failure_candidate.exercise.exercise_id
    assert decision.reason_codes[0].value == "RECENT_FAILURE"


@pytest.mark.asyncio
async def test_low_mastery_beats_incomplete_lesson_and_new_content() -> None:
    low_mastery_skill = uuid4()
    low_mastery_candidate = _candidate(
        skill_ids=[low_mastery_skill], skill_mastery_scores={low_mastery_skill: 0.1}
    )
    high_mastery_candidate = _candidate()

    decision = await POLICY.recommend(
        state=_learner_state(), candidates=[high_mastery_candidate, low_mastery_candidate], now=NOW
    )

    assert decision.recommended_exercise_id == low_mastery_candidate.exercise.exercise_id
    assert decision.reason_codes[0].value == "LOW_MASTERY"


@pytest.mark.asyncio
async def test_new_content_is_the_lowest_priority_tier() -> None:
    only_candidate = _candidate()
    decision = await POLICY.recommend(state=_learner_state(), candidates=[only_candidate], now=NOW)
    assert decision.recommendation_type == RecommendationType.NEW_LESSON
    assert decision.reason_codes[0].value == "NEW_CONTENT"


@pytest.mark.asyncio
async def test_tie_break_prefers_lower_lesson_position() -> None:
    first_lesson = _candidate(lesson_position=0, position=5)
    second_lesson = _candidate(lesson_position=1, position=0)

    decision = await POLICY.recommend(
        state=_learner_state(), candidates=[second_lesson, first_lesson], now=NOW
    )

    assert decision.recommended_exercise_id == first_lesson.exercise.exercise_id


@pytest.mark.asyncio
async def test_tie_break_prefers_lower_exercise_position_within_same_lesson() -> None:
    lesson_id = uuid4()
    earlier = _candidate(lesson_id=lesson_id, lesson_position=0, position=0)
    later = _candidate(lesson_id=lesson_id, lesson_position=0, position=1)

    decision = await POLICY.recommend(state=_learner_state(), candidates=[later, earlier], now=NOW)

    assert decision.recommended_exercise_id == earlier.exercise.exercise_id


@pytest.mark.asyncio
async def test_decision_is_auditable_with_versioned_snapshot() -> None:
    candidate = _candidate()
    decision = await POLICY.recommend(state=_learner_state(), candidates=[candidate], now=NOW)

    assert decision.policy_version == "adaptive-policy-v1"
    assert decision.input_snapshot["policy_version"] == "adaptive-policy-v1"
    assert "components" in decision.input_snapshot
    assert decision.input_snapshot["weights"] == COMPONENT_WEIGHTS
    assert decision.explanation


@pytest.mark.asyncio
async def test_recommendation_is_deterministic_for_identical_inputs() -> None:
    skill_id = uuid4()
    candidates = [
        _candidate(skill_ids=[skill_id], skill_mastery_scores={skill_id: 0.2}),
        _candidate(is_overdue_review=True),
    ]
    state = _learner_state()

    first = await POLICY.recommend(state=state, candidates=candidates, now=NOW)
    second = await POLICY.recommend(state=state, candidates=candidates, now=NOW)

    assert first.recommended_exercise_id == second.recommended_exercise_id
    assert first.priority_score == second.priority_score
    assert first.recommendation_type == second.recommendation_type
