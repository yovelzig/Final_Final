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

from celery.signals import worker_process_init, worker_process_shutdown

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.language.ports import LanguageServicePort
from stock_research_core.application.operations.job_registry import BackgroundJobRegistry
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings, TutorModelSettings
from stock_research_core.application.learning_orchestrator.nodes import LiveResearchTriggerDependencies
from stock_research_core.application.operations.job_registry import BackgroundJobRegistry
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.infrastructure.ai_tutor.config import (
    EmbeddingSettings,
    HebrewQueryBridgeSettings,
    KnowledgeSufficiencySettings,
    OpenAIReasoningSettings,
    TutorModelSettings,
)
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.model_factory import build_knowledge_sufficiency_gate, build_tutor_model
from stock_research_core.infrastructure.ai_tutor.production_safety import (
    assert_embedding_provider_production_safe,
)
from stock_research_core.infrastructure.ai_tutor.sentence_transformer_embeddings import (
    SentenceTransformerEmbeddingAdapter,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.language.composition import build_language_service, close_language_service
from stock_research_core.infrastructure.language.config import LanguageServiceSettings
from stock_research_core.infrastructure.learning_orchestrator.config import LangGraphSettings
from stock_research_core.infrastructure.learning_orchestrator.runtime_factory import build_learning_orchestrator_runtime
from stock_research_core.infrastructure.live_research.config import (
    LiveResearchAccountLimitSettings,
    PerplexitySearchSettings,
    ResearchModelSettings,
    SecEdgarSettings,
)
from stock_research_core.infrastructure.live_research.redis_account_rate_limiter import RedisAccountResearchLimiter
from stock_research_core.infrastructure.live_research.research_model_factory import (
    build_research_model,
    close_research_model,
)
from stock_research_core.infrastructure.live_research.sec_company_ticker_resolver import (
    SecCompanyTickerResolver,
)
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
    BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION: 180,
    BackgroundJobType.COACH_RESEARCH_RESUME: 120,
}


@dataclass
class WorkerContext:
    engine: Any
    redis_client: Any
    service: BackgroundJobService
    registry: BackgroundJobRegistry
    #: Phase G2E2A: the same shared `LanguageServicePort` instance the API
    #: process composes (`api.app_factory`) - stored here so
    #: `_shutdown_worker_process` can close an owned HTTP client, and so
    #: a future handler that needs direct access (not just through the
    #: registry) has one. `build_operations_registry` receives this
    #: exact instance too, never a second one.
    language_service: LanguageServicePort
    #: Only set on `finquest-worker-coach` (spec G2D2 section 14) -
    #: `None`-safe to close on `worker_process_shutdown`.
    learning_orchestrator_checkpointer_pool: Any | None = None
    #: Only set on `finquest-worker-coach` when SEC EDGAR is enabled
    #: (spec G2D2/H1 correction pass, section 5) - `None`-safe to close
    #: on `worker_process_shutdown`.
    cik_resolver: Any | None = None
    #: Only set on `finquest-worker-coach` when Ollama is configured
    #: (spec G2D2/H1 correction pass, section 6) - `None`-safe to close
    #: on `worker_process_shutdown`.
    research_model_router: Any | None = None


_worker_context: WorkerContext | None = None


