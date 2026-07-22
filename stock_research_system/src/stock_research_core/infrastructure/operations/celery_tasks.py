"""Celery task definitions: the worker's composition root.

Each task's payload is exactly one `job_id` string (see `celery_queue.py`)
- every task here reloads the canonical job (parameters included) from
PostgreSQL via `BackgroundJobService.execute_job`, never trusts anything
else. Celery's own retry mechanism is never used: retry scheduling is
owned entirely by `BackgroundJobService`, which re-enqueues a fresh
message when (and only when) the job type's registered retry policy
allows it - see `application.operations.service`.

The worker-process composition root (`_build_worker_context`) is invoked
lazily, once per forked worker process, on `worker_process_init` - never
at module import time, so importing this module (e.g. from a test) never
opens a database connection, a Redis connection, or constructs an engine.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from celery.signals import worker_process_init

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.operations.job_registry import BackgroundJobRegistry
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.production_safety import (
    assert_embedding_provider_production_safe,
)
from stock_research_core.infrastructure.ai_tutor.sentence_transformer_embeddings import (
    SentenceTransformerEmbeddingAdapter,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.operations.celery_app import celery_app
from stock_research_core.infrastructure.operations.celery_queue import CeleryJobQueue
from stock_research_core.infrastructure.operations.config import OperationsSettings
from stock_research_core.infrastructure.operations.metrics import NoOpMetrics, PrometheusMetrics
from stock_research_core.infrastructure.operations.redis_lock import RedisDistributedLock, build_redis_client
from stock_research_core.infrastructure.operations.registry_factory import build_operations_registry
from stock_research_core.infrastructure.operations.structured_logging import (
    bind_job_log_context,
    clear_log_context,
    configure_structlog,
    get_logger,
)
from stock_research_core.infrastructure.operations.tracing import build_tracing

logger = logging.getLogger("stock_research_core.infrastructure.operations.celery_tasks")

_TIME_LIMITS: dict[BackgroundJobType, int] = {
    BackgroundJobType.TRACKED_MARKET_REFRESH: 1800,
    BackgroundJobType.SECURITY_MARKET_REFRESH: 300,
    BackgroundJobType.PORTFOLIO_VALUATION: 120,
    BackgroundJobType.PORTFOLIO_BATCH_VALUATION: 900,
    BackgroundJobType.CURRICULUM_KNOWLEDGE_REFRESH: 1800,
    BackgroundJobType.LOCAL_DOCUMENT_INGESTION: 300,
    BackgroundJobType.KNOWLEDGE_REEMBED: 900,
    BackgroundJobType.RETRIEVAL_EVALUATION: 600,
    BackgroundJobType.KNOWLEDGE_GAP_SUMMARY: 120,
    BackgroundJobType.SYSTEM_MAINTENANCE: 120,
    BackgroundJobType.RAGAS_QUALITY_EVALUATION: 1800,
    BackgroundJobType.LEARNING_QUALITY_AGGREGATION: 900,
    BackgroundJobType.QUALITY_BASELINE_COMPARISON: 300,
}


@dataclass
class WorkerContext:
    engine: Any
    redis_client: Any
    service: BackgroundJobService
    registry: BackgroundJobRegistry


_worker_context: WorkerContext | None = None


def _build_worker_context() -> WorkerContext:
    database_settings = DatabaseSettings()
    embedding_settings = EmbeddingSettings()
    operations_settings = OperationsSettings()

    assert_embedding_provider_production_safe(
        embedding_settings=embedding_settings, operations_settings=operations_settings
    )
    configure_structlog(environment=operations_settings.finquest_env.value, service_name="finquest-worker")

    engine = create_database_engine(database_settings)
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
    chunker = HeadingAwareWordChunker()
    registry = build_operations_registry(
        unit_of_work_factory=uow_factory, embedding_provider=embedding_provider, chunker=chunker
    )

    redis_client = build_redis_client(operations_settings.redis_url)
    lock_port = RedisDistributedLock(redis_client)
    job_queue = CeleryJobQueue(celery_app)
    metrics = PrometheusMetrics() if operations_settings.metrics_enabled else NoOpMetrics()
    tracing = build_tracing(
        enabled=operations_settings.otel_enabled, service_name="finquest-worker",
        otlp_endpoint=operations_settings.otel_exporter_otlp_endpoint, sample_ratio=operations_settings.otel_sample_ratio,
    )

    service = BackgroundJobService(
        unit_of_work_factory=uow_factory, job_registry=registry, job_queue=job_queue, lock_port=lock_port,
        metrics=metrics, tracing=tracing,
    )
    return WorkerContext(engine=engine, redis_client=redis_client, service=service, registry=registry)


def get_worker_context() -> WorkerContext:
    global _worker_context
    if _worker_context is None:
        _worker_context = _build_worker_context()
    return _worker_context


@worker_process_init.connect
def _init_worker_process(**_kwargs: Any) -> None:
    get_worker_context()


async def _execute_job(job_id: str, *, task_name: str, celery_task_id: str) -> dict[str, Any]:
    context = get_worker_context()
    worker_name = f"celery-worker:{task_name}"
    struct_logger = get_logger("stock_research_core.worker")
    try:
        result = await context.service.execute_job(
            job_id=job_id, worker_name=worker_name, celery_task_id=celery_task_id
        )
        bind_job_log_context(
            job_id=job_id, job_type=task_name, attempt_number=0, queue="", worker_name=worker_name,
        )
        struct_logger.info("job_execution_finished", status=result.status.value)
        return {"status": result.status.value, "warnings": result.warnings}
    except StockResearchError as exc:
        # Every controlled failure path already durably recorded FAILED/
        # RETRY_SCHEDULED in PostgreSQL inside `execute_job` itself - this
        # broad catch only stops one bad job from crashing the worker
        # process (spec ss1: "one job failure must not crash a worker").
        logger.warning("Job %s could not be executed: %s", job_id, exc)
        return {"status": "ERROR", "error": type(exc).__name__}
    finally:
        clear_log_context()


def _run_async(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def _make_task(job_type: BackgroundJobType):
    task_name = f"finquest.{job_type.value.lower()}"
    time_limit = _TIME_LIMITS[job_type]
    soft_time_limit = max(1, int(time_limit * 0.8))

    @celery_app.task(
        name=task_name, bind=True, acks_late=True, max_retries=0, time_limit=time_limit, soft_time_limit=soft_time_limit,
    )
    def _task(self: Any, job_id: str) -> dict[str, Any]:
        return _run_async(_execute_job(job_id, task_name=task_name, celery_task_id=self.request.id or ""))

    return _task


tracked_market_refresh_task = _make_task(BackgroundJobType.TRACKED_MARKET_REFRESH)
security_market_refresh_task = _make_task(BackgroundJobType.SECURITY_MARKET_REFRESH)
portfolio_valuation_task = _make_task(BackgroundJobType.PORTFOLIO_VALUATION)
portfolio_batch_valuation_task = _make_task(BackgroundJobType.PORTFOLIO_BATCH_VALUATION)
curriculum_knowledge_refresh_task = _make_task(BackgroundJobType.CURRICULUM_KNOWLEDGE_REFRESH)
local_document_ingestion_task = _make_task(BackgroundJobType.LOCAL_DOCUMENT_INGESTION)
knowledge_reembed_task = _make_task(BackgroundJobType.KNOWLEDGE_REEMBED)
retrieval_evaluation_task = _make_task(BackgroundJobType.RETRIEVAL_EVALUATION)
knowledge_gap_summary_task = _make_task(BackgroundJobType.KNOWLEDGE_GAP_SUMMARY)
system_maintenance_task = _make_task(BackgroundJobType.SYSTEM_MAINTENANCE)
ragas_quality_evaluation_task = _make_task(BackgroundJobType.RAGAS_QUALITY_EVALUATION)
learning_quality_aggregation_task = _make_task(BackgroundJobType.LEARNING_QUALITY_AGGREGATION)
quality_baseline_comparison_task = _make_task(BackgroundJobType.QUALITY_BASELINE_COMPARISON)
