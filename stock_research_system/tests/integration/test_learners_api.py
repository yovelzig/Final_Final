"""Integration tests for `/api/v1/learners/me*` against the real
PostgreSQL test database, driven over HTTP.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import auth_headers

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"learners-{uuid.uuid4().hex[:10]}@example.com"


async def test_get_my_profile(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    response = await api_client.get("/api/v1/learners/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["display_name"]


async def test_patch_my_profile_updates_allowed_fields(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    response = await api_client.patch(
        "/api/v1/learners/me", headers=headers, json={"display_name": "Updated Name", "daily_goal_minutes": 20}
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Updated Name"
    assert response.json()["daily_goal_minutes"] == 20


async def test_get_my_dashboard(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    response = await api_client.get("/api/v1/learners/me/dashboard", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert "learner" in body
    assert "skill_mastery" in body


async def test_get_my_mastery_is_empty_for_a_fresh_account(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    response = await api_client.get("/api/v1/learners/me/mastery", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["pagination"]["total"] == 0


async def test_get_my_progress_is_empty_for_a_fresh_account(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    response = await api_client.get("/api/v1/learners/me/progress", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["pagination"]["total"] == 0


async def test_get_my_misconceptions_is_empty_for_a_fresh_account(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    response = await api_client.get("/api/v1/learners/me/misconceptions", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["pagination"]["total"] == 0


async def test_learners_endpoints_require_authentication(api_client) -> None:
    for path in ("/api/v1/learners/me", "/api/v1/learners/me/dashboard", "/api/v1/learners/me/mastery"):
        response = await api_client.get(path)
        assert response.status_code == 401, path
