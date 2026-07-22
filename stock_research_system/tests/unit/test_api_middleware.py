"""Unit tests for `api/middleware.py`: correlation-ID handling and
security headers, exercised over a minimal Starlette app (no database,
no full `create_app()`).
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from stock_research_core.api.middleware import (
    CORRELATION_ID_HEADER,
    CorrelationIdMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/api/v1/whoami")
    async def whoami() -> dict:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    return app


async def _get(app: FastAPI, path: str, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers or {})


async def test_generates_a_correlation_id_when_absent() -> None:
    response = await _get(_build_app(), "/api/v1/whoami")
    assert CORRELATION_ID_HEADER in response.headers
    assert len(response.headers[CORRELATION_ID_HEADER]) > 0


async def test_echoes_a_valid_client_supplied_correlation_id() -> None:
    response = await _get(_build_app(), "/api/v1/whoami", headers={CORRELATION_ID_HEADER: "client-supplied-id-123"})
    assert response.headers[CORRELATION_ID_HEADER] == "client-supplied-id-123"


async def test_replaces_a_malformed_correlation_id() -> None:
    malformed = "has spaces/and;semicolons"
    response = await _get(_build_app(), "/api/v1/whoami", headers={CORRELATION_ID_HEADER: malformed})
    assert response.headers[CORRELATION_ID_HEADER] != malformed


async def test_replaces_an_overlong_correlation_id() -> None:
    overlong = "a" * 200
    response = await _get(_build_app(), "/api/v1/whoami", headers={CORRELATION_ID_HEADER: overlong})
    assert response.headers[CORRELATION_ID_HEADER] != overlong


async def test_security_headers_are_present() -> None:
    response = await _get(_build_app(), "/api/v1/whoami")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_api_paths_get_cache_control_no_store() -> None:
    response = await _get(_build_app(), "/api/v1/whoami")
    assert response.headers.get("Cache-Control") == "no-store"


async def test_health_path_does_not_get_cache_control_no_store() -> None:
    response = await _get(_build_app(), "/health")
    assert "Cache-Control" not in response.headers


async def test_middleware_never_logs_or_touches_the_authorization_header(caplog) -> None:  # type: ignore[no-untyped-def]
    secret_token = "Bearer super-secret-access-token-value"
    await _get(_build_app(), "/api/v1/whoami", headers={"Authorization": secret_token})
    assert secret_token not in caplog.text
    assert "super-secret-access-token-value" not in caplog.text
