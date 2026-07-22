"""PostgreSQL integration tests: LearningSessionRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.adaptive_learning.enums import (
    AdaptiveDecisionStatus,
    LearningSessionStatus,
    LearningSessionType,
    RecommendationType,
)
from stock_research_core.domain.adaptive_learning.models import AdaptiveDecision, LearningSession, LearningSessionActivity
from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    LearnerProfile,
    Lesson,
    LearningModule,
    LearningPath,
    Skill,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_learner_and_exercise(uow_factory) -> tuple[LearnerProfile, Exercise]:
    learner = LearnerProfile(display_name="Learner")
    skill = Skill(
        code=f"MONEY_BASICS_{uuid4().hex[:8].upper()}",
        name="Money Basics",
        description="desc",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        stored_skill = await uow.curriculum.upsert_skill(skill)
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"path-{uuid4().hex[:8]}", title="Path", description="d",
                difficulty=DifficultyLevel.BEGINNER, position=0, estimated_minutes=10, published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code="mod", title="Module", description="d",
                position=0, estimated_minutes=10, published=True,
            )
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="lesson", title="Lesson", summary="s",
                content_markdown="# c", difficulty=DifficultyLevel.BEGINNER,
                status=LessonStatus.PUBLISHED, position=0, estimated_minutes=10,
                primary_skill_id=stored_skill.skill_id,
            )
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(
                lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE,
                prompt="prompt", explanation="explanation", difficulty=DifficultyLevel.BEGINNER,
                position=0, skill_ids=[stored_skill.skill_id], maximum_score=1.0, passing_score=1.0,
            )
        )
        await uow.commit()
    return stored_learner, exercise


async def _seed_decision(uow_factory, learner_id, exercise) -> AdaptiveDecision:
    decision = AdaptiveDecision(
        learner_id=learner_id,
        recommendation_type=RecommendationType.PRACTICE_EXERCISE,
        recommended_exercise_id=exercise.exercise_id,
        target_skill_ids=list(exercise.skill_ids),
        priority_score=0.5,
        policy_version="adaptive-policy-v1",
        explanation="explanation",
        generated_at=NOW,
    )
    async with uow_factory() as uow:
        stored = await uow.adaptive_decisions.create_decision(decision)
        await uow.commit()
    return stored


async def test_session_create_and_get(uow_factory) -> None:
    learner, _exercise = await _seed_learner_and_exercise(uow_factory)
    session = LearningSession(
        learner_id=learner.learner_id, goal_minutes=10, started_at=NOW, last_activity_at=NOW,
        policy_version="adaptive-policy-v1",
    )

    async with uow_factory() as uow:
        created = await uow.learning_sessions.create_session(session)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.learning_sessions.get_session(created.session_id)

    assert fetched is not None
    assert fetched.learner_id == learner.learner_id
    assert fetched.status == LearningSessionStatus.STARTED


async def test_session_update_persists_counters(uow_factory) -> None:
    learner, _exercise = await _seed_learner_and_exercise(uow_factory)
    session = LearningSession(
        learner_id=learner.learner_id, goal_minutes=10, started_at=NOW, last_activity_at=NOW,
        policy_version="adaptive-policy-v1",
    )
    async with uow_factory() as uow:
        created = await uow.learning_sessions.create_session(session)
        await uow.commit()

    updated = created.model_copy(
        update={
            "status": LearningSessionStatus.COMPLETED,
            "completed_at": NOW,
            "recommended_item_count": 3,
            "completed_item_count": 2,
            "correct_item_count": 1,
        }
    )
    async with uow_factory() as uow:
        result = await uow.learning_sessions.update_session(updated)
        await uow.commit()

    assert result.status == LearningSessionStatus.COMPLETED
    assert result.completed_item_count == 2


async def test_list_active_sessions_excludes_completed(uow_factory) -> None:
    learner, _exercise = await _seed_learner_and_exercise(uow_factory)
    active_session = LearningSession(
        learner_id=learner.learner_id, goal_minutes=10, started_at=NOW, last_activity_at=NOW,
        status=LearningSessionStatus.ACTIVE, policy_version="adaptive-policy-v1",
    )
    completed_session = LearningSession(
        learner_id=learner.learner_id, goal_minutes=10, started_at=NOW, last_activity_at=NOW,
        status=LearningSessionStatus.COMPLETED, completed_at=NOW, policy_version="adaptive-policy-v1",
    )

    async with uow_factory() as uow:
        await uow.learning_sessions.create_session(active_session)
        await uow.learning_sessions.create_session(completed_session)
        await uow.commit()

    async with uow_factory() as uow:
        active_only = await uow.learning_sessions.list_active_sessions(learner.learner_id)

    assert {s.session_id for s in active_only} == {active_session.session_id}


async def test_activity_add_get_update_and_list(uow_factory) -> None:
    learner, exercise = await _seed_learner_and_exercise(uow_factory)
    session = LearningSession(
        learner_id=learner.learner_id, goal_minutes=10, started_at=NOW, last_activity_at=NOW,
        policy_version="adaptive-policy-v1",
    )
    async with uow_factory() as uow:
        stored_session = await uow.learning_sessions.create_session(session)
        await uow.commit()
    decision = await _seed_decision(uow_factory, learner.learner_id, exercise)

    activity = LearningSessionActivity(
        session_id=stored_session.session_id, learner_id=learner.learner_id,
        exercise_id=exercise.exercise_id, decision_id=decision.decision_id, position=1,
        recommended_at=NOW,
    )
    async with uow_factory() as uow:
        created_activity = await uow.learning_sessions.add_activity(activity)
        await uow.commit()

    async with uow_factory() as uow:
        by_id = await uow.learning_sessions.get_activity(created_activity.activity_id)
        by_decision = await uow.learning_sessions.get_activity_by_decision(decision.decision_id)

    assert by_id is not None
    assert by_decision is not None
    assert by_id.activity_id == by_decision.activity_id

    updated = created_activity.model_copy(update={"completed_at": NOW})
    async with uow_factory() as uow:
        result = await uow.learning_sessions.update_activity(updated)
        await uow.commit()

    assert result.completed_at == NOW

    async with uow_factory() as uow:
        activities = await uow.learning_sessions.list_activities(stored_session.session_id)

    assert len(activities) == 1
    assert activities[0].position == 1