def _build_worker_context(
    *,
    database_settings: DatabaseSettings | None = None,
    embedding_settings: EmbeddingSettings | None = None,
    operations_settings: OperationsSettings | None = None,
    language_service_settings: LanguageServiceSettings | None = None,
    tutor_model_settings: TutorModelSettings | None = None,
) -> WorkerContext:
    """Build a hermetic-capable worker context for all job and Coach worker types."""
    database_settings = database_settings or DatabaseSettings()
    embedding_settings = embedding_settings or EmbeddingSettings()
    operations_settings = operations_settings or OperationsSettings()
    language_service_settings = language_service_settings or LanguageServiceSettings()
    tutor_model_settings = tutor_model_settings or TutorModelSettings()
    learning_orchestrator_settings = LangGraphSettings()

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
    # Network-free: constructing an `LlmBackedLanguageService` only opens
    # a lazy `httpx.AsyncClient` (no connection until first request),
    # identical in spirit to every other adapter built in this function.
    # Never logs `language_service_settings.language_service_api_key` (or
    # any resolved/reused credential) - only the resulting object is used.
    language_service = build_language_service(
        language_service_settings, tutor_model_settings=tutor_model_settings
    )
    registry = build_operations_registry(
        unit_of_work_factory=uow_factory, embedding_provider=embedding_provider, chunker=chunker,
        language_service=language_service,
        language_service_enabled=language_service_settings.hebrew_query_bridge_enabled,
    )

    redis_client = build_redis_client(operations_settings.redis_url)
    lock_port = RedisDistributedLock(redis_client)
    job_queue = CeleryJobQueue(celery_app)
    # Spec G2D2/H1 correction pass, section 8: constructed for every
    # worker (not only finquest-worker-coach) - this is what
    # `BackgroundJobService._maybe_create_coach_resume_job` releases the
    # per-account concurrency slot through once a Coach-triggered
    # LIVE_RESEARCH_RUN_EXECUTION job (executed on finquest-worker-research)
    # goes terminal. Cheap/connection-less to construct; a no-op for every
    # worker that never touches that job type.
    live_research_account_limit_settings = LiveResearchAccountLimitSettings()
    account_research_rate_limiter = RedisAccountResearchLimiter(
        redis_client=redis_client,
        concurrent_limit=live_research_account_limit_settings.live_research_per_account_concurrent_limit,
        hourly_limit=live_research_account_limit_settings.live_research_per_account_hourly_limit,
        concurrent_window_seconds=LiveResearchTriggerDependencies.research_deadline_seconds,
    )
    metrics = PrometheusMetrics() if operations_settings.metrics_enabled else NoOpMetrics()
    tracing = build_tracing(
        enabled=operations_settings.otel_enabled, service_name="finquest-worker",
        otlp_endpoint=operations_settings.otel_exporter_otlp_endpoint, sample_ratio=operations_settings.otel_sample_ratio,
    )

    # Spec G2D2 section 14: only `finquest-worker-coach` (the one
    # process with `LANGGRAPH_COACH_WORKER_ENABLED=true`) opens a
    # checkpointer pool and compiles the Coach graph - every other
    # worker sharing this same composition root gets
    # `learning_orchestrator_service=None`, exactly like the API
    # process does when `LANGGRAPH_ENABLED=false`.
    learning_orchestrator_service = None
    checkpointer_pool = None
    cik_resolver = None
    research_model_router = None
    if learning_orchestrator_settings.langgraph_coach_worker_enabled:
        tutor_model = build_tutor_model(TutorModelSettings(), openai_reasoning_settings=OpenAIReasoningSettings())
        knowledge_sufficiency_gate = build_knowledge_sufficiency_gate(KnowledgeSufficiencySettings())

        # Spec G2D2 section 5/11/18: a trigger-only `BackgroundJobService`
        # built from a registry that does *not* register the coach-resume
        # handler - only used for `create_job(LIVE_RESEARCH_RUN_EXECUTION)`
        # calls from inside the graph, never for `execute_job`. This
        # sidesteps the circular dependency where the *execution* registry
        # below needs `learning_orchestrator_service`, which itself needs
        # a `BackgroundJobService` to trigger Live Research jobs.
        live_research_perplexity_settings = PerplexitySearchSettings()
        live_research_sec_settings = SecEdgarSettings()
        live_research_route_enabled = (
            learning_orchestrator_settings.langgraph_enabled
            and learning_orchestrator_settings.langgraph_live_research_route_enabled
            and operations_settings.live_research_jobs_enabled
            and (
                live_research_perplexity_settings.live_research_perplexity_enabled
                or live_research_sec_settings.live_research_sec_enabled
            )
        )
        live_research_trigger_registry = build_operations_registry(
            unit_of_work_factory=uow_factory, embedding_provider=embedding_provider, chunker=chunker,
        )
        live_research_trigger_service = BackgroundJobService(
            unit_of_work_factory=uow_factory, job_registry=live_research_trigger_registry, job_queue=job_queue,
            lock_port=lock_port, metrics=metrics, tracing=tracing,
        )
        # Spec G2D2/H1 correction pass, section 5: constructed only when
        # SEC EDGAR itself is enabled - never fabricates a CIK when SEC is
        # disabled.
        cik_resolver = (
            SecCompanyTickerResolver(user_agent=live_research_sec_settings.live_research_sec_user_agent)
            if live_research_sec_settings.live_research_sec_enabled
            else None
        )
        live_research_deps = LiveResearchTriggerDependencies(
            background_job_service=live_research_trigger_service,
            account_rate_limiter=account_research_rate_limiter,
            enabled=live_research_route_enabled,
            max_question_characters=live_research_account_limit_settings.live_research_max_question_characters,
            cik_resolver=cik_resolver,
        )

        # Spec G2D2/H1 correction pass, section 6: `None` when Ollama is
        # unconfigured - `synthesize_research_response` then takes the
        # bounded provider-unavailable path, never a model call.
        research_model_router = build_research_model(ResearchModelSettings())
        composition = asyncio.run(
            build_learning_orchestrator_runtime(
                settings=learning_orchestrator_settings, database_url=database_settings.database_url,
                unit_of_work_factory=uow_factory, embedding_provider=embedding_provider, tutor_model=tutor_model,
                knowledge_sufficiency_gate=knowledge_sufficiency_gate, lock_port=lock_port, metrics=metrics,
                tracing=tracing, language_service=language_service,
                language_service_enabled=language_service_settings.hebrew_query_bridge_enabled,
                live_research=live_research_deps, research_model_router=research_model_router,
            )
        )
        learning_orchestrator_service = composition.service
        checkpointer_pool = composition.checkpointer_pool

    registry = build_operations_registry(
        unit_of_work_factory=uow_factory, embedding_provider=embedding_provider, chunker=chunker,
        learning_orchestrator_service=learning_orchestrator_service,
        language_service=language_service,
        language_service_enabled=language_service_settings.hebrew_query_bridge_enabled,
    )

    service = BackgroundJobService(
        unit_of_work_factory=uow_factory, job_registry=registry, job_queue=job_queue, lock_port=lock_port,
        metrics=metrics, tracing=tracing, account_research_rate_limiter=account_research_rate_limiter,
    )
    return WorkerContext(
        engine=engine, redis_client=redis_client, service=service, registry=registry,
        learning_orchestrator_checkpointer_pool=checkpointer_pool, cik_resolver=cik_resolver,
        research_model_router=research_model_router, language_service=language_service,
    )


def get_worker_context() -> WorkerContext:
    global _worker_context
    if _worker_context is None:
        _worker_context = _build_worker_context()
    return _worker_context


@worker_process_init.connect
def _init_worker_process(**_kwargs: Any) -> None:
    get_worker_context()


@worker_process_shutdown.connect
def _shutdown_worker_process(**_kwargs: Any) -> None:
    """Close every process-owned client exactly once."""
    global _worker_context
    if _worker_context is None:
        return
    asyncio.run(close_language_service(_worker_context.language_service))
    if _worker_context.learning_orchestrator_checkpointer_pool is not None:
        asyncio.run(_worker_context.learning_orchestrator_checkpointer_pool.close())
    if _worker_context.cik_resolver is not None:
        asyncio.run(_worker_context.cik_resolver.aclose())
    if _worker_context.research_model_router is not None:
        asyncio.run(close_research_model(_worker_context.research_model_router))
    _worker_context = None


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
live_research_run_execution_task = _make_task(BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION)
coach_research_resume_task = _make_task(BackgroundJobType.COACH_RESEARCH_RESUME)
