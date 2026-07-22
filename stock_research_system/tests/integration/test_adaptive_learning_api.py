"""Integration tests for `/api/v1/adaptive/*` against the real PostgreSQL
test database, driven over HTTP - the full session -> recommendation ->
decision -> answer -> complete flow, plus the diagnostic flow.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import auth_headers
from stock_research_core.domain.adaptive_learning.models import ExerciseAdaptiveProfile
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType, FinancialSkillCategory, LessonStatus
from stock_research_core.domain.learning.models import Exercise, ExerciseOption, Lesson, LearningModule, LearningPath, Skill

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"adaptive-{uuid.uuid4().hex[:10]}@example.com"


async def _seed_adaptive_exercise(uow_factory) -> dict:
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
        await uow.adaptive_profiles.upsert(
            ExerciseAdaptiveProfile(
                exercise_id=exercise.exercise_id, base_difficulty_score=0.5, estimated_seconds=45,
                diagnostic_eligible=True, review_eligible=True,
            )
        )
        await uow.commit()
    return {"skill_id": skill.skill_id, "exercise_id": exercise.exercise_id, "correct_option_id": correct.option_id}


async def test_full_session_recommendation_and_answer_flow(api_client, uow_factory) -> None:
    world = await _seed_adaptive_exercise(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.post("/api/v1/adaptive/sessions", headers=headers, json={})
    assert r.status_code == 201
    session_id = r.json()["session_id"]

    r = await api_client.get(f"/api/v1/adaptive/sessions/{session_id}", headers=headers)
    assert r.status_code == 200

    r = await api_client.post(f"/api/v1/adaptive/sessions/{session_id}/next", headers=headers, json={})
    assert r.status_code == 200
    recommendation = r.json()
    decision_id = recommendation["decision"]["decision_id"]
    assert recommendation["exercise"] is not None
    assert "is_correct" not in recommendation["exercise"]

    r = await api_client.post(f"/api/v1/adaptive/decisions/{decision_id}/accept", headers=headers)
    assert r.status_code == 200

    r = await api_client.post(f"/api/v1/adaptive/decisions/{decision_id}/start", headers=headers, json={})
    assert r.status_code == 200

    r = await api_client.post(
        f"/api/v1/adaptive/decisions/{decision_id}/answers", headers=headers,
        json={"selected_option_ids": [str(world["correct_option_id"])]},
    )
    assert r.status_code == 200
    assert r.json()["session"]["correct_item_count"] == 1

    r = await api_client.post(f"/api/v1/adaptive/sessions/{session_id}/complete", headers=headers)
    assert r.status_code == 200
    assert r.json()["session"]["status"] == "COMPLETED"


async def test_session_ownership_is_enforced(api_client, uow_factory) -> None:
    await _seed_adaptive_exercise(uow_factory)
    owner_headers = await auth_headers(api_client, email=_email())
    other_headers = await auth_headers(api_client, email=_email())

    r = await api_client.post("/api/v1/adaptive/sessions", headers=owner_headers, json={})
    session_id = r.json()["session_id"]

    r = await api_client.get(f"/api/v1/adaptive/sessions/{session_id}", headers=other_headers)
    assert r.status_code == 404


async def test_full_diagnostic_flow(api_client, uow_factory) -> None:
    world = await _seed_adaptive_exercise(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(
        "/api/v1/adaptive/diagnostics", headers=headers,
        json={"skill_ids": [str(world["skill_id"])], "maximum_items": 5},
    )
    assert r.status_code == 201
    diag = r.json()
    assessment_id = diag["assessment"]["assessment_id"]
    assert len(diag["items"]) == 1
    item_id = diag["items"][0]["item_id"]

    r = await api_client.get(f"/api/v1/adaptive/diagnostics/{assessment_id}", headers=headers)
    assert r.status_code == 200

    r = await api_client.post(
        f"/api/v1/adaptive/diagnostics/{assessment_id}/items/{item_id}/start", headers=headers, json={}
    )
    assert r.status_code == 200

    r = await api_client.post(
        f"/api/v1/adaptive/diagnostics/{assessment_id}/items/{item_id}/result", headers=headers,
        json={"selected_option_ids": [str(world["correct_option_id"])]},
    )
    assert r.status_code == 200
    assert r.json()["skill_scores"][str(world["skill_id"])] == 1.0

    r = await api_client.post(f"/api/v1/adaptive/diagnostics/{assessment_id}/complete", headers=headers)
    assert r.status_code == 200
    assert r.json()["assessment"]["status"] == "COMPLETED"


async def test_adaptive_endpoints_require_authentication(api_client) -> None:
    response = await api_client.post("/api/v1/adaptive/sessions", json={})
    assert response.status_code == 401
