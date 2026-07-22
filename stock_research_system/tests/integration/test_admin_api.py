"""Integration tests for `/api/v1/admin/*` against the real PostgreSQL
test database, driven over HTTP - account administration (ADMIN-only),
curriculum authoring (CONTENT_EDITOR-or-ADMIN), and knowledge-base
document upload.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import auth_headers, promote_role

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"admin-{uuid.uuid4().hex[:10]}@example.com"


async def _admin_headers(api_client, uow_factory) -> dict[str, str]:
    email = _email()
    body_headers = await auth_headers(api_client, email=email)
    me = await api_client.get("/api/v1/auth/me", headers=body_headers)
    account_id = me.json()["account"]["account_id"]
    await promote_role(uow_factory, account_id=account_id, role="ADMIN")
    login = await api_client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPassword123!"})
    return {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}


async def _content_editor_headers(api_client, uow_factory) -> dict[str, str]:
    email = _email()
    body_headers = await auth_headers(api_client, email=email)
    me = await api_client.get("/api/v1/auth/me", headers=body_headers)
    account_id = me.json()["account"]["account_id"]
    await promote_role(uow_factory, account_id=account_id, role="CONTENT_EDITOR")
    login = await api_client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPassword123!"})
    return {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}


async def test_account_administration_requires_admin_role(api_client, uow_factory) -> None:
    learner_headers = await auth_headers(api_client, email=_email())
    response = await api_client.get("/api/v1/admin/accounts", headers=learner_headers)
    assert response.status_code == 403


async def test_admin_can_list_get_disable_enable_and_revoke_sessions(api_client, uow_factory) -> None:
    admin_headers = await _admin_headers(api_client, uow_factory)
    target_email = _email()
    target_headers = await auth_headers(api_client, email=target_email)
    target_me = await api_client.get("/api/v1/auth/me", headers=target_headers)
    target_account_id = target_me.json()["account"]["account_id"]

    r = await api_client.get("/api/v1/admin/accounts", headers=admin_headers, params={"limit": 5})
    assert r.status_code == 200
    assert "items" in r.json() and "pagination" in r.json()

    r = await api_client.get(f"/api/v1/admin/accounts/{target_account_id}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["email"] == target_email

    r = await api_client.post(f"/api/v1/admin/accounts/{target_account_id}/disable", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "DISABLED"

    r = await api_client.post(
        "/api/v1/auth/login", json={"email": target_email, "password": "StrongPassword123!"}
    )
    assert r.status_code == 401

    r = await api_client.post(f"/api/v1/admin/accounts/{target_account_id}/enable", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "ACTIVE"

    r = await api_client.post(
        f"/api/v1/admin/accounts/{target_account_id}/revoke-sessions", headers=admin_headers
    )
    assert r.status_code == 200
    assert r.json()["revoked_session_count"] >= 1


async def test_curriculum_authoring_requires_content_editor_or_admin(api_client, uow_factory) -> None:
    learner_headers = await auth_headers(api_client, email=_email())
    response = await api_client.put(
        "/api/v1/admin/curriculum/skills", headers=learner_headers,
        json={"code": "SHOULD_FAIL", "name": "x", "description": "d", "category": "MONEY_BASICS", "difficulty": "BEGINNER"},
    )
    assert response.status_code == 403


async def test_content_editor_can_author_full_curriculum_hierarchy(api_client, uow_factory) -> None:
    editor_headers = await _content_editor_headers(api_client, uow_factory)

    r = await api_client.put(
        "/api/v1/admin/curriculum/skills", headers=editor_headers,
        json={
            "code": f"ADMIN_TEST_{uuid.uuid4().hex[:8].upper()}", "name": "Skill", "description": "d",
            "category": "MONEY_BASICS", "difficulty": "BEGINNER",
        },
    )
    assert r.status_code == 200
    skill_id = r.json()["skill_id"]

    r = await api_client.put(
        "/api/v1/admin/curriculum/paths", headers=editor_headers,
        json={
            "code": f"admin-path-{uuid.uuid4().hex[:8]}", "title": "Path", "description": "d",
            "difficulty": "BEGINNER", "position": 0, "estimated_minutes": 10, "published": True,
        },
    )
    assert r.status_code == 200
    path_id = r.json()["path_id"]

    r = await api_client.put(
        f"/api/v1/admin/curriculum/paths/{path_id}/modules", headers=editor_headers,
        json={"code": "mod", "title": "Module", "description": "d", "position": 0, "estimated_minutes": 10, "published": True},
    )
    assert r.status_code == 200
    module_id = r.json()["module_id"]

    r = await api_client.put(
        f"/api/v1/admin/curriculum/modules/{module_id}/lessons", headers=editor_headers,
        json={
            "code": "lesson", "title": "Lesson", "summary": "s", "content_markdown": "# c",
            "difficulty": "BEGINNER", "status": "PUBLISHED", "position": 0, "estimated_minutes": 10,
            "primary_skill_id": skill_id,
        },
    )
    assert r.status_code == 200
    lesson_id = r.json()["lesson_id"]

    r = await api_client.put(
        f"/api/v1/admin/curriculum/lessons/{lesson_id}/exercises", headers=editor_headers,
        json={
            "exercise_type": "SINGLE_CHOICE", "prompt": "P?", "explanation": "E.", "difficulty": "BEGINNER",
            "position": 0, "skill_ids": [skill_id], "maximum_score": 1.0, "passing_score": 1.0,
            "options": [
                {"option_key": "a", "content": "Right", "position": 0, "is_correct": True, "feedback": "Yes"},
                {"option_key": "b", "content": "Wrong", "position": 1, "is_correct": False, "feedback": "No"},
            ],
        },
    )
    assert r.status_code == 200
    exercise = r.json()
    assert exercise["options"][0]["is_correct"] is True

    # The newly authored, published path/lesson is immediately visible on the learner-facing catalog.
    learner_headers = await auth_headers(api_client, email=_email())
    r = await api_client.get(f"/api/v1/lessons/{lesson_id}/exercises", headers=learner_headers)
    assert r.status_code == 200
    assert "is_correct" not in r.json()[0]


async def test_document_upload_is_bounded_to_supported_extensions(api_client, uow_factory) -> None:
    editor_headers = await _content_editor_headers(api_client, uow_factory)

    files = {"file": ("smoke.exe", b"not text", "application/octet-stream")}
    response = await api_client.post(
        "/api/v1/admin/knowledge/documents", headers=editor_headers, files=files,
        data={"source_title": "Bad Upload"},
    )
    assert response.status_code == 422


async def test_document_upload_and_listing(api_client, uow_factory) -> None:
    editor_headers = await _content_editor_headers(api_client, uow_factory)

    content = f"# Admin API Test Document {uuid.uuid4().hex}\n\nSome content for testing.".encode("utf-8")
    files = {"file": ("doc.md", content, "text/markdown")}
    data = {"source_title": f"Admin API Test {uuid.uuid4().hex[:6]}", "approval_status": "APPROVED"}
    response = await api_client.post(
        "/api/v1/admin/knowledge/documents", headers=editor_headers, files=files, data=data
    )
    assert response.status_code == 201
    assert response.json()["documents_created"] == 1

    r = await api_client.get("/api/v1/admin/knowledge/documents", headers=editor_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1

    r = await api_client.get("/api/v1/admin/knowledge/ingestion-runs", headers=editor_headers)
    assert r.status_code == 200
