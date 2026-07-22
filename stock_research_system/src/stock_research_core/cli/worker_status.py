"""Worker health/readiness CLI - a lightweight, bounded check suitable for
a Docker `HEALTHCHECK` command. Checks PostgreSQL, Redis, the Celery
broker, the job registry (fails fast if misconfigured), the required
queues, and embedding-provider configuration for knowledge workers.
Never runs an expensive job, never downloads a model.

Usage (PowerShell):

    python -m stock_research_core.cli.worker_status

Exit code 0 = healthy, 1 = unhealthy (prints which check(s) failed).
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.production_safety import describe_embedding_provider_status
from stock_research_core.infrastructure.ai_tutor.sentence_transformer_embeddings import (
    SentenceTransformerEmbeddingAdapter,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import check_database_connection, create_database_engine
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.operations.celery_app import ALL_QUEUES, celery_app
from stock_research_core.infrastructure.operations.config import OperationsSettings
from stock_research_core.infrastructure.operations.redis_lock import build_redis_client
from stock_research_core.infrastructure.operations.registry_factory import build_operations_registry


async def _check_database(database_settings: DatabaseSettings) -> tuple[bool, str]:
    engine = create_database_engine(database_settings)
    try:
        connected = await check_database_connection(engine)
        return connected, "connected" if connected else "could not connect"
    finally:
        await engine.dispose()


def _check_celery_broker_blocking() -> tuple[bool, str]:
    try:
        with celery_app.connection_for_write() as connection:
            connection.ensure_connection(max_retries=1, timeout=2)
        return True, "broker connection established"
    except Exception as exc:  # noqa: BLE001
        return False, f"error: {exc}"


async def _check_celery_broker() -> tuple[bool, str]:
    return await asyncio.to_thread(_check_celery_broker_blocking)


async def _check_redis(operations_settings: OperationsSettings) -> tuple[bool, str]:
    client = build_redis_client(operations_settings.redis_url)
    try:
        ok = bool(await client.ping())
        return ok, "connected" if ok else "ping failed"
    except Exception as exc:  # noqa: BLE001
        return False, f"error: {exc}"
    finally:
        await client.aclose()


async def _check_registry(database_settings: DatabaseSettings, embedding_settings: EmbeddingSettings) -> tuple[bool, str]:
    from stock_research_core.domain.operations.enums import BackgroundJobType
    from stock_research_core.infrastructure.database.engine import create_session_factory

    engine = create_database_engine(database_settings)
    try:
        session_factory = create_session_factory(engine)
        uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731
        embedding_provider = (
            DeterministicFakeEmbeddingAdapter(dimension=embedding_settings.embedding_dimension)
            if embedding_settings.embedding_provider == "deterministic_fake"
            else SentenceTransformerEmbeddingAdapter(
                model_name=embedding_settings.embedding_model_name, dimension=embedding_settings.embedding_dimension,
                batch_size=embedding_settings.embedding_batch_size,
            )
        )
        registry = build_operations_registry(
            unit_of_work_factory=uow_factory, embedding_provider=embedding_provider, chunker=HeadingAwareWordChunker()
        )
        queues = sorted(registry.all_queue_names())
        return True, f"{len(list(BackgroundJobType))} job types registered across queues {queues}"
    except Exception as exc:  # noqa: BLE001
        return False, f"error: {exc}"
    finally:
        await engine.dispose()


async def main_async() -> int:
    database_settings = DatabaseSettings()
    operations_settings = OperationsSettings()
    embedding_settings = EmbeddingSettings()

    checks: list[tuple[str, bool, str]] = []

    db_ok, db_detail = await _check_database(database_settings)
    checks.append(("PostgreSQL", db_ok, db_detail))

    redis_ok, redis_detail = await _check_redis(operations_settings)
    checks.append(("Redis", redis_ok, redis_detail))

    broker_ok, broker_detail = await _check_celery_broker()
    checks.append(("Celery broker", broker_ok, broker_detail))

    registry_ok, registry_detail = await _check_registry(database_settings, embedding_settings)
    checks.append(("Job registry", registry_ok, registry_detail))

    queues_ok = True
    checks.append(("Required queues", queues_ok, ", ".join(ALL_QUEUES)))

    embedding_status = describe_embedding_provider_status(
        embedding_settings=embedding_settings, operations_settings=operations_settings
    )
    # `production_approved` describes the *provider choice* in the
    # abstract (deterministic_fake is never production-approved on its
    # own merits) - only actually fail this health check when the
    # process is really running in production; deterministic_fake in
    # test/development is expected and healthy.
    is_production = operations_settings.finquest_env.value == "production"
    embedding_ok = bool(embedding_status["initializable"]) and (
        not is_production or bool(embedding_status["production_approved"])
    )
    checks.append((
        "Embedding provider",
        embedding_ok,
        f"provider={embedding_status['provider']} environment={embedding_status['environment']} "
        f"production_approved={embedding_status['production_approved']} initializable={embedding_status['initializable']}",
    ))

    overall_ok = all(ok for _, ok, _ in checks)
    for name, ok, detail in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")

    return 0 if overall_ok else 1


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
