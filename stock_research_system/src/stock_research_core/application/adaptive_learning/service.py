"""Application service orchestrating the adaptive learning engine.

This module depends only on domain models, application result models,
and `Protocol` contracts (`UnitOfWorkPort`, the four policy ports). It
never instantiates a concrete engine, session, or repository, and never
calls `datetime.now()` directly - time comes from an injected `clock`
callable so tests are fully deterministic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import UUID

from stock_research_core.application.adaptive_learning.models import (
    AdaptiveLearnerState,
    DiagnosticSummary,
    ExerciseCandidate,
    ExerciseRecommendation,
    SessionSummary,
)
from stock_research_core.application.adaptive_learning.ports import (
    AdaptivePolicyPort,
    DiagnosticPolicyPort,
    DifficultyPolicyPort,
    ReviewSchedulingPolicyPort,
    ScenarioEligibilityPort,
)
from stock_research_core.application.exceptions import (
    AdaptiveDecisionNotFoundError,
    DiagnosticAssessmentItemNotFoundError,
    DiagnosticAssessmentNotFoundError,
    ExerciseNotFoundError,
    InactiveLearnerError,
    InvalidDecisionStateError,
    LearnerNotFoundError,
    LearningSessionNotFoundError,
)
from stock_research_core.application.learning.grading import is_auto_gradable
from stock_research_core.application.learning.models import LearningActivityResult
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.adaptive_learning.enums import (
    AdaptiveDecisionStatus,
    DiagnosticAssessmentStatus,
    LearningSessionStatus,
    LearningSessionType,
    RecommendationReason,
    RecommendationType,
)
from stock_research_core.domain.adaptive_learning.models import (
    AdaptiveDecision,
    DiagnosticAssessment,
    LearningSession,
    LearningSessionActivity,
    SkillReviewSchedule,
)
from stock_research_core.domain.learning.enums import (
    AttemptStatus,
    ConfidenceLevel,
    DifficultyLevel,
    ExerciseType,
    LessonStatus,
)
from stock_research_core.domain.learning.models import ExerciseAttempt
from stock_research_core.domain.models import utc_now

Clock = Callable[[], datetime]

#: How many of the learner's most recent (completed or skipped) session
#: activities count toward the repetition cooldown.
_COOLDOWN_WINDOW = 3
_REPEATED_FAILURE_MIN_ATTEMPTS = 2
_REPEATED_FAILURE_MAX_CORRECT_RATE = 0.50
_PREREQUISITE_MASTERY_THRESHOLD = 0.60
_RECENT_ATTEMPTS_CAP = 50


class AdaptiveLearningService:
    """Orchestrates learning sessions, recommendations, and diagnostics."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        adaptive_policy: AdaptivePolicyPort,
        difficulty_policy: DifficultyPolicyPort,
        review_policy: ReviewSchedulingPolicyPort,
        diagnostic_policy: DiagnosticPolicyPort,
        clock: Clock = utc_now,
        scenario_eligibility: ScenarioEligibilityPort | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._adaptive_policy = adaptive_policy
        self._difficulty_policy = difficulty_policy
        self._review_policy = review_policy
        self._diagnostic_policy = diagnostic_policy
        self._clock = clock
        #: Optional: when absent, SCENARIO_DECISION exercises are never
        #: recommended (they were previously excluded outright by
        #: `is_auto_gradable`; this preserves that behavior unless a
        #: scenario-eligibility checker is explicitly wired in).
        self._scenario_eligibility = scenario_eligibility

    # -- sessions ---------------------------------------------------------

    async def start_session(
        self,
        *,
        learner_id: UUID,
        session_type: LearningSessionType = LearningSessionType.DAILY_PRACTICE,
        goal_minutes: int | None = None,
    ) -> LearningSession:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            learner = await uow.learners.get(learner_id)
            if learner is None:
                raise LearnerNotFoundError(f"No learner found with id '{learner_id}'.")
            if not learner.active:
                raise InactiveLearnerError(f"Learner '{learner_id}' is not active.")

            if session_type == LearningSessionType.DAILY_PRACTICE:
                active_sessions = await uow.learning_sessions.list_active_sessions(learner_id)
                existing_daily = next(
                    (s for s in active_sessions if s.session_type == LearningSessionType.DAILY_PRACTICE),
                    None,
                )
                if existing_daily is not None:
                    # Documented policy: reuse the existing active daily session
                    # rather than creating a conflicting second one.
                    return existing_daily

            session = LearningSession(
                learner_id=learner_id,
                session_type=session_type,
                status=LearningSessionStatus.ACTIVE,
                goal_minutes=goal_minutes if goal_minutes is not None else learner.daily_goal_minutes,
                started_at=now,
                last_activity_at=now,
                policy_version=self._adaptive_policy.policy_version,
            )
            created = await uow.learning_sessions.create_session(session)
            await uow.commit()
        return created

    async def complete_session(self, *, session_id: UUID) -> SessionSummary:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            session = await uow.learning_sessions.get_session(session_id)
            if session is None:
                raise LearningSessionNotFoundError(f"No learning session found with id '{session_id}'.")
            updated_session = session.model_copy(
                update={
                    "status": LearningSessionStatus.COMPLETED,
                    "completed_at": now,
                    "last_activity_at": now,
                }
            )
            stored_session = await uow.learning_sessions.update_session(updated_session)
            activities = await uow.learning_sessions.list_activities(session_id)
            await uow.commit()
        return SessionSummary(
            session=stored_session, activities=activities, mastery_changes={}, reviews_scheduled=[]
        )

    # -- recommendations ---------------------------------------------------------

    async def recommend_next(self, *, learner_id: UUID, session_id: UUID) -> ExerciseRecommendation:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            session = await uow.learning_sessions.get_session(session_id)
            if session is None:
                raise LearningSessionNotFoundError(f"No learning session found with id '{session_id}'.")
            if session.learner_id != learner_id:
                raise InvalidDecisionStateError("session does not belong to the requesting learner")
            if session.status not in (LearningSessionStatus.STARTED, LearningSessionStatus.ACTIVE):
                raise InvalidDecisionStateError(f"session '{session_id}' is not active")

            state = await self._load_learner_state(uow, learner_id, session)

            elapsed_seconds = (now - session.started_at).total_seconds()
            if elapsed_seconds >= session.goal_minutes * 60:
                decision = AdaptiveDecision(
                    learner_id=learner_id,
                    session_id=session_id,
                    recommendation_type=RecommendationType.SESSION_COMPLETE,
                    reason_codes=[RecommendationReason.DAILY_GOAL_REACHED],
                    priority_score=1.0,
                    policy_version=self._adaptive_policy.policy_version,
                    explanation="You've reached your daily goal for this session. Great work!",
                    input_snapshot={
                        "elapsed_seconds": elapsed_seconds,
                        "goal_minutes": session.goal_minutes,
                    },
                    generated_at=now,
                )
                created_decision = await uow.adaptive_decisions.create_decision(decision)
                await uow.commit()
                return ExerciseRecommendation(decision=created_decision)

            candidates = await self._build_candidates(uow, state, session, now)
            decision = await self._adaptive_policy.recommend(state=state, candidates=candidates, now=now)

            exercise = None
            adaptive_profile = None
            lesson = None
            if decision.recommendation_type not in (
                RecommendationType.SESSION_COMPLETE,
                RecommendationType.NO_ELIGIBLE_CONTENT,
            ):
                matching = next(
                    (c for c in candidates if c.exercise.exercise_id == decision.recommended_exercise_id),
                    None,
                )
                if matching is not None:
                    consecutive_correct, consecutive_incorrect = self._consecutive_streak(
                        state, matching.exercise.exercise_id
                    )
                    mastery_values = list(matching.skill_mastery_scores.values())
                    average_mastery = (
                        sum(mastery_values) / len(mastery_values) if mastery_values else 0.0
                    )
                    difficulty_score, _adjustment = self._difficulty_policy.recommend_difficulty(
                        mastery_score=average_mastery,
                        recent_correct_rate=matching.recent_correct_rate,
                        consecutive_correct=consecutive_correct,
                        consecutive_incorrect=consecutive_incorrect,
                        confidence_level=None,
                    )
                    decision = decision.model_copy(
                        update={"recommended_difficulty_score": difficulty_score}
                    )
                    exercise = matching.exercise
                    adaptive_profile = matching.adaptive_profile
                    lesson = await uow.curriculum.get_lesson(exercise.lesson_id)

            created_decision = await uow.adaptive_decisions.create_decision(decision)

            if exercise is not None:
                existing_activities = await uow.learning_sessions.list_activities(session_id)
                activity = LearningSessionActivity(
                    session_id=session_id,
                    learner_id=learner_id,
                    exercise_id=exercise.exercise_id,
                    decision_id=created_decision.decision_id,
                    position=len(existing_activities) + 1,
                    recommended_at=now,
                )
                await uow.learning_sessions.add_activity(activity)
                updated_session = session.model_copy(
                    update={
                        "recommended_item_count": session.recommended_item_count + 1,
                        "last_activity_at": now,
                        "status": LearningSessionStatus.ACTIVE,
                    }
                )
                await uow.learning_sessions.update_session(updated_session)

            await uow.commit()

        return ExerciseRecommendation(
            decision=created_decision, exercise=exercise, lesson=lesson, adaptive_profile=adaptive_profile
        )

    async def accept_recommendation(self, *, decision_id: UUID) -> AdaptiveDecision:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            decision = await self._get_decision_or_raise(uow, decision_id)
            if decision.status != AdaptiveDecisionStatus.GENERATED:
                raise InvalidDecisionStateError(
                    f"decision '{decision_id}' is '{decision.status.value}', expected GENERATED"
                )
            updated = decision.model_copy(
                update={"status": AdaptiveDecisionStatus.ACCEPTED, "accepted_at": now}
            )
            result = await uow.adaptive_decisions.update_decision(updated)

            activity = await uow.learning_sessions.get_activity_by_decision(decision_id)
            if activity is not None and activity.started_at is None:
                await uow.learning_sessions.update_activity(
                    activity.model_copy(update={"started_at": now})
                )

            await uow.commit()
        return result

    async def start_recommended_exercise(
        self, *, decision_id: UUID, confidence_level: ConfidenceLevel | None = None
    ) -> ExerciseAttempt:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            decision = await self._get_decision_or_raise(uow, decision_id)
            if decision.status not in (AdaptiveDecisionStatus.GENERATED, AdaptiveDecisionStatus.ACCEPTED):
                raise InvalidDecisionStateError(
                    f"decision '{decision_id}' cannot be started (status={decision.status.value})"
                )
            if decision.recommended_exercise_id is None:
                raise InvalidDecisionStateError(f"decision '{decision_id}' has no recommended exercise")

            activity = await uow.learning_sessions.get_activity_by_decision(decision_id)
            if activity is not None and activity.attempt_id is not None:
                existing_attempt = await uow.attempts.get_attempt(activity.attempt_id)
                if existing_attempt is not None:
                    return existing_attempt  # avoid duplicating attempts for the same decision

            exercise = await uow.curriculum.get_exercise(decision.recommended_exercise_id)
            if exercise is None:
                raise ExerciseNotFoundError(f"No exercise found with id '{decision.recommended_exercise_id}'.")

            previous_attempts = await uow.attempts.list_attempts(
                decision.learner_id, decision.recommended_exercise_id
            )
            attempt = ExerciseAttempt(
                learner_id=decision.learner_id,
                exercise_id=decision.recommended_exercise_id,
                maximum_score=exercise.maximum_score,
                attempt_number=len(previous_attempts) + 1,
                confidence_level=confidence_level,
            )
            created_attempt = await uow.attempts.create_attempt(attempt)

            if activity is not None:
                await uow.learning_sessions.update_activity(
                    activity.model_copy(
                        update={
                            "attempt_id": created_attempt.attempt_id,
                            "started_at": activity.started_at or now,
                        }
                    )
                )

            if decision.status == AdaptiveDecisionStatus.GENERATED:
                await uow.adaptive_decisions.update_decision(
                    decision.model_copy(
                        update={"status": AdaptiveDecisionStatus.ACCEPTED, "accepted_at": now}
                    )
                )

            await uow.commit()
        return created_attempt

    async def record_completed_activity(
        self, *, decision_id: UUID, learning_activity_result: LearningActivityResult
    ) -> SessionSummary:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            decision = await self._get_decision_or_raise(uow, decision_id)

            activity = await uow.learning_sessions.get_activity_by_decision(decision_id)
            if activity is None:
                raise InvalidDecisionStateError(f"No session activity found for decision '{decision_id}'.")

            attempt = learning_activity_result.attempt
            if attempt.exercise_id != decision.recommended_exercise_id:
                raise InvalidDecisionStateError("attempt does not belong to the recommended exercise")

            updated_activity = await uow.learning_sessions.update_activity(
                activity.model_copy(update={"completed_at": now})
            )
            await uow.adaptive_decisions.update_decision(
                decision.model_copy(update={"status": AdaptiveDecisionStatus.COMPLETED, "completed_at": now})
            )

            session = await uow.learning_sessions.get_session(activity.session_id)
            if session is None:
                raise LearningSessionNotFoundError(f"No learning session found with id '{activity.session_id}'.")

            is_correct = bool(attempt.is_correct)
            score = attempt.score or 0.0
            updated_session = await uow.learning_sessions.update_session(
                session.model_copy(
                    update={
                        "completed_item_count": session.completed_item_count + 1,
                        "correct_item_count": session.correct_item_count + (1 if is_correct else 0),
                        "total_score": session.total_score + score,
                        "maximum_score": session.maximum_score + attempt.maximum_score,
                        "last_activity_at": now,
                    }
                )
            )

            mastery_changes: dict[UUID, float] = {}
            reviews_scheduled: list[SkillReviewSchedule] = []
            # Skill mastery itself is already updated by LearningService.submit_answer
            # (via the orchestrator); here we only update spaced-repetition
            # schedules, which are adaptive-engine-specific. A deterministic
            # misconception rule does not exist yet in this phase, so none is
            # invented here even on repeated failure.
            if attempt.status == AttemptStatus.GRADED and attempt.score is not None:
                normalized_score = attempt.score / attempt.maximum_score
                for skill_id in decision.target_skill_ids:
                    previous_schedule = await uow.review_schedules.get(decision.learner_id, skill_id)
                    new_schedule = self._review_policy.update_schedule(
                        learner_id=decision.learner_id,
                        skill_id=skill_id,
                        previous=previous_schedule,
                        normalized_score=normalized_score,
                        confidence_level=attempt.confidence_level,
                        practiced_at=now,
                    )
                    stored_schedule = await uow.review_schedules.upsert(new_schedule)
                    reviews_scheduled.append(stored_schedule)
                    mastery_changes[skill_id] = normalized_score

            await uow.commit()

        return SessionSummary(
            session=updated_session,
            activities=[updated_activity],
            mastery_changes=mastery_changes,
            reviews_scheduled=reviews_scheduled,
        )

    async def skip_recommendation(self, *, decision_id: UUID) -> AdaptiveDecision:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            decision = await self._get_decision_or_raise(uow, decision_id)
            if decision.status not in (AdaptiveDecisionStatus.GENERATED, AdaptiveDecisionStatus.ACCEPTED):
                raise InvalidDecisionStateError(
                    f"decision '{decision_id}' cannot be skipped (status={decision.status.value})"
                )

            result = await uow.adaptive_decisions.update_decision(
                decision.model_copy(update={"status": AdaptiveDecisionStatus.SKIPPED, "skipped_at": now})
            )

            activity = await uow.learning_sessions.get_activity_by_decision(decision_id)
            if activity is not None:
                await uow.learning_sessions.update_activity(
                    activity.model_copy(update={"skipped_at": now})
                )

            await uow.commit()
        return result

    # -- diagnostics ---------------------------------------------------------

    async def start_diagnostic(
        self,
        *,
        learner_id: UUID,
        skill_ids: list[UUID] | None = None,
        maximum_items: int = 10,
    ) -> DiagnosticSummary:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            learner = await uow.learners.get(learner_id)
            if learner is None:
                raise LearnerNotFoundError(f"No learner found with id '{learner_id}'.")

            if skill_ids is None:
                all_skills = await uow.curriculum.list_skills(active_only=True)
                effective_skill_ids = [
                    skill.skill_id for skill in all_skills if skill.difficulty == DifficultyLevel.BEGINNER
                ]
            else:
                effective_skill_ids = list(skill_ids)

            state = await self._load_learner_state(uow, learner_id, session=None)
            diagnostic_profiles = await uow.adaptive_profiles.list_active(diagnostic_only=True)
            diagnostic_exercise_ids = {profile.exercise_id for profile in diagnostic_profiles}
            candidates = await self._build_diagnostic_candidates(uow, state, diagnostic_exercise_ids)

            assessment = DiagnosticAssessment(
                learner_id=learner_id,
                status=DiagnosticAssessmentStatus.IN_PROGRESS,
                skill_ids=effective_skill_ids,
                maximum_items=maximum_items,
                started_at=now,
                policy_version=self._diagnostic_policy.policy_version,
            )
            created_assessment = await uow.diagnostics.create_assessment(assessment)

            items = await self._diagnostic_policy.select_items(
                learner_id=learner_id,
                skill_ids=effective_skill_ids,
                candidates=candidates,
                maximum_items=maximum_items,
                now=now,
            )
            rewritten_items = [
                item.model_copy(update={"assessment_id": created_assessment.assessment_id})
                for item in items
            ]
            if rewritten_items:
                await uow.diagnostics.save_items(rewritten_items)

            session = LearningSession(
                learner_id=learner_id,
                session_type=LearningSessionType.DIAGNOSTIC,
                status=LearningSessionStatus.ACTIVE,
                goal_minutes=learner.daily_goal_minutes,
                started_at=now,
                last_activity_at=now,
                policy_version=self._diagnostic_policy.policy_version,
            )
            await uow.learning_sessions.create_session(session)

            summary = self._diagnostic_policy.summarize(assessment=created_assessment, items=rewritten_items)
            await uow.commit()
        return summary

    async def start_diagnostic_item(
        self,
        *,
        assessment_id: UUID,
        item_id: UUID,
        confidence_level: ConfidenceLevel | None = None,
    ) -> ExerciseAttempt:
        async with self._unit_of_work_factory() as uow:
            assessment = await self._get_assessment_or_raise(uow, assessment_id)
            item = await uow.diagnostics.get_item(item_id)
            if item is None or item.assessment_id != assessment_id:
                raise DiagnosticAssessmentItemNotFoundError(
                    f"No diagnostic item found with id '{item_id}' for assessment '{assessment_id}'."
                )

            if item.attempt_id is not None:
                existing = await uow.attempts.get_attempt(item.attempt_id)
                if existing is not None:
                    return existing

            exercise = await uow.curriculum.get_exercise(item.exercise_id)
            if exercise is None:
                raise ExerciseNotFoundError(f"No exercise found with id '{item.exercise_id}'.")

            previous_attempts = await uow.attempts.list_attempts(assessment.learner_id, item.exercise_id)
            attempt = ExerciseAttempt(
                learner_id=assessment.learner_id,
                exercise_id=item.exercise_id,
                maximum_score=exercise.maximum_score,
                attempt_number=len(previous_attempts) + 1,
                confidence_level=confidence_level,
            )
            created_attempt = await uow.attempts.create_attempt(attempt)
            await uow.diagnostics.update_item(item.model_copy(update={"attempt_id": created_attempt.attempt_id}))
            await uow.commit()
        return created_attempt

    async def record_diagnostic_result(
        self,
        *,
        assessment_id: UUID,
        item_id: UUID,
        learning_activity_result: LearningActivityResult,
    ) -> DiagnosticSummary:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            assessment = await self._get_assessment_or_raise(uow, assessment_id)
            item = await uow.diagnostics.get_item(item_id)
            if item is None or item.assessment_id != assessment_id:
                raise DiagnosticAssessmentItemNotFoundError(
                    f"No diagnostic item found with id '{item_id}' for assessment '{assessment_id}'."
                )

            attempt = learning_activity_result.attempt
            normalized_score = (
                attempt.score / attempt.maximum_score if attempt.score is not None else 0.0
            )
            await uow.diagnostics.update_item(
                item.model_copy(update={"completed_at": now, "normalized_score": normalized_score})
            )

            items = await uow.diagnostics.list_items(assessment_id)
            summary = self._diagnostic_policy.summarize(assessment=assessment, items=items)
            await uow.commit()
        return summary

    async def complete_diagnostic(self, *, assessment_id: UUID) -> DiagnosticSummary:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            assessment = await self._get_assessment_or_raise(uow, assessment_id)
            items = await uow.diagnostics.list_items(assessment_id)
            completed_items = [item for item in items if item.completed_at is not None]
            if not completed_items:
                raise InvalidDecisionStateError(
                    f"diagnostic assessment '{assessment_id}' has no completed items"
                )

            stored_assessment = await uow.diagnostics.update_assessment(
                assessment.model_copy(
                    update={"status": DiagnosticAssessmentStatus.COMPLETED, "completed_at": now}
                )
            )
            summary = self._diagnostic_policy.summarize(assessment=stored_assessment, items=items)

            for skill_id, diagnostic_score in summary.skill_scores.items():
                item_count = sum(1 for item in completed_items if skill_id in item.skill_ids)
                previous_mastery = await uow.mastery.get(assessment.learner_id, skill_id)
                new_mastery = self._diagnostic_policy.compute_initial_mastery(
                    learner_id=assessment.learner_id,
                    skill_id=skill_id,
                    previous=previous_mastery,
                    diagnostic_score=diagnostic_score,
                    diagnostic_item_count=item_count,
                    now=now,
                )
                await uow.mastery.upsert(new_mastery)

            await uow.commit()
        return summary

    async def get_attempt_id_for_decision(self, *, decision_id: UUID) -> UUID:
        """Look up the attempt attached to a decision's session activity.

        Used by `AdaptiveLearningOrchestrator` so it never needs direct
        repository access of its own.
        """
        async with self._unit_of_work_factory() as uow:
            await self._get_decision_or_raise(uow, decision_id)
            activity = await uow.learning_sessions.get_activity_by_decision(decision_id)
            if activity is None or activity.attempt_id is None:
                raise InvalidDecisionStateError(
                    f"decision '{decision_id}' has no started attempt yet; "
                    "call start_recommended_exercise first"
                )
            return activity.attempt_id

    # -- private helpers ---------------------------------------------------------

    async def _get_decision_or_raise(self, uow: UnitOfWorkPort, decision_id: UUID) -> AdaptiveDecision:
        decision = await uow.adaptive_decisions.get_decision(decision_id)
        if decision is None:
            raise AdaptiveDecisionNotFoundError(f"No adaptive decision found with id '{decision_id}'.")
        return decision

    async def _get_assessment_or_raise(
        self, uow: UnitOfWorkPort, assessment_id: UUID
    ) -> DiagnosticAssessment:
        assessment = await uow.diagnostics.get_assessment(assessment_id)
        if assessment is None:
            raise DiagnosticAssessmentNotFoundError(
                f"No diagnostic assessment found with id '{assessment_id}'."
            )
        return assessment

    async def _load_learner_state(
        self, uow: UnitOfWorkPort, learner_id: UUID, session: LearningSession | None
    ) -> AdaptiveLearnerState:
        learner = await uow.learners.get(learner_id)
        if learner is None:
            raise LearnerNotFoundError(f"No learner found with id '{learner_id}'.")
        recent_attempts = await uow.attempts.list_attempts(learner_id)
        return AdaptiveLearnerState(
            learner=learner,
            mastery=await uow.mastery.list_for_learner(learner_id),
            progress=await uow.progress.list_for_learner(learner_id),
            active_misconceptions=await uow.misconceptions.list_active(learner_id),
            review_schedules=await uow.review_schedules.list_for_learner(learner_id),
            recent_attempts=recent_attempts[-_RECENT_ATTEMPTS_CAP:],
            current_session=session,
        )

    def _consecutive_streak(
        self, state: AdaptiveLearnerState, exercise_id: UUID
    ) -> tuple[int, int]:
        attempts = sorted(
            (
                attempt
                for attempt in state.recent_attempts
                if attempt.exercise_id == exercise_id and attempt.status == AttemptStatus.GRADED
            ),
            key=lambda attempt: attempt.started_at,
        )
        consecutive_correct = 0
        consecutive_incorrect = 0
        for attempt in reversed(attempts):
            if attempt.is_correct:
                if consecutive_incorrect > 0:
                    break
                consecutive_correct += 1
            else:
                if consecutive_correct > 0:
                    break
                consecutive_incorrect += 1
        return consecutive_correct, consecutive_incorrect

    async def _build_candidates(
        self,
        uow: UnitOfWorkPort,
        state: AdaptiveLearnerState,
        session: LearningSession,
        now: datetime,
    ) -> list[ExerciseCandidate]:
        """Build the *eligible* candidate pool for `recommend_next`.

        Eligibility applied here: active exercise + active adaptive
        profile, a deterministically gradable exercise type, not in an
        archived lesson, mastery within the profile's optional
        min/max range, not already an open (unfinished) activity in
        this session, and outside the repetition cooldown unless it
        qualifies for a documented bypass (overdue review, active
        misconception, or repeated recent failure). Prerequisite gaps
        are *not* filtered out here - they are surfaced by the
        adaptive policy itself as a PREREQUISITE_REVIEW-tier candidate.
        """
        mastery_by_skill = {mastery.skill_id: mastery.mastery_score for mastery in state.mastery}
        misconception_skill_ids = {m.skill_id for m in state.active_misconceptions}
        overdue_skill_ids = {
            schedule.skill_id
            for schedule in state.review_schedules
            if schedule.next_review_at is not None and schedule.next_review_at <= now
        }

        session_activities = sorted(
            await uow.learning_sessions.list_activities(session.session_id),
            key=lambda activity: activity.position,
        )
        resolved_activities = [
            activity
            for activity in session_activities
            if activity.completed_at is not None or activity.skipped_at is not None
        ]
        cooldown_exercise_ids = [
            activity.exercise_id for activity in resolved_activities[-_COOLDOWN_WINDOW:]
        ]
        open_activity_exercise_ids = {
            activity.exercise_id
            for activity in session_activities
            if activity.completed_at is None and activity.skipped_at is None
        }

        attempts_by_exercise: dict[UUID, list[ExerciseAttempt]] = {}
        for attempt in state.recent_attempts:
            attempts_by_exercise.setdefault(attempt.exercise_id, []).append(attempt)

        candidates: list[ExerciseCandidate] = []
        for path in await uow.curriculum.list_paths(published_only=True):
            for module in await uow.curriculum.list_modules(path.path_id):
                for lesson in await uow.curriculum.list_lessons(module.module_id):
                    if lesson.status == LessonStatus.ARCHIVED:
                        continue
                    for exercise in await uow.curriculum.list_exercises(lesson.lesson_id):
                        if not exercise.active:
                            continue
                        if not is_auto_gradable(exercise.exercise_type):
                            is_eligible_scenario = (
                                exercise.exercise_type == ExerciseType.SCENARIO_DECISION
                                and self._scenario_eligibility is not None
                                and await self._scenario_eligibility.is_eligible(exercise.exercise_id)
                            )
                            if not is_eligible_scenario:
                                continue
                        if exercise.exercise_id in open_activity_exercise_ids:
                            continue
                        profile = await uow.adaptive_profiles.get_by_exercise(exercise.exercise_id)
                        if profile is None or not profile.active:
                            continue

                        skill_scores = {
                            skill_id: mastery_by_skill.get(skill_id, 0.0)
                            for skill_id in exercise.skill_ids
                        }
                        average_mastery = (
                            sum(skill_scores.values()) / len(skill_scores) if skill_scores else 0.0
                        )
                        if (
                            profile.minimum_mastery_score is not None
                            and average_mastery < profile.minimum_mastery_score
                        ):
                            continue
                        if (
                            profile.maximum_mastery_score is not None
                            and average_mastery > profile.maximum_mastery_score
                        ):
                            continue

                        is_overdue_review = bool(overdue_skill_ids & set(exercise.skill_ids))
                        has_active_misconception = bool(
                            misconception_skill_ids & set(exercise.skill_ids)
                        )

                        exercise_attempts = attempts_by_exercise.get(exercise.exercise_id, [])
                        graded_attempts = [
                            attempt
                            for attempt in exercise_attempts
                            if attempt.status == AttemptStatus.GRADED
                        ]
                        recent_graded = graded_attempts[-5:]
                        recent_correct_rate = (
                            sum(1 for attempt in recent_graded if attempt.is_correct)
                            / len(recent_graded)
                            if recent_graded
                            else None
                        )
                        is_repeated_failure = (
                            len(recent_graded) >= _REPEATED_FAILURE_MIN_ATTEMPTS
                            and recent_correct_rate is not None
                            and recent_correct_rate < _REPEATED_FAILURE_MAX_CORRECT_RATE
                        )

                        bypass_cooldown = (
                            is_overdue_review or has_active_misconception or is_repeated_failure
                        )
                        recent_completions_in_window = cooldown_exercise_ids.count(
                            exercise.exercise_id
                        )
                        if recent_completions_in_window > 0 and not bypass_cooldown:
                            continue

                        prerequisites_satisfied = all(
                            mastery_by_skill.get(prerequisite_id, 0.0)
                            >= _PREREQUISITE_MASTERY_THRESHOLD
                            for prerequisite_id in profile.recommended_prerequisite_skill_ids
                        )

                        candidates.append(
                            ExerciseCandidate(
                                exercise=exercise,
                                adaptive_profile=profile,
                                lesson_position=lesson.position,
                                skill_mastery_scores=skill_scores,
                                recent_attempt_count=recent_completions_in_window,
                                recent_correct_rate=recent_correct_rate,
                                last_attempt_at=max(
                                    (attempt.started_at for attempt in exercise_attempts), default=None
                                ),
                                is_overdue_review=is_overdue_review,
                                has_active_misconception=has_active_misconception,
                                prerequisites_satisfied=prerequisites_satisfied,
                            )
                        )
        return candidates

    async def _build_diagnostic_candidates(
        self,
        uow: UnitOfWorkPort,
        state: AdaptiveLearnerState,
        diagnostic_exercise_ids: set[UUID],
    ) -> list[ExerciseCandidate]:
        """Build the candidate pool for diagnostic item selection.

        Unlike `_build_candidates`, `recent_attempt_count` here is a
        plain lifetime attempt count (used by the diagnostic policy to
        prefer never-attempted exercises), not a cooldown-window count.
        """
        mastery_by_skill = {mastery.skill_id: mastery.mastery_score for mastery in state.mastery}
        attempts_by_exercise: dict[UUID, list[ExerciseAttempt]] = {}
        for attempt in state.recent_attempts:
            attempts_by_exercise.setdefault(attempt.exercise_id, []).append(attempt)

        candidates: list[ExerciseCandidate] = []
        for path in await uow.curriculum.list_paths(published_only=True):
            for module in await uow.curriculum.list_modules(path.path_id):
                for lesson in await uow.curriculum.list_lessons(module.module_id):
                    if lesson.status == LessonStatus.ARCHIVED:
                        continue
                    for exercise in await uow.curriculum.list_exercises(lesson.lesson_id):
                        if exercise.exercise_id not in diagnostic_exercise_ids or not exercise.active:
                            continue
                        profile = await uow.adaptive_profiles.get_by_exercise(exercise.exercise_id)
                        if profile is None or not profile.active:
                            continue
                        exercise_attempts = attempts_by_exercise.get(exercise.exercise_id, [])
                        candidates.append(
                            ExerciseCandidate(
                                exercise=exercise,
                                adaptive_profile=profile,
                                lesson_position=lesson.position,
                                skill_mastery_scores={
                                    skill_id: mastery_by_skill.get(skill_id, 0.0)
                                    for skill_id in exercise.skill_ids
                                },
                                recent_attempt_count=len(exercise_attempts),
                                recent_correct_rate=None,
                                last_attempt_at=max(
                                    (attempt.started_at for attempt in exercise_attempts), default=None
                                ),
                            )
                        )
        return candidates
