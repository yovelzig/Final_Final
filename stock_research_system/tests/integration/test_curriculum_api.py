"""Integration tests for `/api/v1/learning-paths`, `/modules`, `/lessons`,
`/exercises`, and attempt/answer endpoints against the real PostgreSQL
test database, driven over HTTP.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import auth_headers
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType, FinancialSkillCategory, LessonStatus
from stock_research_core.domain.learning.models import Exercise, ExerciseOption, Lesson, LearningModule, LearningPath, Skill

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"curric-{uuid.uuid4().hex[:10]}@example.com"


async def _seed_lesson_with_exercise(uow_factory) -> dict:
    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(
                code=f"SKILL_{uuid.uuid4().hex[:8].upper()}", name="Skill", description="d",
                category=FinancialSkillCategory.MONEY_BASICS, difficulty=DifficultyLevel.BEGINNER,
            )
        )
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"path-{uuid.uuid4().hex[:8]}", title="Path", description="d",
                difficulty=DifficultyLevel.BEGINNER, position=0, estimated_minutes=10, published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code="mod", title="Module", description="d", position=0,
                estimated_minutes=10, published=True,
            )
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="lesson", title="Lesson", summary="s",
                content_markdown="# c", difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED,
                position=0, estimated_minutes=10, primary_skill_id=skill.skill_id,
            )
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(
                lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE, prompt="P?",
                explanation="E.", difficulty=DifficultyLevel.BEGINNER, position=0, skill_ids=[skill.skill_id],
                maximum_score=1.0, passing_score=1.0,
            )
        )
        correct = ExerciseOption(exercise_id=exercise.exercise_id, option_key="a", content="Right", position=0, is_correct=True)
        incorrect = ExerciseOption(exercise_id=exercise.exercise_id, option_key="b", content="Wrong", position=1, is_correct=False)
        await uow.curriculum.upsert_options([correct, incorrect])
        await uow.commit()
    return {
        "path_id": path.path_id, "module_id": module.module_id, "lesson_id": lesson.lesson_id,
        "exercise_id": exercise.exercise_id, "correct_option_id": correct.option_id,
    }


async def test_full_catalog_and_attempt_flow(api_client, uow_factory) -> None:
    world = await _seed_lesson_with_exercise(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.get("/api/v1/learning-paths", headers=headers)
    assert r.status_code == 200
    assert any(p["path_id"] == str(world["path_id"]) for p in r.json())

    r = await api_client.get(f"/api/v1/learning-paths/{world['path_id']}", headers=headers)
    assert r.status_code == 200

    r = await api_client.get(f"/api/v1/learning-paths/{world['path_id']}/modules", headers=headers)
    assert r.status_code == 200
    assert any(m["module_id"] == str(world["module_id"]) for m in r.json())

    r = await api_client.get(f"/api/v1/modules/{world['module_id']}/lessons", headers=headers)
    assert r.status_code == 200
    assert any(lesson["lesson_id"] == str(world["lesson_id"]) for lesson in r.json())

    r = await api_client.get(f"/api/v1/lessons/{world['lesson_id']}/exercises", headers=headers)
    assert r.status_code == 200
    exercises = r.json()
    assert len(exercises) == 1
    exercise = exercises[0]
    assert "is_correct" not in exercise
    for option in exercise["options"]:
        assert "is_correct" not in option
        assert "feedback" not in option

    r = await api_client.get(f"/api/v1/exercises/{world['exercise_id']}", headers=headers)
    assert r.status_code == 200
    single_exercise = r.json()
    assert single_exercise["exercise_id"] == str(world["exercise_id"])
    assert "is_correct" not in single_exercise
    for option in single_exercise["options"]:
        assert "is_correct" not in option
        assert "feedback" not in option

    r = await api_client.get(f"/api/v1/exercises/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    assert r.status_code in (200, 201)
    attempt_id = r.json()["attempt_id"]

    r = await api_client.get(f"/api/v1/attempts/{attempt_id}", headers=headers)
    assert r.status_code == 200

    r = await api_client.post(
        f"/api/v1/attempts/{attempt_id}/answers", headers=headers,
        json={"selected_option_ids": [str(world["correct_option_id"])]},
    )
    assert r.status_code == 200
    assert r.json()["attempt"]["is_correct"] is True


async def test_nonexistent_learning_path_returns_404(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    response = await api_client.get(f"/api/v1/learning-paths/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_attempt_ownership_is_enforced(api_client, uow_factory) -> None:
    world = await _seed_lesson_with_exercise(uow_factory)
    owner_headers = await auth_headers(api_client, email=_email())
    other_headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(
        f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=owner_headers, json={}
    )
    attempt_id = r.json()["attempt_id"]

    r = await api_client.get(f"/api/v1/attempts/{attempt_id}", headers=other_headers)
    assert r.status_code == 404

    r = await api_client.post(
        f"/api/v1/attempts/{attempt_id}/answers", headers=other_headers,
        json={"selected_option_ids": [str(world["correct_option_id"])]},
    )
    assert r.status_code == 404


async def test_catalog_requires_authentication(api_client) -> None:
    response = await api_client.get("/api/v1/learning-paths")
    assert response.status_code == 401
