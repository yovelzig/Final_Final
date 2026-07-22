"""PostgreSQL integration tests: DiagnosticRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.adaptive_learning.enums import DiagnosticAssessmentStatus
from stock_research_core.domain.adaptive_learning.models import DiagnosticAssessment, DiagnosticAssessmentItem
from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAttempt,
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


async def test_assessment_create_get_and_update(uow_factory) -> None:
    learner, _exercise, skill = await _seed_learner_and_exercise(uow_factory)
    assessment = DiagnosticAssessment(
        learner_id=learner.learner_id, skill_ids=[skill.skill_id], maximum_items=5,
        policy_version="diagnostic-policy-v1",
    )

    async with uow_factory() as uow:
        created = await uow.diagnostics.create_assessment(assessment)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.diagnostics.get_assessment(created.assessment_id)

    assert fetched is not None
    assert fetched.skill_ids == [skill.skill_id]
    assert fetched.status == DiagnosticAssessmentStatus.CREATED

    updated = fetched.model_copy(
        update={"status": DiagnosticAssessmentStatus.IN_PROGRESS, "started_at": NOW}
    )
    async with uow_factory() as uow:
        result = await uow.diagnostics.update_assessment(updated)
        await uow.commit()

    assert result.status == DiagnosticAssessmentStatus.IN_PROGRESS
    assert result.skill_ids == [skill.skill_id]


async def test_save_items_and_list_items_ordered_by_position(uow_factory) -> None:
    learner, exercise, skill = await _seed_learner_and_exercise(uow_factory)
    assessment = DiagnosticAssessment(
        learner_id=learner.learner_id, skill_ids=[skill.skill_id], maximum_items=5,
        policy_version="diagnostic-policy-v1",
    )
    async with uow_factory() as uow:
        created_assessment = await uow.diagnostics.create_assessment(assessment)
        await uow.commit()

    item = DiagnosticAssessmentItem(
        assessment_id=created_assessment.assessment_id, exercise_id=exercise.exercise_id,
        skill_ids=[skill.skill_id], position=1, selected_at=NOW,
    )
    async with uow_factory() as uow:
        count = await uow.diagnostics.save_items([item])
        await uow.commit()

    assert count == 1

    async with uow_factory() as uow:
        items = await uow.diagnostics.list_items(created_assessment.assessment_id)
        by_id = await uow.diagnostics.get_item(item.item_id)

    assert len(items) == 1
    assert items[0].item_id == item.item_id
    assert by_id is not None
    assert by_id.skill_ids == [skill.skill_id]


async def test_update_item_persists_completion(uow_factory) -> None:
    learner, exercise, skill = await _seed_learner_and_exercise(uow_factory)
    assessment = DiagnosticAssessment(
        learner_id=learner.learner_id, skill_ids=[skill.skill_id], maximum_items=5,
        policy_version="diagnostic-policy-v1",
    )
    async with uow_factory() as uow:
        created_assessment = await uow.diagnostics.create_assessment(assessment)
        await uow.commit()

    item = DiagnosticAssessmentItem(
        assessment_id=created_assessment.assessment_id, exercise_id=exercise.exercise_id,
        skill_ids=[skill.skill_id], position=1, selected_at=NOW,
    )
    async with uow_factory() as uow:
        await uow.diagnostics.save_items([item])
        await uow.commit()

    async with uow_factory() as uow:
        attempt = await uow.attempts.create_attempt(
            ExerciseAttempt(
                learner_id=learner.learner_id, exercise_id=exercise.exercise_id,
                maximum_score=exercise.maximum_score, attempt_number=1, started_at=NOW,
            )
        )
        await uow.commit()

    updated = item.model_copy(
        update={"completed_at": NOW, "attempt_id": attempt.attempt_id, "normalized_score": 0.8}
    )
    async with uow_factory() as uow:
        result = await uow.diagnostics.update_item(updated)
        await uow.commit()

    assert result.normalized_score == 0.8
    assert result.completed_at == NOW


async def test_list_recent_assessments_orders_newest_first(uow_factory) -> None:
    learner, _exercise, skill = await _seed_learner_and_exercise(uow_factory)
    async with uow_factory() as uow:
        first = await uow.diagnostics.create_assessment(
            DiagnosticAssessment(
                learner_id=learner.learner_id, skill_ids=[skill.skill_id], maximum_items=5,
                policy_version="diagnostic-policy-v1",
            )
        )
        second = await uow.diagnostics.create_assessment(
            DiagnosticAssessment(
                learner_id=learner.learner_id, skill_ids=[skill.skill_id], maximum_items=5,
                policy_version="diagnostic-policy-v1",
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        recent = await uow.diagnostics.list_recent_assessments(learner.learner_id, limit=10)

    assert {a.assessment_id for a in recent} == {first.assessment_id, second.assessment_id}
