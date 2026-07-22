"""Deterministic, versioned adaptive-learning policies.

No machine learning, no LLM calls, no randomness: every decision here
is produced by explicit, documented rules over already-gathered state.
Each policy implements one of the Protocols in `ports.py` so a future
ML-based policy can be substituted without touching
`AdaptiveLearningService`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from stock_research_core.application.adaptive_learning.models import (
    AdaptiveLearnerState,
    DiagnosticSummary,
    ExerciseCandidate,
)
from stock_research_core.domain.adaptive_learning.enums import (
    AdaptiveDecisionStatus,
    DifficultyAdjustment,
    DiagnosticSkillResult,
    RecommendationReason,
    RecommendationType,
    ReviewScheduleStatus,
)
from stock_research_core.domain.adaptive_learning.models import (
    AdaptiveDecision,
    DiagnosticAssessment,
    DiagnosticAssessmentItem,
    SkillReviewSchedule,
)
from stock_research_core.domain.learning.enums import ConfidenceLevel, MasteryLevel
from stock_research_core.domain.learning.models import SkillMastery

# ---------------------------------------------------------------------------
# RuleBasedDifficultyPolicy
# ---------------------------------------------------------------------------


class RuleBasedDifficultyPolicy:
    """difficulty-policy-v1: deterministic difficulty targeting.

    Base target by mastery score:
        < 0.30            -> 0.20 (BEGINNER/EASY band)
        0.30 - 0.60        -> 0.40 (EASY/MEDIUM band)
        0.60 - 0.85        -> 0.60 (MEDIUM/HARD band)
        >= 0.85            -> 0.80 (HARD/ADVANCED band)

    Adjustments, applied in order (a decrease always takes precedence
    over a potential increase - a learner cannot be both struggling and
    on a winning streak in the same evaluation):
        - 2+ consecutive incorrect answers: -0.15 (DECREASE)
        - incorrect with HIGH/VERY_HIGH confidence (i.e. a confident
          wrong answer, a likely misconception signal): additional
          -0.10 (DECREASE)
        - otherwise, 3+ consecutive correct answers: +0.10 (INCREASE) -
          unless confidence is LOW/VERY_LOW, in which case difficulty
          is never increased on the strength of an uncertain streak.

    Final score is clamped to [0, 1].
    """

    policy_version = "difficulty-policy-v1"

    _LOW_MASTERY_TARGET = 0.20
    _MEDIUM_MASTERY_TARGET = 0.40
    _HIGH_MASTERY_TARGET = 0.60
    _VERY_HIGH_MASTERY_TARGET = 0.80

    _CONSECUTIVE_INCORRECT_THRESHOLD = 2
    _CONSECUTIVE_CORRECT_THRESHOLD = 3
    _INCORRECT_STREAK_PENALTY = 0.15
    _CORRECT_STREAK_BONUS = 0.10
    _HIGH_CONFIDENCE_MISS_PENALTY = 0.10

    _LOW_CONFIDENCE_LEVELS = frozenset({ConfidenceLevel.LOW, ConfidenceLevel.VERY_LOW})
    _HIGH_CONFIDENCE_LEVELS = frozenset({ConfidenceLevel.HIGH, ConfidenceLevel.VERY_HIGH})

    def recommend_difficulty(
        self,
        *,
        mastery_score: float,
        recent_correct_rate: float | None,
        consecutive_correct: int,
        consecutive_incorrect: int,
        confidence_level: ConfidenceLevel | None,
    ) -> tuple[float, DifficultyAdjustment]:
        if mastery_score < 0.30:
            target = self._LOW_MASTERY_TARGET
        elif mastery_score < 0.60:
            target = self._MEDIUM_MASTERY_TARGET
        elif mastery_score < 0.85:
            target = self._HIGH_MASTERY_TARGET
        else:
            target = self._VERY_HIGH_MASTERY_TARGET

        adjustment = DifficultyAdjustment.KEEP
        decreased = False

        if consecutive_incorrect >= self._CONSECUTIVE_INCORRECT_THRESHOLD:
            target -= self._INCORRECT_STREAK_PENALTY
            adjustment = DifficultyAdjustment.DECREASE
            decreased = True

        if confidence_level in self._HIGH_CONFIDENCE_LEVELS and consecutive_incorrect > 0:
            target -= self._HIGH_CONFIDENCE_MISS_PENALTY
            adjustment = DifficultyAdjustment.DECREASE
            decreased = True

        if (
            not decreased
            and consecutive_correct >= self._CONSECUTIVE_CORRECT_THRESHOLD
            and confidence_level not in self._LOW_CONFIDENCE_LEVELS
        ):
            target += self._CORRECT_STREAK_BONUS
            adjustment = DifficultyAdjustment.INCREASE

        clamped = max(0.0, min(1.0, target))
        return clamped, adjustment


# ---------------------------------------------------------------------------
# DeterministicReviewSchedulingPolicy
# ---------------------------------------------------------------------------


class DeterministicReviewSchedulingPolicy:
    """review-schedule-v1: transparent spaced-repetition rules.

    Not a full proprietary spaced-repetition algorithm - a simple,
    documented rule set. Future versions may use more sophisticated
    spacing without changing the persisted schema.

    First review for a skill (no previous schedule), chosen from the
    latest graded result:
        score < 0.50                              -> 1 day
        0.50 <= score < 0.80                       -> 2 days
        score >= 0.80, confidence LOW/None         -> 3 days
        score >= 0.80, confidence MEDIUM           -> 5 days
        score >= 0.80, confidence HIGH/VERY_HIGH   -> 7 days

    Later reviews, on a successful result (score >= 0.80):
        new_interval = max(first_review_interval(score, confidence),
                            round(previous_interval * new_ease_factor))
        ease_factor: +0.10 for a strong (HIGH/VERY_HIGH confidence)
                     result, unchanged for a correct-but-low-confidence
                     result.
        successful_review_count += 1; consecutive_successful += 1.

    Later reviews, on an unsuccessful result (score < 0.80):
        next review in 1 day; consecutive_successful reset to 0;
        failed_review_count += 1.
        ease_factor: -0.10 for a partial result (0.50 <= score < 0.80),
                     -0.20 for an incorrect result (score < 0.50).

    Ease factor is always clamped to [1.3, 2.8].
    """

    policy_version = "review-schedule-v1"

    _INCORRECT_THRESHOLD = 0.50
    _SUCCESS_THRESHOLD = 0.80

    _FIRST_INCORRECT_DAYS = 1
    _FIRST_PARTIAL_DAYS = 2
    _FIRST_CORRECT_LOW_DAYS = 3
    _FIRST_CORRECT_MEDIUM_DAYS = 5
    _FIRST_CORRECT_HIGH_DAYS = 7

    _EASE_MIN = 1.3
    _EASE_MAX = 2.8
    _DEFAULT_EASE = 2.0

    _EASE_INCREASE_STRONG = 0.10
    _EASE_DECREASE_PARTIAL = 0.10
    _EASE_DECREASE_INCORRECT = 0.20

    _HIGH_CONFIDENCE_LEVELS = frozenset({ConfidenceLevel.HIGH, ConfidenceLevel.VERY_HIGH})

    def _first_review_interval_days(
        self, normalized_score: float, confidence_level: ConfidenceLevel | None
    ) -> int:
        if normalized_score < self._INCORRECT_THRESHOLD:
            return self._FIRST_INCORRECT_DAYS
        if normalized_score < self._SUCCESS_THRESHOLD:
            return self._FIRST_PARTIAL_DAYS
        if confidence_level in self._HIGH_CONFIDENCE_LEVELS:
            return self._FIRST_CORRECT_HIGH_DAYS
        if confidence_level == ConfidenceLevel.MEDIUM:
            return self._FIRST_CORRECT_MEDIUM_DAYS
        return self._FIRST_CORRECT_LOW_DAYS

    def _clamp_ease(self, value: float) -> float:
        return max(self._EASE_MIN, min(self._EASE_MAX, value))

    def update_schedule(
        self,
        *,
        learner_id: UUID,
        skill_id: UUID,
        previous: SkillReviewSchedule | None,
        normalized_score: float,
        confidence_level: ConfidenceLevel | None,
        practiced_at: datetime,
    ) -> SkillReviewSchedule:
        is_successful = normalized_score >= self._SUCCESS_THRESHOLD

        if previous is None:
            interval_days = self._first_review_interval_days(normalized_score, confidence_level)
            return SkillReviewSchedule(
                learner_id=learner_id,
                skill_id=skill_id,
                status=ReviewScheduleStatus.SCHEDULED,
                last_reviewed_at=practiced_at,
                next_review_at=practiced_at + timedelta(days=interval_days),
                review_interval_days=interval_days,
                successful_review_count=1 if is_successful else 0,
                failed_review_count=0 if is_successful else 1,
                consecutive_successful_reviews=1 if is_successful else 0,
                ease_factor=self._DEFAULT_EASE,
                calculation_version=self.policy_version,
                # Deterministic given deterministic inputs: unlike the other
                # two branches (which reuse `previous.created_at`), a brand
                # new schedule has no prior row to inherit from, so this
                # must be pinned to the injected `practiced_at` clock value
                # too - leaving it unset falls back to `SkillReviewSchedule`
                # 's `Field(default_factory=utc_now)`, i.e. real wall-clock
                # time, which is what made this policy's output
                # nondeterministic across two calls in the same test.
                created_at=practiced_at,
                updated_at=practiced_at,
            )

        if is_successful:
            ease_delta = (
                self._EASE_INCREASE_STRONG if confidence_level in self._HIGH_CONFIDENCE_LEVELS else 0.0
            )
            new_ease = self._clamp_ease(previous.ease_factor + ease_delta)
            floor_interval = self._first_review_interval_days(normalized_score, confidence_level)
            new_interval = max(floor_interval, round(previous.review_interval_days * new_ease))
            return SkillReviewSchedule(
                schedule_id=previous.schedule_id,
                learner_id=learner_id,
                skill_id=skill_id,
                status=ReviewScheduleStatus.SCHEDULED,
                last_reviewed_at=practiced_at,
                next_review_at=practiced_at + timedelta(days=new_interval),
                review_interval_days=new_interval,
                successful_review_count=previous.successful_review_count + 1,
                failed_review_count=previous.failed_review_count,
                consecutive_successful_reviews=previous.consecutive_successful_reviews + 1,
                ease_factor=new_ease,
                calculation_version=self.policy_version,
                created_at=previous.created_at,
                updated_at=practiced_at,
            )

        ease_delta = (
            -self._EASE_DECREASE_PARTIAL
            if normalized_score >= self._INCORRECT_THRESHOLD
            else -self._EASE_DECREASE_INCORRECT
        )
        new_ease = self._clamp_ease(previous.ease_factor + ease_delta)
        new_interval = self._FIRST_INCORRECT_DAYS
        return SkillReviewSchedule(
            schedule_id=previous.schedule_id,
            learner_id=learner_id,
            skill_id=skill_id,
            status=ReviewScheduleStatus.SCHEDULED,
            last_reviewed_at=practiced_at,
            next_review_at=practiced_at + timedelta(days=new_interval),
            review_interval_days=new_interval,
            successful_review_count=previous.successful_review_count,
            failed_review_count=previous.failed_review_count + 1,
            consecutive_successful_reviews=0,
            ease_factor=new_ease,
            calculation_version=self.policy_version,
            created_at=previous.created_at,
            updated_at=practiced_at,
        )


# ---------------------------------------------------------------------------
# RuleBasedDiagnosticPolicy
# ---------------------------------------------------------------------------


class RuleBasedDiagnosticPolicy:
    """diagnostic-policy-v1: deterministic diagnostic item selection and scoring.

    Item selection: candidates are grouped by requested skill and
    sorted, per skill, by (unattempted first, closeness of
    `base_difficulty_score` to 0.5, stable exercise UUID string). Items
    are then chosen round-robin across skills (one pass per round) so
    that breadth of skill coverage is maximized before a second item is
    added for any one skill, up to `maximum_items`.

    `assessment_id` on returned items is a placeholder (the assessment
    does not exist yet when items are selected) - the caller rewrites
    it to the real assessment ID before persisting, the same pattern
    used for canonical-ID rewriting elsewhere in this codebase.

    Scoring: a skill's score is the average `normalized_score` of
    completed items targeting it (an item targeting multiple skills
    contributes to all of them, for this MVP). Thresholds:
        NOT_ASSESSED:      no completed item
        NEEDS_FOUNDATION:  score < 0.30
        DEVELOPING:        0.30 <= score < 0.60
        READY:             0.60 <= score < 0.85
        STRONG:            score >= 0.85

    Initial mastery from a completed diagnostic (see
    `compute_initial_mastery`): a brand-new skill's mastery is the
    diagnostic score directly; an existing mastery is blended
    `0.6 * previous + 0.4 * diagnostic`. `MASTERED` is never assigned
    from diagnostic data alone unless at least 3 diagnostic items
    covered the skill and its diagnostic score is >= 0.90.
    """

    policy_version = "diagnostic-policy-v1"

    _NEEDS_FOUNDATION_MAX = 0.30
    _DEVELOPING_MAX = 0.60
    _READY_MAX = 0.85

    _MASTERY_PREVIOUS_WEIGHT = 0.60
    _MASTERY_DIAGNOSTIC_WEIGHT = 0.40
    _MASTERED_MIN_ITEMS = 3
    _MASTERED_MIN_SCORE = 0.90

    async def select_items(
        self,
        *,
        learner_id: UUID,
        skill_ids: list[UUID],
        candidates: list[ExerciseCandidate],
        maximum_items: int,
        now: datetime,
    ) -> list[DiagnosticAssessmentItem]:
        unique_skill_ids = list(dict.fromkeys(skill_ids))

        def sort_key(candidate: ExerciseCandidate) -> tuple[int, float, str]:
            unattempted_first = 0 if candidate.recent_attempt_count == 0 else 1
            difficulty_distance = abs(candidate.adaptive_profile.base_difficulty_score - 0.5)
            return (unattempted_first, difficulty_distance, str(candidate.exercise.exercise_id))

        candidates_by_skill: dict[UUID, list[ExerciseCandidate]] = {
            skill_id: sorted(
                (c for c in candidates if skill_id in c.exercise.skill_ids), key=sort_key
            )
            for skill_id in unique_skill_ids
        }

        selected: list[DiagnosticAssessmentItem] = []
        selected_exercise_ids: set[UUID] = set()
        round_index = 0

        while len(selected) < maximum_items:
            added_this_round = False
            for skill_id in unique_skill_ids:
                if len(selected) >= maximum_items:
                    break
                available = [
                    c
                    for c in candidates_by_skill[skill_id]
                    if c.exercise.exercise_id not in selected_exercise_ids
                ]
                if round_index < len(available):
                    candidate = available[round_index]
                    selected_exercise_ids.add(candidate.exercise.exercise_id)
                    selected.append(
                        DiagnosticAssessmentItem(
                            assessment_id=uuid4(),
                            exercise_id=candidate.exercise.exercise_id,
                            skill_ids=list(candidate.exercise.skill_ids),
                            position=len(selected) + 1,
                            selected_at=now,
                        )
                    )
                    added_this_round = True
            if not added_this_round:
                break
            round_index += 1

        return selected

    def summarize(
        self,
        *,
        assessment: DiagnosticAssessment,
        items: list[DiagnosticAssessmentItem],
    ) -> DiagnosticSummary:
        completed_items = [item for item in items if item.completed_at is not None]

        scores_by_skill: dict[UUID, list[float]] = {skill_id: [] for skill_id in assessment.skill_ids}
        for item in completed_items:
            if item.normalized_score is None:
                continue
            for skill_id in item.skill_ids:
                if skill_id in scores_by_skill:
                    scores_by_skill[skill_id].append(item.normalized_score)

        skill_scores: dict[UUID, float] = {}
        skill_results: dict[UUID, DiagnosticSkillResult] = {}
        for skill_id in assessment.skill_ids:
            scores = scores_by_skill[skill_id]
            if not scores:
                skill_results[skill_id] = DiagnosticSkillResult.NOT_ASSESSED
                continue
            average = sum(scores) / len(scores)
            skill_scores[skill_id] = average
            skill_results[skill_id] = self._classify(average)

        needs_foundation = sorted(
            (
                skill_id
                for skill_id, result in skill_results.items()
                if result == DiagnosticSkillResult.NEEDS_FOUNDATION
            ),
            key=str,
        )
        if needs_foundation:
            recommended_starting = needs_foundation
        else:
            not_assessed = sorted(
                (
                    skill_id
                    for skill_id, result in skill_results.items()
                    if result == DiagnosticSkillResult.NOT_ASSESSED
                ),
                key=str,
            )
            recommended_starting = not_assessed or sorted(assessment.skill_ids, key=str)

        return DiagnosticSummary(
            assessment=assessment,
            items=items,
            skill_results=skill_results,
            skill_scores=skill_scores,
            recommended_starting_skill_ids=recommended_starting,
        )

    def _classify(self, average_score: float) -> DiagnosticSkillResult:
        if average_score < self._NEEDS_FOUNDATION_MAX:
            return DiagnosticSkillResult.NEEDS_FOUNDATION
        if average_score < self._DEVELOPING_MAX:
            return DiagnosticSkillResult.DEVELOPING
        if average_score < self._READY_MAX:
            return DiagnosticSkillResult.READY
        return DiagnosticSkillResult.STRONG

    def compute_initial_mastery(
        self,
        *,
        learner_id: UUID,
        skill_id: UUID,
        previous: SkillMastery | None,
        diagnostic_score: float,
        diagnostic_item_count: int,
        now: datetime,
    ) -> SkillMastery:
        """Combine a diagnostic result into skill mastery (see class docstring)."""
        is_correct_signal = diagnostic_score >= self._DEVELOPING_MAX

        if previous is None:
            mastery_score = diagnostic_score
            mastery_id = uuid4()
            total_attempts = 1
            correct_attempts = 1 if is_correct_signal else 0
            consecutive_correct = 1 if is_correct_signal else 0
        else:
            mastery_score = (
                self._MASTERY_PREVIOUS_WEIGHT * previous.mastery_score
                + self._MASTERY_DIAGNOSTIC_WEIGHT * diagnostic_score
            )
            mastery_id = previous.mastery_id
            total_attempts = previous.total_attempts + 1
            correct_attempts = previous.correct_attempts + (1 if is_correct_signal else 0)
            consecutive_correct = (
                previous.consecutive_correct + 1 if is_correct_signal else 0
            )

        if mastery_score < self._NEEDS_FOUNDATION_MAX:
            mastery_level = MasteryLevel.NOVICE
        elif mastery_score < self._DEVELOPING_MAX:
            mastery_level = MasteryLevel.DEVELOPING
        elif (
            mastery_score >= self._READY_MAX
            and diagnostic_item_count >= self._MASTERED_MIN_ITEMS
            and diagnostic_score >= self._MASTERED_MIN_SCORE
        ):
            mastery_level = MasteryLevel.MASTERED
        else:
            mastery_level = MasteryLevel.PROFICIENT

        return SkillMastery(
            mastery_id=mastery_id,
            learner_id=learner_id,
            skill_id=skill_id,
            mastery_score=mastery_score,
            mastery_level=mastery_level,
            correct_attempts=correct_attempts,
            total_attempts=total_attempts,
            consecutive_correct=consecutive_correct,
            last_practiced_at=now,
            calculation_version=f"{self.policy_version}+mastery-blend-v1",
            updated_at=now,
        )


# ---------------------------------------------------------------------------
# RuleBasedAdaptivePolicy
# ---------------------------------------------------------------------------

#: Priority-score component weights. Must sum to 1.0 (enforced by a test).
COMPONENT_WEIGHTS: dict[str, float] = {
    "misconception_urgency": 0.25,
    "review_urgency": 0.20,
    "mastery_gap": 0.20,
    "prerequisite_importance": 0.15,
    "recent_failure_signal": 0.10,
    "lesson_progress_relevance": 0.05,
    "novelty": 0.05,
}

_TIER_MISCONCEPTION = 1
_TIER_OVERDUE_REVIEW = 2
_TIER_PREREQUISITE = 3
_TIER_RECENT_FAILURE = 4
_TIER_LOW_MASTERY = 5
_TIER_INCOMPLETE_LESSON = 6
_TIER_NEW_CONTENT = 7

_LOW_MASTERY_GAP_THRESHOLD = 0.40  # gap = 1 - average_mastery; 0.40 gap == 0.60 average mastery
_REPEATED_FAILURE_MIN_ATTEMPTS = 2
_REPEATED_FAILURE_MAX_CORRECT_RATE = 0.50


class RuleBasedAdaptivePolicy:
    """adaptive-policy-v1: deterministic next-exercise recommendation.

    `candidates` must already be the *eligible* pool (active exercise
    and profile, gradable type, mastery within the profile's optional
    range, and either outside the recent-repetition cooldown or
    qualifying for one of the documented bypasses) - see
    `AdaptiveLearningService._build_candidates`. This policy only
    scores, tier-ranks, and explains.

    Candidate priority order (highest first): active misconception,
    overdue review, prerequisite gap, recent repeated failure, low
    mastery, incomplete lesson, new content. A candidate's *tier*
    strictly decides ranking; the weighted `priority_score` below is
    computed for every candidate for transparency/audit and used only
    to break ties *within* a tier, alongside (in order) lower lesson
    position, lower exercise position, and the exercise UUID string.
    """

    policy_version = "adaptive-policy-v1"

    def __init__(self) -> None:
        assert abs(sum(COMPONENT_WEIGHTS.values()) - 1.0) < 1e-9

    async def recommend(
        self,
        *,
        state: AdaptiveLearnerState,
        candidates: list[ExerciseCandidate],
        now: datetime,
    ) -> AdaptiveDecision:
        if not candidates:
            return self._no_eligible_content_decision(state, now)

        in_progress_lesson_ids = {
            progress.lesson_id
            for progress in state.progress
            if progress.lesson_id is not None and progress.status.value == "IN_PROGRESS"
        }

        scored: list[tuple[int, float, ExerciseCandidate, dict[str, float]]] = []
        for candidate in candidates:
            components = self._score_components(candidate, in_progress_lesson_ids)
            tier = self._tier_for(candidate, components)
            weighted = sum(components[name] * weight for name, weight in COMPONENT_WEIGHTS.items())
            scored.append((tier, weighted, candidate, components))

        scored.sort(
            key=lambda row: (
                row[0],
                -row[1],
                row[2].lesson_position,
                row[2].exercise.position,
                str(row[2].exercise.exercise_id),
            )
        )
        winning_tier, winning_score, winner, winning_components = scored[0]

        return self._build_decision(
            state, winner, winning_tier, winning_score, winning_components, now
        )

    def _score_components(
        self, candidate: ExerciseCandidate, in_progress_lesson_ids: set[UUID]
    ) -> dict[str, float]:
        mastery_scores = [
            candidate.skill_mastery_scores.get(skill_id, 0.0)
            for skill_id in candidate.exercise.skill_ids
        ]
        average_mastery = sum(mastery_scores) / len(mastery_scores) if mastery_scores else 0.0
        mastery_gap = 1.0 - average_mastery

        prerequisite_importance = 0.0 if candidate.prerequisites_satisfied else 1.0

        recent_failure_signal = 0.0
        if (
            candidate.recent_attempt_count >= _REPEATED_FAILURE_MIN_ATTEMPTS
            and candidate.recent_correct_rate is not None
            and candidate.recent_correct_rate < _REPEATED_FAILURE_MAX_CORRECT_RATE
        ):
            recent_failure_signal = 1.0 - candidate.recent_correct_rate

        lesson_progress_relevance = (
            1.0 if candidate.exercise.lesson_id in in_progress_lesson_ids else 0.0
        )
        novelty = 1.0 / (1.0 + candidate.recent_attempt_count)

        return {
            "misconception_urgency": 1.0 if candidate.has_active_misconception else 0.0,
            "review_urgency": 1.0 if candidate.is_overdue_review else 0.0,
            "mastery_gap": mastery_gap,
            "prerequisite_importance": prerequisite_importance,
            "recent_failure_signal": recent_failure_signal,
            "lesson_progress_relevance": lesson_progress_relevance,
            "novelty": novelty,
        }

    def _tier_for(self, candidate: ExerciseCandidate, components: dict[str, float]) -> int:
        if candidate.has_active_misconception:
            return _TIER_MISCONCEPTION
        if candidate.is_overdue_review:
            return _TIER_OVERDUE_REVIEW
        if components["prerequisite_importance"] > 0:
            return _TIER_PREREQUISITE
        if components["recent_failure_signal"] > 0:
            return _TIER_RECENT_FAILURE
        if components["mastery_gap"] >= _LOW_MASTERY_GAP_THRESHOLD:
            return _TIER_LOW_MASTERY
        if components["lesson_progress_relevance"] > 0:
            return _TIER_INCOMPLETE_LESSON
        return _TIER_NEW_CONTENT

    _TIER_TEMPLATES: dict[int, tuple[RecommendationType, RecommendationReason, str]] = {
        _TIER_MISCONCEPTION: (
            RecommendationType.MISCONCEPTION_REMEDIATION,
            RecommendationReason.ACTIVE_MISCONCEPTION,
            "This exercise targets a misconception detected in your recent answers.",
        ),
        _TIER_OVERDUE_REVIEW: (
            RecommendationType.REVIEW_EXERCISE,
            RecommendationReason.OVERDUE_REVIEW,
            "This review is overdue and will help reinforce a skill you've practiced before.",
        ),
        _TIER_PREREQUISITE: (
            RecommendationType.PREREQUISITE_REVIEW,
            RecommendationReason.PREREQUISITE_GAP,
            "This prerequisite exercise is recommended before continuing to more advanced material.",
        ),
        _TIER_RECENT_FAILURE: (
            RecommendationType.PRACTICE_EXERCISE,
            RecommendationReason.RECENT_FAILURE,
            "You've had trouble with similar exercises recently, so this one gives you another chance to practice.",
        ),
        _TIER_LOW_MASTERY: (
            RecommendationType.PRACTICE_EXERCISE,
            RecommendationReason.LOW_MASTERY,
            "Your mastery of this skill is still developing, so this exercise will help you build it up.",
        ),
        _TIER_INCOMPLETE_LESSON: (
            RecommendationType.PRACTICE_EXERCISE,
            RecommendationReason.INCOMPLETE_LESSON,
            "This continues a lesson you've already started.",
        ),
        _TIER_NEW_CONTENT: (
            RecommendationType.NEW_LESSON,
            RecommendationReason.NEW_CONTENT,
            "This introduces new material for you to learn.",
        ),
    }

    def _build_decision(
        self,
        state: AdaptiveLearnerState,
        winner: ExerciseCandidate,
        tier: int,
        priority_score: float,
        components: dict[str, float],
        now: datetime,
    ) -> AdaptiveDecision:
        recommendation_type, reason, explanation = self._TIER_TEMPLATES[tier]
        return AdaptiveDecision(
            learner_id=state.learner.learner_id,
            session_id=state.current_session.session_id if state.current_session else None,
            recommendation_type=recommendation_type,
            recommended_exercise_id=winner.exercise.exercise_id,
            recommended_lesson_id=winner.exercise.lesson_id,
            target_skill_ids=list(winner.exercise.skill_ids),
            reason_codes=[reason],
            priority_score=max(0.0, min(1.0, priority_score)),
            policy_version=self.policy_version,
            explanation=explanation,
            input_snapshot=self._sanitized_snapshot(winner, tier, components),
            generated_at=now,
        )

    def _no_eligible_content_decision(
        self, state: AdaptiveLearnerState, now: datetime
    ) -> AdaptiveDecision:
        return AdaptiveDecision(
            learner_id=state.learner.learner_id,
            session_id=state.current_session.session_id if state.current_session else None,
            recommendation_type=RecommendationType.NO_ELIGIBLE_CONTENT,
            reason_codes=[RecommendationReason.NO_ELIGIBLE_EXERCISE],
            priority_score=0.0,
            policy_version=self.policy_version,
            explanation="There is no eligible exercise to recommend right now.",
            input_snapshot={"policy_version": self.policy_version, "candidate_count": 0},
            generated_at=now,
        )

    def _sanitized_snapshot(
        self, winner: ExerciseCandidate, tier: int, components: dict[str, float]
    ) -> dict[str, Any]:
        """Only primitive, non-secret values - never a full learner/exercise object."""
        return {
            "policy_version": self.policy_version,
            "tier": tier,
            "winning_exercise_id": str(winner.exercise.exercise_id),
            "components": {name: round(value, 6) for name, value in components.items()},
            "weights": COMPONENT_WEIGHTS,
        }
