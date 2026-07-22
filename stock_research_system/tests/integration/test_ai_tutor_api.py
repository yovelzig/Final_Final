"""Integration tests for `/api/v1/tutor/*` against the real PostgreSQL
test database, driven over HTTP - conversation lifecycle for
GENERAL_EDUCATION/LESSON_HELP contexts, ownership, and the learner-safe
citation shape (no chunk_id/vector/prompt text).
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import auth_headers
from stock_research_core.domain.learning.enums import DifficultyLevel, LessonStatus, FinancialSkillCategory
from stock_research_core.domain.learning.models import Lesson, LearningModule, LearningPath, Skill

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"tutor-{uuid.uuid4().hex[:10]}@example.com"


async def _seed_lesson(uow_factory) -> str:
    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(code=f"SKILL_{uuid.uuid4().hex[:8].upper()}", name="Skill", description="d", category=FinancialSkillCategory.MONEY_BASICS, difficulty=DifficultyLevel.BEGINNER)
        )
        path = await uow.curriculum.upsert_path(
            LearningPath(code=f"path-{uuid.uuid4().hex[:8]}", title="Path", description="d", difficulty=DifficultyLevel.BEGINNER, position=0, estimated_minutes=10, published=True)
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(path_id=path.path_id, code="mod", title="Module", description="d", position=0, estimated_minutes=10, published=True)
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(module_id=module.module_id, code="lesson", title="Lesson", summary="s", content_markdown="# c", difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED, position=0, estimated_minutes=10, primary_skill_id=skill.skill_id)
        )
        await uow.commit()
    return str(lesson.lesson_id)


async def test_general_education_conversation_lifecycle(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(
        "/api/v1/tutor/conversations", headers=headers, json={"context_type": "GENERAL_EDUCATION"}
    )
    assert r.status_code == 201
    conversation_id = r.json()["conversation_id"]
    assert r.json()["status"] == "ACTIVE"

    r = await api_client.get("/api/v1/tutor/conversations", headers=headers)
    assert r.status_code == 200
    assert any(c["conversation_id"] == conversation_id for c in r.json())

    r = await api_client.get(f"/api/v1/tutor/conversations/{conversation_id}", headers=headers)
    assert r.status_code == 200

    r = await api_client.post(
        f"/api/v1/tutor/conversations/{conversation_id}/messages", headers=headers,
        json={"question": "What is a diversified portfolio?"},
    )
    assert r.status_code == 200
    ask = r.json()
    assert ask["answer_markdown"]
    for citation in ask["citations"]:
        assert "chunk_id" not in citation
        assert "vector" not in citation

    r = await api_client.get(f"/api/v1/tutor/conversations/{conversation_id}/messages", headers=headers)
    assert r.status_code == 200
    messages = r.json()
    assert [m["role"] for m in messages] == ["USER", "ASSISTANT"]

    r = await api_client.post(f"/api/v1/tutor/conversations/{conversation_id}/close", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "CLOSED"

    r = await api_client.post(
        f"/api/v1/tutor/conversations/{conversation_id}/messages", headers=headers,
        json={"question": "Another question?"},
    )
    assert r.status_code == 409


async def test_lesson_help_conversation_requires_lesson_id(api_client, uow_factory) -> None:
    lesson_id = await _seed_lesson(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.post("/api/v1/tutor/conversations", headers=headers, json={"context_type": "LESSON_HELP"})
    assert r.status_code == 422

    r = await api_client.post(
        "/api/v1/tutor/conversations", headers=headers,
        json={"context_type": "LESSON_HELP", "lesson_id": lesson_id},
    )
    assert r.status_code == 201
    assert r.json()["lesson_id"] == lesson_id


async def test_conversation_ownership_is_enforced(api_client) -> None:
    owner_headers = await auth_headers(api_client, email=_email())
    other_headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(
        "/api/v1/tutor/conversations", headers=owner_headers, json={"context_type": "GENERAL_EDUCATION"}
    )
    conversation_id = r.json()["conversation_id"]

    r = await api_client.get(f"/api/v1/tutor/conversations/{conversation_id}", headers=other_headers)
    assert r.status_code == 404


async def test_tutor_endpoints_require_authentication(api_client) -> None:
    response = await api_client.get("/api/v1/tutor/conversations")
    assert response.status_code == 401
