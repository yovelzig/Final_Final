"""Unit tests for `AdaptiveLearningService`.

Uses fake in-memory repository implementations and a fake Unit of Work -
no SQLAlchemy or PostgreSQL is involved anywhere in this file. The real
deterministic policies are used (not further fakes) so these tests also
exercise the service/policy integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.adaptive_learning.policies import (
    DeterministicReviewSchedulingPolicy,
    RuleBasedAdaptivePolicy,
    RuleBasedDiagnosticPolicy,
    RuleBasedDifficultyPolicy,
)
from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.exceptions import (
    InactiveLearnerError,
    InvalidDecisionStateError,
    LearnerNotFoundError,
)
from stock_research_core.application.learning.models import LearningActivityResult
from stock_research_core.domain.adaptive_learning.enums import (
    AdaptiveDecisionStatus,
    LearningSessionStatus,
    LearningSessionType,
    RecommendationType,
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
from stock_research_core.domain.learning.enums import (
    AttemptStatus,
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseAttempt,
    LearnerProfile,
    LearningModule,
    LearningPath,
    Lesson,
    Misconception,
    Skill,
    SkillMastery,
    UserProgress,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Fake repositories (one in-memory dict each, mirroring the SQL repositories)
# ---------------------------------------------------------------------------


class FakeLearnerRepository:
    def __init__(self) -> None:
        self.learners: dict[UUID, LearnerProfile] = {}

    async def get(self, learner_id: UUID) -> LearnerProfile | None:
        return self.learners.get(learner_id)


class FakeCurriculumRepository:
    def __init__(self) -> None:
        self.paths: dict[UUID, LearningPath] = {}
        self.modules: dict[UUID, LearningModule] = {}
        self.lessons: dict[UUID, Lesson] = {}
        self.exercises: dict[UUID, Exercise] = {}
        self.skills: dict[UUID, Skill] = {}

    async def list_skills(self, active_only: bool = True):
        values = list(self.skills.values())
        return [s for s in values if s.active] if active_only else values

    async def list_paths(self, published_only: bool = True):
        values = list(self.paths.values())
        return [p for p in values if p.published] if published_only else values

    async def list_modules(self, path_id: UUID):
        return sorted((m for m in self.modules.values() if m.path_id == path_id), key=lambda m: m.position)

    async def list_lessons(self, module_id: UUID):
        return sorted(
            (lesson for lesson in self.lessons.values() if lesson.module_id == module_id),
            key=lambda lesson: lesson.position,
        )

    async def get_lesson(self, lesson_id: UUID):
        return self.lessons.get(lesson_id)

    async def list_exercises(self, lesson_id: UUID):
        return sorted(
            (ex for ex in self.exercises.values() if ex.lesson_id == lesson_id), key=lambda ex: ex.position
        )

    async def get_exercise(self, exercise_id: UUID):
        return self.exercises.get(exercise_id)


class FakeAttemptRepository:
    def __init__(self) -> None:
        self.attempts: dict[UUID, ExerciseAttempt] = {}

    async def create_attempt(self, attempt: ExerciseAttempt) -> ExerciseAttempt:
        self.attempts[attempt.attempt_id] = attempt
        return attempt

    async def get_attempt(self, attempt_id: UUID):
        return self.attempts.get(attempt_id)

    async def list_attempts(self, learner_id: UUID, exercise_id: UUID | None = None):
        values = [a for a in self.attempts.values() if a.learner_id == learner_id]
        if exercise_id is not None:
            values = [a for a in values if a.exercise_id == exercise_id]
        return sorted(values, key=lambda a: a.started_at)


class FakeMasteryRepository:
    def __init__(self) -> None:
        self.mastery: dict[tuple[UUID, UUID], SkillMastery] = {}

    async def upsert(self, mastery: SkillMastery) -> SkillMastery:
        self.mastery[(mastery.learner_id, mastery.skill_id)] = mastery
        return mastery

    async def get(self, learner_id: UUID, skill_id: UUID):
        return self.mastery.get((learner_id, skill_id))

    async def list_for_learner(self, learner_id: UUID):
        return [m for m in self.mastery.values() if m.learner_id == learner_id]


class FakeProgressRepository:
    def __init__(self) -> None:
        self.progress: dict[UUID, UserProgress] = {}

    async def list_for_learner(self, learner_id: UUID):
        return [p for p in self.progress.values() if p.learner_id == learner_id]


class FakeMisconceptionRepository:
    def __init__(self) -> None:
        self.misconceptions: dict[UUID, Misconception] = {}

    async def list_active(self, learner_id: UUID):
        from stock_research_core.domain.learning.enums import MisconceptionStatus

        return [
            m
            for m in self.misconceptions.values()
            if m.learner_id == learner_id and m.status == MisconceptionStatus.ACTIVE
        ]


class FakeAdaptiveProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[UUID, ExerciseAdaptiveProfile] = {}

    async def upsert(self, profile: ExerciseAdaptiveProfile) -> ExerciseAdaptiveProfile:
        self.profiles[profile.exercise_id] = profile
        return profile

    async def get_by_exercise(self, exercise_id: UUID):
        return self.profiles.get(exercise_id)

    async def list_active(self, diagnostic_only: bool = False, review_only: bool = False):
        values = [p for p in self.profiles.values() if p.active]
        if diagnostic_only:
            values = [p for p in values if p.diagnostic_eligible]
        if review_only:
            values = [p for p in values if p.review_eligible]
        return values


class FakeLearningSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, LearningSession] = {}
        self.activities: dict[UUID, LearningSessionActivity] = {}

    async def create_session(self, session: LearningSession) -> LearningSession:
        self.sessions[session.session_id] = session
        return session

    async def get_session(self, session_id: UUID):
        return self.sessions.get(session_id)

    async def update_session(self, session: LearningSession) -> LearningSession:
        self.sessions[session.session_id] = session
        return session

    async def list_active_sessions(self, learner_id: UUID):
        active_statuses = (LearningSessionStatus.STARTED, LearningSessionStatus.ACTIVE)
        return [
            s for s in self.sessions.values() if s.learner_id == learner_id and s.status in active_statuses
        ]

    async def add_activity(self, activity: LearningSessionActivity) -> LearningSessionActivity:
        self.activities[activity.activity_id] = activity
        return activity

    async def get_activity(self, activity_id: UUID):
        return self.activities.get(activity_id)

    async def get_activity_by_decision(self, decision_id: UUID):
        for activity in self.activities.values():
            if activity.decision_id == decision_id:
                return activity
        return None

    async def update_activity(self, activity: LearningSessionActivity) -> LearningSessionActivity:
        self.activities[activity.activity_id] = activity
        return activity

    async def list_activities(self, session_id: UUID):
        return sorted(
            (a for a in self.activities.values() if a.session_id == session_id),
            key=lambda a: a.position,
        )


class FakeDiagnosticRepository:
    def __init__(self) -> None:
        self.assessments: dict[UUID, DiagnosticAssessment] = {}
        self.items: dict[UUID, DiagnosticAssessmentItem] = {}

    async def create_assessment(self, assessment: DiagnosticAssessment) -> DiagnosticAssessment:
        self.assessments[assessment.assessment_id] = assessment
        return assessment

    async def get_assessment(self, assessment_id: UUID):
        return self.assessments.get(assessment_id)

    async def update_assessment(self, assessment: DiagnosticAssessment) -> DiagnosticAssessment:
        self.assessments[assessment.assessment_id] = assessment
        return assessment

    async def save_items(self, items: list[DiagnosticAssessmentItem]) -> int:
        for item in items:
            self.items[item.item_id] = item
        return len(items)

    async def get_item(self, item_id: UUID):
        return self.items.get(item_id)

    async def update_item(self, item: DiagnosticAssessmentItem) -> DiagnosticAssessmentItem:
        self.items[item.item_id] = item
        return item

    async def list_items(self, assessment_id: UUID):
        return sorted(
            (item for item in self.items.values() if item.assessment_id == assessment_id),
            key=lambda item: item.position,
        )


class FakeReviewScheduleRepository:
    def __init__(self) -> None:
        self.schedules: dict[tuple[UUID, UUID], SkillReviewSchedule] = {}

    async def upsert(self, schedule: SkillReviewSchedule) -> SkillReviewSchedule:
        self.schedules[(schedule.learner_id, schedule.skill_id)] = schedule
        return schedule

    async def get(self, learner_id: UUID, skill_id: UUID):
        return self.schedules.get((learner_id, skill_id))

    async def list_for_learner(self, learner_id: UUID):
        return [s for s in self.schedules.values() if s.learner_id == learner_id]

    async def list_due(self, learner_id: UUID, as_of: datetime):
        return [
            s
            for s in self.schedules.values()
            if s.learner_id == learner_id and s.next_review_at is not None and s.next_review_at <= as_of
        ]


class FakeAdaptiveDecisionRepository:
    def __init__(self) -> None:
        self.decisions: dict[UUID, AdaptiveDecision] = {}

    async def create_decision(self, decision: AdaptiveDecision) -> AdaptiveDecision:
        self.decisions[decision.decision_id] = decision
        return decision

    async def get_decision(self, decision_id: UUID):
        return self.decisions.get(decision_id)

    async def update_decision(self, decision: AdaptiveDecision) -> AdaptiveDecision:
        self.decisions[decision.decision_id] = decision
        return decision


class FakeUnitOfWork:
    def __init__(self, factory: "FakeUnitOfWorkFactory") -> None:
        self.learners = factory.learners
        self.curriculum = factory.curriculum
        self.attempts = factory.attempts
        self.mastery = factory.mastery
        self.progress = factory.progress
        self.misconceptions = factory.misconceptions
        self.adaptive_profiles = factory.adaptive_profiles
        self.learning_sessions = factory.learning_sessions
        self.diagnostics = factory.diagnostics
        self.review_schedules = factory.review_schedules
        self.adaptive_decisions = factory.adaptive_decisions
        self.committed = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


class FakeUnitOfWorkFactory:
    def __init__(self) -> None:
        self.learners = FakeLearnerRepository()
        self.curriculum = FakeCurriculumRepository()
        self.attempts = FakeAttemptRepository()
        self.mastery = FakeMasteryRepository()
        self.progress = FakeProgressRepository()
        self.misconceptions = FakeMisconceptionRepository()
        self.adaptive_profiles = FakeAdaptiveProfileRepository()
        self.learning_sessions = FakeLearningSessionRepository()
        self.diagnostics = FakeDiagnosticRepository()
        self.review_schedules = FakeReviewScheduleRepository()
        self.adaptive_decisions = FakeAdaptiveDecisionRepository()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self)


def _make_service(factory: FakeUnitOfWorkFactory, clock=lambda: NOW) -> AdaptiveLearningService:
    return AdaptiveLearningService(
        unit_of_work_factory=factory,
        adaptive_policy=RuleBasedAdaptivePolicy(),
        difficulty_policy=RuleBasedDifficultyPolicy(),
        review_policy=DeterministicReviewSchedulingPolicy(),
        diagnostic_policy=RuleBasedDiagnosticPolicy(),
        clock=clock,
    )


async def _seed_single_exercise_curriculum(
    factory: FakeUnitOfWorkFactory,
) -> tuple[Skill, Exercise]:
    skill = Skill(
        code="MONEY_BASICS",
        name="Money Basics",
        description="desc",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    factory.curriculum.skills[skill.skill_id] = skill

    path = LearningPath(
        code="path", title="Path", description="d", difficulty=DifficultyLevel.BEGINNER,
        position=0, estimated_minutes=10, published=True,
    )
    factory.curriculum.paths[path.path_id] = path

    module = LearningModule(
        path_id=path.path_id, code="mod", title="Module", description="d",
        position=0, estimated_minutes=10, published=True,
    )
    factory.curriculum.modules[module.module_id] = module

    lesson = Lesson(
        module_id=module.module_id, code="lesson", title="Lesson", summary="s",
        content_markdown="# c", difficulty=DifficultyLevel.BEGINNER,
        status=LessonStatus.PUBLISHED, position=0, estimated_minutes=10,
        primary_skill_id=skill.skill_id,
    )
    factory.curriculum.lessons[lesson.lesson_id] = lesson

    exercise = Exercise(
        lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE,
        prompt="prompt", explanation="explanation", difficulty=DifficultyLevel.BEGINNER,
        position=0, skill_ids=[skill.skill_id], maximum_score=1.0, passing_score=1.0,
    )
    factory.curriculum.exercises[exercise.exercise_id] = exercise

    profile = ExerciseAdaptiveProfile(
        exercise_id=exercise.exercise_id, base_difficulty_score=0.5, estimated_seconds=45, active=True
    )
    factory.adaptive_profiles.profiles[exercise.exercise_id] = profile

    return skill, exercise


def _learner(**overrides) -> LearnerProfile:
    defaults = dict(display_name="Learner", daily_goal_minutes=10)
    defaults.update(overrides)
    return LearnerProfile(**defaults)


# ---------------------------------------------------------------------------
# start_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_requires_existing_learner() -> None:
    factory = FakeUnitOfWorkFactory()
    service = _make_service(factory)
    with pytest.raises(LearnerNotFoundError):
        await service.start_session(learner_id=uuid4())


@pytest.mark.asyncio
async def test_start_session_rejects_inactive_learner() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner(active=False)
    factory.learners.learners[learner.learner_id] = learner
    service = _make_service(factory)
    with pytest.raises(InactiveLearnerError):
        await service.start_session(learner_id=learner.learner_id)


@pytest.mark.asyncio
async def test_start_session_reuses_existing_active_daily_session() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    service = _make_service(factory)

    first = await service.start_session(learner_id=learner.learner_id)
    second = await service.start_session(learner_id=learner.learner_id)

    assert first.session_id == second.session_id
    assert len(factory.learning_sessions.sessions) == 1


@pytest.mark.asyncio
async def test_start_session_defaults_goal_minutes_to_learner_daily_goal() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner(daily_goal_minutes=25)
    factory.learners.learners[learner.learner_id] = learner
    service = _make_service(factory)

    session = await service.start_session(learner_id=learner.learner_id)

    assert session.goal_minutes == 25


# ---------------------------------------------------------------------------
# recommend_next
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_next_returns_session_complete_when_goal_reached() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner(daily_goal_minutes=5)
    factory.learners.learners[learner.learner_id] = learner
    later_clock = lambda: NOW + timedelta(minutes=10)
    service = _make_service(factory, clock=lambda: NOW)

    session = await service.start_session(learner_id=learner.learner_id)

    late_service = _make_service(factory, clock=later_clock)
    recommendation = await late_service.recommend_next(learner_id=learner.learner_id, session_id=session.session_id)

    assert recommendation.decision.recommendation_type == RecommendationType.SESSION_COMPLETE


@pytest.mark.asyncio
async def test_recommend_next_returns_no_eligible_content_when_no_candidates() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    service = _make_service(factory)
    session = await service.start_session(learner_id=learner.learner_id)

    recommendation = await service.recommend_next(learner_id=learner.learner_id, session_id=session.session_id)

    assert recommendation.decision.recommendation_type == RecommendationType.NO_ELIGIBLE_CONTENT


@pytest.mark.asyncio
async def test_recommend_next_recommends_an_eligible_exercise_and_merges_difficulty() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    _skill, exercise = await _seed_single_exercise_curriculum(factory)
    service = _make_service(factory)
    session = await service.start_session(learner_id=learner.learner_id)

    recommendation = await service.recommend_next(learner_id=learner.learner_id, session_id=session.session_id)

    assert recommendation.decision.recommended_exercise_id == exercise.exercise_id
    assert recommendation.exercise is not None
    assert recommendation.decision.recommended_difficulty_score is not None
    # An activity should now be tracked in the session.
    activities = await factory.learning_sessions.list_activities(session.session_id)
    assert len(activities) == 1


@pytest.mark.asyncio
async def test_recommend_next_rejects_session_from_a_different_learner() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    other_learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    factory.learners.learners[other_learner.learner_id] = other_learner
    service = _make_service(factory)
    session = await service.start_session(learner_id=learner.learner_id)

    with pytest.raises(InvalidDecisionStateError):
        await service.recommend_next(learner_id=other_learner.learner_id, session_id=session.session_id)


# ---------------------------------------------------------------------------
# accept / start / skip recommendation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_recommendation_transitions_status() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    await _seed_single_exercise_curriculum(factory)
    service = _make_service(factory)
    session = await service.start_session(learner_id=learner.learner_id)
    recommendation = await service.recommend_next(learner_id=learner.learner_id, session_id=session.session_id)

    accepted = await service.accept_recommendation(decision_id=recommendation.decision.decision_id)

    assert accepted.status == AdaptiveDecisionStatus.ACCEPTED
    assert accepted.accepted_at is not None


@pytest.mark.asyncio
async def test_start_recommended_exercise_is_idempotent() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    await _seed_single_exercise_curriculum(factory)
    service = _make_service(factory)
    session = await service.start_session(learner_id=learner.learner_id)
    recommendation = await service.recommend_next(learner_id=learner.learner_id, session_id=session.session_id)

    first_attempt = await service.start_recommended_exercise(decision_id=recommendation.decision.decision_id)
    second_attempt = await service.start_recommended_exercise(decision_id=recommendation.decision.decision_id)

    assert first_attempt.attempt_id == second_attempt.attempt_id


@pytest.mark.asyncio
async def test_skip_recommendation_transitions_status_and_activity() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    await _seed_single_exercise_curriculum(factory)
    service = _make_service(factory)
    session = await service.start_session(learner_id=learner.learner_id)
    recommendation = await service.recommend_next(learner_id=learner.learner_id, session_id=session.session_id)

    skipped = await service.skip_recommendation(decision_id=recommendation.decision.decision_id)

    assert skipped.status == AdaptiveDecisionStatus.SKIPPED
    activity = await factory.learning_sessions.get_activity_by_decision(recommendation.decision.decision_id)
    assert activity.skipped_at is not None


@pytest.mark.asyncio
async def test_get_attempt_id_for_decision_requires_started_attempt() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    await _seed_single_exercise_curriculum(factory)
    service = _make_service(factory)
    session = await service.start_session(learner_id=learner.learner_id)
    recommendation = await service.recommend_next(learner_id=learner.learner_id, session_id=session.session_id)

    with pytest.raises(InvalidDecisionStateError):
        await service.get_attempt_id_for_decision(decision_id=recommendation.decision.decision_id)

    await service.start_recommended_exercise(decision_id=recommendation.decision.decision_id)
    attempt_id = await service.get_attempt_id_for_decision(decision_id=recommendation.decision.decision_id)
    assert attempt_id is not None


# ---------------------------------------------------------------------------
# record_completed_activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_completed_activity_schedules_a_review() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    skill, _exercise = await _seed_single_exercise_curriculum(factory)
    service = _make_service(factory)
    session = await service.start_session(learner_id=learner.learner_id)
    recommendation = await service.recommend_next(learner_id=learner.learner_id, session_id=session.session_id)
    attempt = await service.start_recommended_exercise(decision_id=recommendation.decision.decision_id)

    graded_attempt = attempt.model_copy(
        update={
            "status": AttemptStatus.GRADED,
            "score": 1.0,
            "is_correct": True,
            "submitted_at": attempt.started_at,
            "graded_at": attempt.started_at,
        }
    )
    answer = ExerciseAnswer(attempt_id=graded_attempt.attempt_id, selected_option_ids=[uuid4()])
    result = LearningActivityResult(attempt=graded_attempt, answer=answer)

    summary = await service.record_completed_activity(
        decision_id=recommendation.decision.decision_id, learning_activity_result=result
    )

    assert summary.session.completed_item_count == 1
    assert summary.session.correct_item_count == 1
    assert len(summary.reviews_scheduled) == 1
    schedule = await factory.review_schedules.get(learner.learner_id, skill.skill_id)
    assert schedule is not None


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_diagnostic_creates_assessment_and_items() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    skill, exercise = await _seed_single_exercise_curriculum(factory)
    factory.adaptive_profiles.profiles[exercise.exercise_id] = factory.adaptive_profiles.profiles[
        exercise.exercise_id
    ].model_copy(update={"diagnostic_eligible": True})
    service = _make_service(factory)

    summary = await service.start_diagnostic(learner_id=learner.learner_id, skill_ids=[skill.skill_id])

    assert summary.assessment.learner_id == learner.learner_id
    assert len(summary.items) == 1


@pytest.mark.asyncio
async def test_complete_diagnostic_requires_at_least_one_completed_item() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    skill, exercise = await _seed_single_exercise_curriculum(factory)
    factory.adaptive_profiles.profiles[exercise.exercise_id] = factory.adaptive_profiles.profiles[
        exercise.exercise_id
    ].model_copy(update={"diagnostic_eligible": True})
    service = _make_service(factory)
    summary = await service.start_diagnostic(learner_id=learner.learner_id, skill_ids=[skill.skill_id])

    with pytest.raises(InvalidDecisionStateError):
        await service.complete_diagnostic(assessment_id=summary.assessment.assessment_id)


@pytest.mark.asyncio
async def test_complete_diagnostic_updates_mastery_from_completed_items() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    skill, exercise = await _seed_single_exercise_curriculum(factory)
    factory.adaptive_profiles.profiles[exercise.exercise_id] = factory.adaptive_profiles.profiles[
        exercise.exercise_id
    ].model_copy(update={"diagnostic_eligible": True})
    service = _make_service(factory)
    summary = await service.start_diagnostic(learner_id=learner.learner_id, skill_ids=[skill.skill_id])
    item = summary.items[0]

    attempt = await service.start_diagnostic_item(
        assessment_id=summary.assessment.assessment_id, item_id=item.item_id
    )
    graded_attempt = attempt.model_copy(
        update={
            "status": AttemptStatus.GRADED,
            "score": 1.0,
            "is_correct": True,
            "submitted_at": attempt.started_at,
            "graded_at": attempt.started_at,
        }
    )
    answer = ExerciseAnswer(attempt_id=graded_attempt.attempt_id, selected_option_ids=[uuid4()])
    result = LearningActivityResult(attempt=graded_attempt, answer=answer)
    await service.record_diagnostic_result(
        assessment_id=summary.assessment.assessment_id, item_id=item.item_id, learning_activity_result=result
    )

    final_summary = await service.complete_diagnostic(assessment_id=summary.assessment.assessment_id)

    assert final_summary.assessment.status.value == "COMPLETED"
    mastery = await factory.mastery.get(learner.learner_id, skill.skill_id)
    assert mastery is not None
    assert mastery.mastery_score == 1.0
