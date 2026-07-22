"""Integration tests proving a learning-coach run genuinely survives an
API-process restart while `WAITING_FOR_LEARNER` - the durable-
checkpoint guarantee spec section 17 requires. Simulated by tearing
down one `create_app()` (closing its checkpointer pool and engine
entirely) and resuming the SAME thread through a brand-new app instance
backed only by what PostgreSQL persisted.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from uuid import uuid4

import pytest

from tests.integration.conftest import auth_headers
from tests.integration.learning_orchestrator_app_fixtures import REDIS_TEST_URL

pytestmark = pytest.mark.integration


async def _build_app(database_settings, api_settings):
    from stock_research_core.api.app_factory import create_app
    from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings, TutorModelSettings
    from stock_research_core.infrastructure.learning_orchestrator.config import LangGraphSettings
    from stock_research_core.infrastructure.operations.config import OperationsSettings

    api_database_settings = database_settings.model_copy(update={"database_url": database_settings.test_database_url})
    return create_app(
        testing=True, database_settings=api_database_settings, api_settings=api_settings,
        embedding_settings=EmbeddingSettings(embedding_provider="deterministic_fake"),
        tutor_model_settings=TutorModelSettings(tutor_model_provider="extractive"),
        operations_settings=OperationsSettings(
            readiness_require_redis=False, readiness_require_worker=False, redis_url=REDIS_TEST_URL,
        ),
        learning_orchestrator_settings=LangGraphSettings(langgraph_enabled=True),
    )


async def test_a_waiting_run_resumes_correctly_after_a_full_process_restart(database_settings, api_settings) -> None:
    from httpx import ASGITransport, AsyncClient

    from stock_research_core.infrastructure.learning_orchestrator.postgres_checkpointer import (
        setup_checkpointer_tables,
        to_psycopg_conninfo,
    )

    api_database_settings = database_settings.model_copy(update={"database_url": database_settings.test_database_url})
    await setup_checkpointer_tables(to_psycopg_conninfo(api_database_settings.database_url))

    # -- "process 1": start a run, get it to WAITING_FOR_LEARNER, then tear everything down -----------------------------------------------
    app_1 = await _build_app(database_settings, api_settings)
    async with app_1.router.lifespan_context(app_1):
        async with AsyncClient(transport=ASGITransport(app=app_1), base_url="http://test") as client_1:
            headers = await auth_headers(client_1, email=f"resume-restart-{uuid4().hex[:10]}@example.com")
            thread = (await client_1.post("/api/v1/coach/threads", json={}, headers=headers)).json()
            run_response = await client_1.post(
                f"/api/v1/coach/threads/{thread['thread_id']}/runs",
                json={"user_input": "I'd like to start my daily practice session to build my financial skills."},
                headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
            )
            run = run_response.json()
            assert run["status"] == "WAITING_FOR_LEARNER"
    # `async with app_1.router.lifespan_context(app_1)` has now exited -
    # the checkpointer pool and database engine from "process 1" are
    # fully closed. Nothing from this point on can rely on in-memory
    # state from that instance.

    # -- "process 2": a brand-new app instance, resuming purely from PostgreSQL -----------------------------------------------
    app_2 = await _build_app(database_settings, api_settings)
    async with app_2.router.lifespan_context(app_2):
        async with AsyncClient(transport=ASGITransport(app=app_2), base_url="http://test") as client_2:
            resumed_run = await client_2.get(f"/api/v1/coach/runs/{run['run_id']}", headers=headers)
            assert resumed_run.status_code == 200
            assert resumed_run.json()["status"] == "WAITING_FOR_LEARNER"

            uow_factory = app_2.state.uow_factory
            from uuid import UUID

            async with uow_factory() as uow:
                proposals = await uow.learning_orchestrator_actions.list_for_run(UUID(run["run_id"]))
            proposal_id = str(proposals[0].proposal_id)

            resume_response = await client_2.post(
                f"/api/v1/coach/runs/{run['run_id']}/resume",
                json={"proposal_id": proposal_id, "decision": "APPROVE"}, headers=headers,
            )
            assert resume_response.status_code == 200, resume_response.text
            assert resume_response.json()["status"] == "SUCCEEDED"
