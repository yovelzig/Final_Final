"""Unit tests for `RuleBasedDiagnosticPolicy` (diagnostic-policy-v1)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.adaptive_learning.models import ExerciseCandidate
from stock_research_core.application.adaptive_learning.policies import RuleBasedDiagnosticPolicy
from stock_research_core.domain.adaptive_learning.enums import DiagnosticSkillResult
from stock_research_core.domain.adaptive_learning.models import (
    DiagnosticAssessment,
    DiagnosticAssessmentItem,
    ExerciseAdaptiveProfile,
)
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import Exercise, SkillMastery

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = RuleBasedDiagnosticPolicy()


def _exercise(skill_ids: list, difficulty_score: float = 0.5) -> tuple[Exercise, ExerciseAdaptiveProfile]:
    exercise = Exercise(
        lesson_id=uuid4(),
        exercise_type=ExerciseType.SINGLE_CHOICE,
        prompt="prompt",
        explanation="explanation",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        skill_ids=skill_ids,
        maximum_score=1.0,
        passing_score=1.0,
    )
    profile = ExerciseAdaptiveProfile(
        exercise_id=exercise.exercise_id,
        base_difficulty_score=difficulty_score,
        estimated_seconds=45,
        diagnostic_eligible=True,
    )
    return exercise, profile


def _candidate(skill_ids: list, difficulty_score: float = 0.5, recent_attempt_count: int = 0) -> ExerciseCandidate:
    exercise, profile = _exercise(skill_ids, difficulty_score)
    return ExerciseCandidate(
        exercise=exercise,
        adaptive_profile=profile,
        lesson_position=0,
        recent_attempt_count=recent_attempt_count,
    )


def test_policy_version_is_stable() -> None:
    assert POLICY.policy_version == "diagnostic-policy-v1"


@pytest.mark.asyncio
async def test_select_items_round_robins_across_skills() -> None:
    skill_a, skill_b = uuid4(), uuid4()
    candidates = [
        _candidate([skill_a]),
        _candidate([skill_a]),
        _candidate([skill_b]),
        _candidate([skill_b]),
    ]

    items = await POLICY.select_items(
        learner_id=uuid4(), skill_ids=[skill_a, skill_b], candidates=candidates, maximum_items=2, now=NOW
    )

    assert len(items) == 2
    selected_skills = [item.skill_ids[0] for item in items]
    # Breadth-first: one item per skill before a second item for either.
    assert set(selected_skills) == {skill_a, skill_b}


@pytest.mark.asyncio
async def test_select_items_prefers_unattempted_candidates() -> None:
    skill_a = uuid4()
    attempted = _candidate([skill_a], difficulty_score=0.5, recent_attempt_count=3)
    unattempted = _candidate([skill_a], difficulty_score=0.9, recent_attempt_count=0)

    items = await POLICY.select_items(
        learner_id=uuid4(),
        skill_ids=[skill_a],
        candidates=[attempted, unattempted],
        maximum_items=1,
        now=NOW,
    )

    assert items[0].exercise_id == unattempted.exercise.exercise_id


@pytest.mark.asyncio
async def test_select_items_prefers_difficulty_closest_to_half() -> None:
    skill_a = uuid4()
    far = _candidate([skill_a], difficulty_score=0.95)
    close = _candidate([skill_a], difficulty_score=0.55)

    items = await POLICY.select_items(
        learner_id=uuid4(), skill_ids=[skill_a], candidates=[far, close], maximum_items=1, now=NOW
    )

    assert items[0].exercise_id == close.exercise.exercise_id


@pytest.mark.asyncio
async def test_select_items_uses_placeholder_assessment_id() -> None:
    skill_a = uuid4()
    items = await POLICY.select_items(
        learner_id=uuid4(), skill_ids=[skill_a], candidates=[_candidate([skill_a])], maximum_items=1, now=NOW
    )
    # A real assessment does not exist yet - caller must rewrite this ID.
    assert items[0].assessment_id is not None


@pytest.mark.asyncio
async def test_select_items_is_deterministic() -> None:
    skill_a, skill_b = uuid4(), uuid4()
    candidates = [_candidate([skill_a]), _candidate([skill_b]), _candidate([skill_a, skill_b])]

    first = await POLICY.select_items(
        learner_id=uuid4(), skill_ids=[skill_a, skill_b], candidates=candidates, maximum_items=3, now=NOW
    )
    second = await POLICY.select_items(
        learner_id=uuid4(), skill_ids=[skill_a, skill_b], candidates=candidates, maximum_items=3, now=NOW
    )
    assert [item.exercise_id for item in first] == [item.exercise_id for item in second]


def _assessment(skill_ids: list) -> DiagnosticAssessment:
    return DiagnosticAssessment(
        learner_id=uuid4(), skill_ids=skill_ids, maximum_items=10, policy_version=POLICY.policy_version
    )


def _completed_item(assessment_id, skill_ids: list, normalized_score: float) -> DiagnosticAssessmentItem:
    return DiagnosticAssessmentItem(
        assessment_id=assessment_id,
        exercise_id=uuid4(),
        skill_ids=skill_ids,
        position=1,
        selected_at=NOW,
        completed_at=NOW,
        attempt_id=uuid4(),
        normalized_score=normalized_score,
    )


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.10, DiagnosticSkillResult.NEEDS_FOUNDATION),
        (0.45, DiagnosticSkillResult.DEVELOPING),
        (0.70, DiagnosticSkillResult.READY),
        (0.95, DiagnosticSkillResult.STRONG),
    ],
)
def test_summarize_classifies_skill_score(score: float, expected: DiagnosticSkillResult) -> None:
    skill_id = uuid4()
    assessment = _assessment([skill_id])
    items = [_completed_item(assessment.assessment_id, [skill_id], score)]

    summary = POLICY.summarize(assessment=assessment, items=items)

    assert summary.skill_results[skill_id] == expected
    assert summary.skill_scores[skill_id] == score


def test_summarize_marks_untouched_skills_as_not_assessed() -> None:
    skill_id = uuid4()
    assessment = _assessment([skill_id])

    summary = POLICY.summarize(assessment=assessment, items=[])

    assert summary.skill_results[skill_id] == DiagnosticSkillResult.NOT_ASSESSED
    assert skill_id not in summary.skill_scores
    assert summary.recommended_starting_skill_ids == [skill_id]


def test_summarize_recommends_needs_foundation_skills_first() -> None:
    weak_skill, strong_skill = uuid4(), uuid4()
    assessment = _assessment([weak_skill, strong_skill])
    items = [
        _completed_item(assessment.assessment_id, [weak_skill], 0.1),
        _completed_item(assessment.assessment_id, [strong_skill], 0.95),
    ]

    summary = POLICY.summarize(assessment=assessment, items=items)

    assert summary.recommended_starting_skill_ids == [weak_skill]


def test_compute_initial_mastery_new_skill_uses_raw_diagnostic_score() -> None:
    mastery = POLICY.compute_initial_mastery(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        diagnostic_score=0.7,
        diagnostic_item_count=1,
        now=NOW,
    )
    assert mastery.mastery_score == 0.7
    assert mastery.calculation_version == "diagnostic-policy-v1+mastery-blend-v1"


def test_compute_initial_mastery_blends_with_previous() -> None:
    previous = SkillMastery(
        learner_id=uuid4(),
        skill_id=uuid4(),
        mastery_score=0.5,
        total_attempts=2,
        correct_attempts=1,
        calculation_version="mastery-v1",
    )
    mastery = POLICY.compute_initial_mastery(
        learner_id=previous.learner_id,
        skill_id=previous.skill_id,
        previous=previous,
        diagnostic_score=0.9,
        diagnostic_item_count=1,
        now=NOW,
    )
    expected = 0.6 * 0.5 + 0.4 * 0.9
    assert mastery.mastery_score == pytest.approx(expected)
    assert mastery.mastery_id == previous.mastery_id


def test_compute_initial_mastery_requires_three_items_and_high_score_for_mastered() -> None:
    # Score is high enough but too few diagnostic items - should not be MASTERED.
    from stock_research_core.domain.learning.enums import MasteryLevel

    mastery = POLICY.compute_initial_mastery(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        diagnostic_score=0.95,
        diagnostic_item_count=1,
        now=NOW,
    )
    assert mastery.mastery_level != MasteryLevel.MASTERED

    mastery = POLICY.compute_initial_mastery(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        diagnostic_score=0.95,
        diagnostic_item_count=3,
        now=NOW,
    )
    assert mastery.mastery_level == MasteryLevel.MASTERED
