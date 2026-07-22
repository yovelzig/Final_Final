"""PostgreSQL integration tests: AdaptiveDecisionRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.adaptive_learning.enums import (
    AdaptiveDecisionStatus,
    RecommendationReason,
    RecommendationType,
)
from stock_research_core.domain.adaptive_learning.models import AdaptiveDecision, LearningSession
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


async def _seed_learner_and_exercise(uow_factory) -> tuple[LearnerProfile, Exercise, Skill]:
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
    return stored_learner, exercise, stored_skill


def _decision(learner_id, exercise: Exercise, skill: Skill, **overrides) -> AdaptiveDecision:
    defaults: dict = dict(
        learner_id=learner_id,
        recommendation_type=RecommendationType.PRACTICE_EXERCISE,
        recommended_exercise_id=exercise.exercise_id,
        target_skill_ids=[skill.skill_id],
        reason_codes=[RecommendationReason.LOW_MASTERY],
        priority_score=0.5,
        policy_version="adaptive-policy-v1",
        explanation="This exercise builds a skill that is still developing.",
        generated_at=NOW,
    )
    defaults.update(overrides)
    return AdaptiveDecision(**defaults)


async def test_decision_create_and_get_round_trips_associations(uow_factory) -> None:
    learner, exercise, skill = await _seed_learner_and_exercise(uow_factory)
    decision = _decision(learner.learner_id, exercise, skill)

    async with uow_factory() as uow:
        created = await uow.adaptive_decisions.create_decision(decision)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.adaptive_decisions.get_decision(created.decision_id)

    assert fetched is not None
    assert fetched.target_skill_ids == [skill.skill_id]
    assert fetched.reason_codes == [RecommendationReason.LOW_MASTERY]
    assert fetched.explanation == decision.explanation


async def test_decision_update_status(uow_factory) -> None:
    learner, exercise, skill = await _seed_learner_and_exercise(uow_factory)
    decision = _decision(learner.learner_id, exercise, skill)
    async with uow_factory() as uow:
        created = await uow.adaptive_decisions.create_decision(decision)
        await uow.commit()

    updated = created.model_copy(
        update={"status": AdaptiveDecisionStatus.ACCEPTED, "accepted_at": NOW}
    )
    async with uow_factory() as uow:
        result = await uow.adaptive_decisions.update_decision(updated)
        await uow.commit()

    assert result.status == AdaptiveDecisionStatus.ACCEPTED
    assert result.accepted_at == NOW


async def test_list_recent_decisions_for_learner(uow_factory) -> None:
    learner, exercise, skill = await _seed_learner_and_exercise(uow_factory)
    async with uow_factory() as uow:
        first = await uow.adaptive_decisions.create_decision(_decision(learner.learner_id, exercise, skill))
        second = await uow.adaptive_decisions.create_decision(_decision(learner.learner_id, exercise, skill))
        await uow.commit()

    async with uow_factory() as uow:
        recent = await uow.adaptive_decisions.list_recent_decisions(learner.learner_id, limit=10)

    assert {d.decision_id for d in recent} == {first.decision_id, second.decision_id}


async def test_list_session_decisions(uow_factory) -> None:
    learner, exercise, skill = await _seed_learner_and_exercise(uow_factory)
    session = LearningSession(
        learner_id=learner.learner_id, goal_minutes=10, started_at=NOW, last_activity_at=NOW,
        policy_version="adaptive-policy-v1",
    )
    async with uow_factory() as uow:
        stored_session = await uow.learning_sessions.create_session(session)
        await uow.commit()

    in_session = _decision(learner.learner_id, exercise, skill, session_id=stored_session.session_id)
    outside_session = _decision(learner.learner_id, exercise, skill)

    async with uow_factory() as uow:
        created_in_session = await uow.adaptive_decisions.create_decision(in_session)
        await uow.adaptive_decisions.create_decision(outside_session)
        await uow.commit()

    async with uow_factory() as uow:
        session_decisions = await uow.adaptive_decisions.list_session_decisions(stored_session.session_id)

    assert {d.decision_id for d in session_decisions} == {created_in_session.decision_id}
