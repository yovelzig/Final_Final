"""Integration tests for `/api/v1/auth/*` against the real PostgreSQL test
database, driven entirely over HTTP via `httpx.ASGITransport` (no direct
service or repository calls) - the full register/login/refresh/logout/
logout-all/me lifecycle, account lockout, and refresh-token
reuse-detection.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_account

pytestmark = pytest.mark.integration

_PASSWORD = "StrongPassword123!"


def _email() -> str:
    return f"auth-{uuid.uuid4().hex[:10]}@example.com"


async def test_register_creates_account_and_learner_and_returns_tokens(api_client) -> None:
    body = await register_account(api_client, email=_email())
    assert body["account"]["role"] == "LEARNER"
    assert body["account"]["status"] == "ACTIVE"
    assert body["account"]["learner_id"] == body["learner"]["learner_id"]
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]
    assert "password" not in str(body).lower().replace("password123", "")  # no password/hash leaked


async def test_register_rejects_duplicate_email(api_client) -> None:
    email = _email()
    await register_account(api_client, email=email)
    response = await api_client.post(
        "/api/v1/auth/register", json={"email": email, "password": _PASSWORD, "display_name": "Dup"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_ACCOUNT"


async def test_register_rejects_a_too_short_password_at_the_schema_layer(api_client) -> None:
    response = await api_client.post(
        "/api/v1/auth/register", json={"email": _email(), "password": "weak", "display_name": "Weak"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_register_rejects_a_long_but_policy_weak_password(api_client) -> None:
    """Long enough to clear the DTO's own `min_length`, but fails the
    application-layer character-class policy - this is the path that
    actually reaches `IdentityService`/`validate_password_policy`."""
    response = await api_client.post(
        "/api/v1/auth/register",
        json={"email": _email(), "password": "alllowercaseletters", "display_name": "Weak"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PASSWORD"


async def test_login_succeeds_with_correct_credentials(api_client) -> None:
    email = _email()
    await register_account(api_client, email=email)
    response = await api_client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert response.status_code == 200
    assert response.json()["tokens"]["access_token"]


async def test_login_never_reveals_whether_the_account_exists(api_client) -> None:
    email = _email()
    await register_account(api_client, email=email)

    wrong_password = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "WrongPassword123!"}
    )
    unknown_account = await api_client.post(
        "/api/v1/auth/login", json={"email": _email(), "password": _PASSWORD}
    )
    assert wrong_password.status_code == unknown_account.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_account.json()["error"]["message"]


async def test_account_locks_after_max_failed_logins(api_client) -> None:
    email = _email()
    await register_account(api_client, email=email)

    last_status = None
    for _ in range(6):
        response = await api_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "WrongPassword123!"}
        )
        last_status = response.status_code

    assert last_status == 401
    locked_response = await api_client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert locked_response.status_code == 401
    assert locked_response.json()["error"]["code"] == "ACCOUNT_LOCKED"


async def test_refresh_rotates_the_token(api_client) -> None:
    body = await register_account(api_client, email=_email())
    old_refresh_token = body["tokens"]["refresh_token"]

    response = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != old_refresh_token
    assert new_tokens["access_token"] != body["tokens"]["access_token"]


async def test_reusing_a_rotated_refresh_token_is_rejected_and_revokes_the_family(api_client) -> None:
    body = await register_account(api_client, email=_email())
    old_refresh_token = body["tokens"]["refresh_token"]

    rotated = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    new_refresh_token = rotated.json()["refresh_token"]

    reuse_response = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert reuse_response.status_code == 401
    assert reuse_response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"

    # The entire family, including the token issued by the rotation above, is now dead.
    after_reuse_response = await api_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_refresh_token}
    )
    assert after_reuse_response.status_code == 401


async def test_logout_revokes_the_refresh_token(api_client) -> None:
    body = await register_account(api_client, email=_email())
    refresh_token = body["tokens"]["refresh_token"]

    logout_response = await api_client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_response.status_code == 204

    refresh_response = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 401


async def test_logout_all_revokes_every_session(api_client) -> None:
    email = _email()
    first = await register_account(api_client, email=email)
    second_login = await api_client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    second_tokens = second_login.json()["tokens"]

    headers = {"Authorization": f"Bearer {first['tokens']['access_token']}"}
    logout_all_response = await api_client.post("/api/v1/auth/logout-all", headers=headers)
    assert logout_all_response.status_code == 200
    assert logout_all_response.json()["revoked_session_count"] == 2

    for token in (first["tokens"]["refresh_token"], second_tokens["refresh_token"]):
        response = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert response.status_code == 401


async def test_me_returns_the_authenticated_principal(api_client) -> None:
    email = _email()
    headers = await auth_headers(api_client, email=email)
    response = await api_client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["email"] == email
    assert body["learner"] is not None


async def test_me_requires_authentication(api_client) -> None:
    response = await api_client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_rejects_a_garbage_bearer_token(api_client) -> None:
    response = await api_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


async def test_auth_responses_carry_cache_control_no_store(api_client) -> None:
    response = await api_client.post("/api/v1/auth/register", json={
        "email": _email(), "password": _PASSWORD, "display_name": "Cache Test",
    })
    assert response.headers.get("Cache-Control") == "no-store"


async def test_auth_responses_carry_a_correlation_id(api_client) -> None:
    response = await api_client.post("/api/v1/auth/register", json={
        "email": _email(), "password": _PASSWORD, "display_name": "Correlation Test",
    })
    assert "X-Correlation-ID" in response.headers
