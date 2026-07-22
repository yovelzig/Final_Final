"""Shared LangGraph-enabled `create_app()` fixtures for the Phase 12
checkpointer-dependent integration test modules
(`test_orchestrator_resume.py`, `test_orchestrator_concurrency.py`,
`test_orchestrator_api.py`, `test_orchestrator_end_to_end.py`). Not
collected by pytest (no `test_` prefix).

Every module that imports this one must set
`WindowsSelectorEventLoopPolicy` itself, at its own module level,
*before* this module (or anything importing psycopg) is imported - see
`test_langgraph_postgres_checkpointer.py`'s docstring for why.

Requires a reachable Redis (`REDIS_TEST_URL`, default
`redis://localhost:6379/0`) - on a Windows dev machine where
docker-compose's `redis` service deliberately has no host port mapping,
point `REDIS_TEST_URL` at a temporary forwarder (e.g. `docker run
--rm -d --network <compose-network> -p 16379:6379 alpine/socat
TCP-LISTEN:6379,fork,reuseaddr TCP:finquest-redis:6379`) or run these
specific modules inside the Docker network. A non-issue in CI/Docker,
where the compose network is reachable directly.
"""

from __future__ import annotations

import os

import pytest

from stock_research_core.infrastructure.learning_orchestrator.config import LangGraphSettings

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://localhost:6379/0")


@pytest.fixture(scope="module")
async def learning_coach_app(database_settings, api_settings):
    from stock_research_core.api.app_factory import create_app
    from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings, TutorModelSettings
    from stock_research_core.infrastructure.operations.config import OperationsSettings

    assert database_settings.test_database_url is not None
    api_database_settings = database_settings.model_copy(
        update={"database_url": database_settings.test_database_url}
    )
    app = create_app(
        testing=True,
        database_settings=api_database_settings,
        api_settings=api_settings,
        embedding_settings=EmbeddingSettings(embedding_provider="deterministic_fake"),
        tutor_model_settings=TutorModelSettings(tutor_model_provider="extractive"),
        operations_settings=OperationsSettings(
            readiness_require_redis=False, readiness_require_worker=False, redis_url=REDIS_TEST_URL,
        ),
        learning_orchestrator_settings=LangGraphSettings(langgraph_enabled=True),
    )
    async with app.router.lifespan_context(app):
        from stock_research_core.infrastructure.learning_orchestrator.postgres_checkpointer import (
            setup_checkpointer_tables,
            to_psycopg_conninfo,
        )

        await setup_checkpointer_tables(to_psycopg_conninfo(api_database_settings.database_url))
        yield app


@pytest.fixture
async def learning_coach_client(learning_coach_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=learning_coach_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
