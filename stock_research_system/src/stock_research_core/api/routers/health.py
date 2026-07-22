"""Unversioned health and readiness endpoints.

`GET /health` never touches the database - it is a pure liveness check.
`GET /ready` checks PostgreSQL connectivity, the current Alembic
revision, the `timescaledb`/`vector` extensions, Redis connectivity,
worker availability (best-effort, configurable), and embedding-provider
production safety; it never exposes the database URL, Redis URL, or any
secret, and never runs an expensive query or downloads a model.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.infrastructure.ai_tutor.production_safety import describe_embedding_provider_status

router = APIRouter(tags=["Health"])

_EXPECTED_EXTENSIONS = {"timescaledb", "vector"}


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    service: str
    version: str


class EmbeddingProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    environment: str
    production_approved: bool
    initializable: bool
    warnings: list[str]


class LearningCoachReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    graph_compiled: bool
    graph_version: str | None
    checkpointer_connected: bool | None
    intent_classifier_mode: str


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database_connected: bool
    alembic_revision: str | None
    extensions_installed: list[str]
    redis_connected: bool
    worker_available: bool | None
    embedding_provider: EmbeddingProviderStatus
    learning_coach: LearningCoachReadiness
    ready: bool


@router.get("/health", response_model=HealthResponse, summary="Liveness check (no database access)")
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok", service="finquest-api", version=request.app.state.api_settings.api_version
    )


async def _check_database(engine: AsyncEngine) -> tuple[bool, str | None, list[str]]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            revision_result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            revision = revision_result.scalar_one_or_none()
            extension_result = await connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname = ANY(:names)"),
                {"names": list(_EXPECTED_EXTENSIONS)},
            )
            extensions = sorted(row[0] for row in extension_result.all())
            return True, revision, extensions
    except Exception:  # noqa: BLE001 - readiness checks must never raise, only report unready
        return False, None, []


async def _check_redis(redis_client: Any) -> bool:
    if redis_client is None:
        return False
    try:
        return bool(await redis_client.ping())
    except Exception:  # noqa: BLE001
        return False


@router.get(
    "/ready", response_model=ReadinessCheck,
    summary="Readiness check (database, Alembic revision, extensions, Redis, worker, embedding safety)",
)
async def ready(request: Request, response: Response) -> ReadinessCheck:
    engine: AsyncEngine = request.app.state.engine
    database_connected, alembic_revision, extensions_installed = await _check_database(engine)

    redis_client = getattr(request.app.state, "redis_client", None)
    redis_connected = await _check_redis(redis_client)

    operations_settings = request.app.state.operations_settings
    embedding_settings = request.app.state.embedding_settings
    embedding_status = describe_embedding_provider_status(
        embedding_settings=embedding_settings, operations_settings=operations_settings
    )

    worker_available: bool | None = None
    if operations_settings.readiness_require_worker:
        worker_available = await _check_worker_available(request.app.state.celery_app_instance, redis_connected)

    learning_coach = await _check_learning_coach(request)

    # `production_approved` describes the provider *choice* in the
    # abstract (deterministic_fake is never production-approved on its
    # own merits) - only gate overall readiness on it when this process
    # is actually running in production; deterministic_fake in test/
    # development is expected and must not report unready.
    embedding_safe = (
        bool(embedding_status["production_approved"]) if operations_settings.finquest_env.value == "production" else True
    )
    ready_state = (
        database_connected
        and _EXPECTED_EXTENSIONS.issubset(set(extensions_installed))
        and (redis_connected or not operations_settings.readiness_require_redis)
        and embedding_safe
        and (worker_available is not False)
    )
    response.status_code = status.HTTP_200_OK if ready_state else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessCheck(
        database_connected=database_connected, alembic_revision=alembic_revision,
        extensions_installed=extensions_installed, redis_connected=redis_connected,
        worker_available=worker_available, embedding_provider=EmbeddingProviderStatus(**embedding_status),
        learning_coach=learning_coach, ready=ready_state,
    )


async def _check_learning_coach(request: Request) -> LearningCoachReadiness:
    """Never gates overall API readiness: a disabled or unreachable
    learning-coach subsystem must not take down `/ready` for the rest of
    FinQuest (spec section 29 - "keep the existing tutor API operational")."""
    settings = getattr(request.app.state, "learning_orchestrator_settings", None)
    if settings is None or not settings.langgraph_enabled:
        return LearningCoachReadiness(
            enabled=False, graph_compiled=False, graph_version=None, checkpointer_connected=None,
            intent_classifier_mode="DISABLED",
        )

    service = getattr(request.app.state, "learning_orchestrator_service", None)
    pool = getattr(request.app.state, "learning_orchestrator_checkpointer_pool", None)
    checkpointer_connected: bool | None = None
    if pool is not None:
        try:
            await pool.check()
            checkpointer_connected = True
        except Exception:  # noqa: BLE001
            checkpointer_connected = False

    return LearningCoachReadiness(
        enabled=True, graph_compiled=service is not None, graph_version=settings.langgraph_graph_version,
        checkpointer_connected=checkpointer_connected,
        intent_classifier_mode="MODEL_ASSISTED" if settings.langgraph_model_intent_classification else "RULE_BASED",
    )


def _ping_workers_blocking(celery_app_instance: Any) -> bool:
    inspector = celery_app_instance.control.inspect(timeout=1.0)
    pings = inspector.ping()
    return bool(pings)


async def _check_worker_available(celery_app_instance: Any, redis_connected: bool) -> bool:
    if celery_app_instance is None or not redis_connected:
        return False
    try:
        # `control.inspect().ping()` is a blocking Kombu round-trip - run
        # it off the event loop so a readiness probe never stalls other
        # concurrent requests.
        return await asyncio.to_thread(_ping_workers_blocking, celery_app_instance)
    except Exception:  # noqa: BLE001 - a Celery inspect failure means "not available", not a 500
        return False
