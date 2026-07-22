"""Integration tests for `/health` and `/ready` against the real
PostgreSQL/TimescaleDB test database.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_health_never_touches_the_database(api_client) -> None:
    response = await api_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "finquest-api"


async def test_health_requires_no_authentication(api_client) -> None:
    response = await api_client.get("/health")
    assert response.status_code == 200


async def test_ready_reports_database_connected_and_expected_extensions(api_client) -> None:
    response = await api_client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["database_connected"] is True
    assert body["ready"] is True
    assert set(body["extensions_installed"]) >= {"timescaledb", "vector"}
    assert body["alembic_revision"] == "0011_ragas_learning_quality"


async def test_ready_requires_no_authentication(api_client) -> None:
    response = await api_client.get("/ready")
    assert response.status_code in (200, 503)
