"""FastAPI application factory: the one place outside a router/CLI
allowed to construct concrete infrastructure adapters.

All expensive/stateful resources (the database engine, the embedding
provider, the tutor-model HTTP client) are created in `lifespan` -
never at import time, never per-request. Tests call `create_app(...)`
with explicit settings (typically pointed at the real test database)
and may additionally use `app.dependency_overrides` for finer-grained
substitution.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from stock_research_core.api.exception_handlers import register_exception_handlers
from stock_research_core.api.middleware import (
    CorrelationIdMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from stock_research_core.api.routers import (
    admin,
    adaptive_learning,
    ai_tutor,
    auth,
    curriculum,
    health,
    integrations,
    learners,
    learning_orchestrator,
    market_scenarios,
    operations,
    quality_evaluation,
    virtual_portfolios,
)
from stock_research_core.api.settings import ApiSettings, AuthSettings
from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.learning_orchestrator.nodes import LiveResearchTriggerDependencies
from stock_research_core.application.operations.service import BackgroundJobService
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
from stock_research_core.infrastructure.ai_tutor.model_factory import (
    build_knowledge_sufficiency_gate,
    build_tutor_model,
    close_tutor_model,
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
from stock_research_core.infrastructure.identity.argon2_password_hasher import Argon2PasswordHasher
from stock_research_core.infrastructure.identity.in_memory_rate_limiter import InMemoryRateLimiter
from stock_research_core.infrastructure.identity.jwt_access_token_service import JwtAccessTokenService
from stock_research_core.infrastructure.identity.opaque_refresh_token_service import (
    OpaqueRefreshTokenService,
)
from stock_research_core.infrastructure.language.composition import build_language_service, close_language_service
from stock_research_core.infrastructure.language.config import LanguageServiceSettings
from stock_research_core.infrastructure.learning_orchestrator.config import LangGraphSettings
from stock_research_core.infrastructure.learning_orchestrator.runtime_factory import (
    build_learning_orchestrator_runtime,
)
from stock_research_core.infrastructure.live_research.config import (
    LiveResearchAccountLimitSettings,
    PerplexitySearchSettings,
    ResearchModelSettings,
    SecEdgarSettings,
)
from stock_research_core.infrastructure.live_research.redis_account_rate_limiter import (
    RedisAccountResearchLimiter,
)
from stock_research_core.infrastructure.live_research.research_model_factory import (
    build_research_model,
    close_research_model,
)
from stock_research_core.infrastructure.live_research.sec_company_ticker_resolver import (
    SecCompanyTickerResolver,
)
from stock_research_core.infrastructure.operations.celery_app import celery_app as _celery_app
from stock_research_core.infrastructure.operations.celery_queue import CeleryJobQueue
from stock_research_core.infrastructure.operations.config import OperationsSettings, ProxySettings
from stock_research_core.infrastructure.operations.metrics import NoOpMetrics, PrometheusMetrics
from stock_research_core.infrastructure.operations.redis_lock import RedisDistributedLock, build_redis_client
from stock_research_core.infrastructure.operations.registry_factory import (
    build_operations_registry,
    build_quality_evaluation_service,
)
from stock_research_core.infrastructure.operations.structured_logging import configure_structlog
from stock_research_core.infrastructure.operations.tracing import build_tracing


def _build_embedding_provider(settings: EmbeddingSettings):
    if settings.embedding_provider == "deterministic_fake":
        return DeterministicFakeEmbeddingAdapter(dimension=settings.embedding_dimension)
    return SentenceTransformerEmbeddingAdapter(
        model_name=settings.embedding_model_name, dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
    )


#: `build_tutor_model`/`build_knowledge_sufficiency_gate`/`close_tutor_model`
#: now live in `infrastructure.ai_tutor.model_factory`, shared verbatim
#: with `infrastructure.operations.celery_tasks`'s coach-worker
#: composition (spec G2D2) - imported above, not redefined here.


def create_app(
    *,
    api_settings: ApiSettings | None = None,
    auth_settings: AuthSettings | None = None,
    database_settings: DatabaseSettings | None = None,
    embedding_settings: EmbeddingSettings | None = None,
    tutor_model_settings: TutorModelSettings | None = None,
    knowledge_sufficiency_settings: KnowledgeSufficiencySettings | None = None,
    language_service_settings: LanguageServiceSettings | None = None,
    operations_settings: OperationsSettings | None = None,
    proxy_settings: ProxySettings | None = None,
    learning_orchestrator_settings: LangGraphSettings | None = None,
    openai_reasoning_settings: OpenAIReasoningSettings | None = None,
    hebrew_query_bridge_settings: HebrewQueryBridgeSettings | None = None,
    live_research_account_limit_settings: LiveResearchAccountLimitSettings | None = None,
    live_research_perplexity_settings: PerplexitySearchSettings | None = None,
    live_research_sec_settings: SecEdgarSettings | None = None,
    testing: bool = False,
) -> FastAPI:
    api_settings = api_settings or ApiSettings()
    auth_settings = auth_settings or AuthSettings()
    database_settings = database_settings or DatabaseSettings()
    embedding_settings = embedding_settings or EmbeddingSettings()
    tutor_model_settings = tutor_model_settings or TutorModelSettings()
    knowledge_sufficiency_settings = knowledge_sufficiency_settings or KnowledgeSufficiencySettings()
    language_service_settings = language_service_settings or LanguageServiceSettings()
    operations_settings = operations_settings or OperationsSettings()
    learning_orchestrator_settings = learning_orchestrator_settings or LangGraphSettings()
    proxy_settings = proxy_settings or ProxySettings()
    openai_reasoning_settings = openai_reasoning_settings or OpenAIReasoningSettings()
    hebrew_query_bridge_settings = hebrew_query_bridge_settings or HebrewQueryBridgeSettings()
    live_research_account_limit_settings = live_research_account_limit_settings or LiveResearchAccountLimitSettings()
    live_research_perplexity_settings = live_research_perplexity_settings or PerplexitySearchSettings()
    live_research_sec_settings = live_research_sec_settings or SecEdgarSettings()

    auth_settings.require_strong_secret(testing=testing)
    if testing and not auth_settings.auth_jwt_secret:
        # `require_strong_secret(testing=True)` deliberately allows an empty
        # secret through, but PyJWT itself refuses to sign with one - tests
        # that don't care about the secret's value still need *a* value.
        auth_settings = auth_settings.model_copy(update={"auth_jwt_secret": "test-only-jwt-secret-not-for-production"})

    if not testing:
        assert_embedding_provider_production_safe(
            embedding_settings=embedding_settings, operations_settings=operations_settings
        )
        configure_structlog(environment=operations_settings.finquest_env.value, service_name=api_settings.api_title)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(database_settings)
        session_factory = create_session_factory(engine)

        app.state.api_settings = api_settings
        app.state.auth_settings = auth_settings
        app.state.operations_settings = operations_settings
        app.state.proxy_settings = proxy_settings
        app.state.engine = engine
        app.state.uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)
        app.state.password_hasher = Argon2PasswordHasher()
        app.state.access_token_service = JwtAccessTokenService(
            secret=auth_settings.auth_jwt_secret, issuer=auth_settings.auth_jwt_issuer,
            audience=auth_settings.auth_jwt_audience, algorithm=auth_settings.auth_jwt_algorithm,
            access_token_minutes=auth_settings.auth_access_token_minutes,
            allow_weak_secret_for_tests=testing,
        )
        app.state.refresh_token_service = OpaqueRefreshTokenService(
            refresh_token_days=auth_settings.auth_refresh_token_days
        )
        app.state.rate_limiter = InMemoryRateLimiter()
        app.state.embedding_settings = embedding_settings
        app.state.embedding_provider = _build_embedding_provider(embedding_settings)
        app.state.chunker = HeadingAwareWordChunker()
        app.state.tutor_model = build_tutor_model(
            tutor_model_settings, openai_reasoning_settings=openai_reasoning_settings
        )
        app.state.knowledge_sufficiency_settings = knowledge_sufficiency_settings
        app.state.knowledge_sufficiency_gate = _build_knowledge_sufficiency_gate(knowledge_sufficiency_settings)
        app.state.language_service_settings = language_service_settings
        app.state.language_service = build_language_service(
            language_service_settings, tutor_model_settings=tutor_model_settings
        )
        app.state.language_service_enabled = language_service_settings.hebrew_query_bridge_enabled

        # Phase 11: background jobs. `redis.asyncio.from_url()` and
        # `Celery.send_task`/`control.inspect` are lazy - constructing
        # these here never opens a connection at startup, matching the
        # spec's "no worker or Redis connection during import" rule (this
        # is `lifespan`, called at app *startup*, not at module import).
        redis_client = build_redis_client(operations_settings.redis_url)
        app.state.redis_client = redis_client
        app.state.celery_app_instance = _celery_app
        # Spec G2D2/H1 correction pass, section 8: constructed once and
        # shared by both `background_job_service` (whose
        # `_maybe_create_coach_resume_job` releases the per-account
        # concurrency slot once a Coach-triggered LIVE_RESEARCH_RUN_
        # EXECUTION job goes terminal) and `live_research_deps` (which
        # acquires that same slot) below - the two must never be
        # independently-configured instances. Reuses this function's own
        # `live_research_account_limit_settings` parameter/default
        # (resolved above), never a second, independently-constructed
        # `LiveResearchAccountLimitSettings()`.
        account_research_rate_limiter = RedisAccountResearchLimiter(
            redis_client=redis_client,
            concurrent_limit=live_research_account_limit_settings.live_research_per_account_concurrent_limit,
            hourly_limit=live_research_account_limit_settings.live_research_per_account_hourly_limit,
            concurrent_window_seconds=LiveResearchTriggerDependencies.research_deadline_seconds,
        )
        metrics = PrometheusMetrics() if operations_settings.metrics_enabled else NoOpMetrics()
        app.state.metrics = metrics
        tracing = build_tracing(
            enabled=operations_settings.otel_enabled, service_name=operations_settings.otel_service_name,
            otlp_endpoint=operations_settings.otel_exporter_otlp_endpoint, sample_ratio=operations_settings.otel_sample_ratio,
        )
        app.state.tracing = tracing
        registry = build_operations_registry(
            unit_of_work_factory=app.state.uow_factory, embedding_provider=app.state.embedding_provider,
            chunker=app.state.chunker,
            language_service=app.state.language_service, language_service_enabled=app.state.language_service_enabled,
        )
        app.state.background_job_service = BackgroundJobService(
            unit_of_work_factory=app.state.uow_factory, job_registry=registry,
            job_queue=CeleryJobQueue(_celery_app), lock_port=RedisDistributedLock(redis_client),
            metrics=metrics, tracing=tracing, account_research_rate_limiter=account_research_rate_limiter,
        )

        # -- Phase 13: quality-evaluation platform -----------------------------------------------
        quality_evaluation = build_quality_evaluation_service(
            unit_of_work_factory=app.state.uow_factory, embedding_provider=app.state.embedding_provider,
        )
        app.state.quality_evaluation_service = quality_evaluation.service
        app.state.quality_evaluation_default_configuration = quality_evaluation.default_configuration

        # -- Phase 12: LangGraph learning coach -----------------------------------------------
        # Entirely opt-in: `LANGGRAPH_ENABLED=false` (the default) means no
        # checkpointer pool is opened and no graph is compiled - every
        # existing Phase 1-11 capability is completely unaffected. Spec
        # G2D2: composition now lives in `build_learning_orchestrator_runtime`,
        # shared verbatim with `finquest-worker-coach` and the
        # graph-validation CLI, rather than duplicated in each process.
        app.state.learning_orchestrator_settings = learning_orchestrator_settings

        # Spec G2D2 section 5/11/18: `LiveResearchTriggerDependencies` is
        # always constructed (the account rate limiter and background job
        # service are cheap, connection-less objects), but `enabled` only
        # becomes `True` when the full flag chain is satisfied - every
        # graph node that reads `NodeDependencies.live_research` already
        # treats `enabled=False` exactly like the field being `None`, so
        # this is a safe, rollback-neutral default identical to every
        # other Phase 11 flag in this file.
        live_research_route_enabled = (
            learning_orchestrator_settings.langgraph_enabled
            and learning_orchestrator_settings.langgraph_live_research_route_enabled
            and operations_settings.live_research_jobs_enabled
            and (
                live_research_perplexity_settings.live_research_perplexity_enabled
                or live_research_sec_settings.live_research_sec_enabled
            )
        )
        # Spec G2D2/H1 correction pass, section 5: constructed only when
        # SEC EDGAR itself is enabled - never fabricates a CIK when SEC is
        # disabled, `request_live_research` instead returns a bounded
        # provider-unavailable response for FINANCIAL_FILING_REVIEW/
        # COMPANY_OVERVIEW in that case.
        cik_resolver = (
            SecCompanyTickerResolver(user_agent=live_research_sec_settings.live_research_sec_user_agent)
            if live_research_sec_settings.live_research_sec_enabled
            else None
        )
        live_research_deps = LiveResearchTriggerDependencies(
            background_job_service=app.state.background_job_service,
            account_rate_limiter=account_research_rate_limiter,
            enabled=live_research_route_enabled,
            max_question_characters=live_research_account_limit_settings.live_research_max_question_characters,
            cik_resolver=cik_resolver,
        )
        # Spec G2D2/H1 correction pass, section 6: `None` when Ollama is
        # unconfigured - `synthesize_research_response` then takes the
        # bounded provider-unavailable path, never a model call.
        research_model_router = build_research_model(ResearchModelSettings())
        runtime_composition = await build_learning_orchestrator_runtime(
            settings=learning_orchestrator_settings, database_url=database_settings.database_url,
            unit_of_work_factory=app.state.uow_factory, embedding_provider=app.state.embedding_provider,
            tutor_model=app.state.tutor_model, knowledge_sufficiency_gate=app.state.knowledge_sufficiency_gate,
            lock_port=RedisDistributedLock(redis_client), metrics=metrics, tracing=tracing,
            language_service=app.state.language_service, language_service_enabled=app.state.language_service_enabled,
            live_research=live_research_deps,
            research_model_router=research_model_router,
        )
        app.state.learning_orchestrator_service = runtime_composition.service
        app.state.learning_orchestrator_checkpointer_pool = runtime_composition.checkpointer_pool
        checkpointer_pool = runtime_composition.checkpointer_pool
        intent_model_client = runtime_composition.intent_model_client

        try:
            yield
        finally:
            await _close_tutor_model(app.state.tutor_model)
            await close_language_service(app.state.language_service)
            if intent_model_client is not None:
                await intent_model_client.aclose()
            if checkpointer_pool is not None:
                await checkpointer_pool.close()
            if cik_resolver is not None:
                await cik_resolver.aclose()
            await close_research_model(research_model_router)
            await redis_client.aclose()
            await engine.dispose()

    app = FastAPI(
        title=api_settings.api_title,
        version=api_settings.api_version,
        docs_url="/docs" if api_settings.api_docs_enabled else None,
        redoc_url="/redoc" if api_settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if api_settings.api_docs_enabled else None,
        lifespan=lifespan,
    )

    cors_origins = api_settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=bool(cors_origins) and "*" not in cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )
    # Added in this order so that, at request time, CorrelationId runs
    # outermost (first) - every other middleware and every exception
    # handler can then rely on `request.state.correlation_id` already
    # being set.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    prefix = api_settings.api_prefix
    app.include_router(auth.router, prefix=f"{prefix}/auth", tags=["Authentication"])
    app.include_router(learners.router, prefix=prefix, tags=["Learners"])
    app.include_router(curriculum.router, prefix=prefix, tags=["Curriculum"])
    app.include_router(adaptive_learning.router, prefix=f"{prefix}/adaptive", tags=["Adaptive Learning"])
    app.include_router(market_scenarios.router, prefix=f"{prefix}/scenarios", tags=["Historical Scenarios"])
    app.include_router(virtual_portfolios.router, prefix=f"{prefix}/portfolios", tags=["Virtual Portfolios"])
    app.include_router(ai_tutor.router, prefix=f"{prefix}/tutor", tags=["AI Tutor"])
    app.include_router(admin.router, prefix=f"{prefix}/admin", tags=["Administration"])
    app.include_router(operations.router, prefix=f"{prefix}/operations", tags=["Operations"])
    app.include_router(
        quality_evaluation.router, prefix=f"{prefix}/admin/evaluations", tags=["Quality Evaluation"]
    )
    app.include_router(integrations.router, prefix=f"{prefix}/integrations/n8n", tags=["n8n Integration"])
    if learning_orchestrator_settings.langgraph_enabled:
        app.include_router(learning_orchestrator.router, prefix=f"{prefix}/coach", tags=["Learning Coach"])

    _register_metrics_endpoint(app, api_settings=api_settings, operations_settings=operations_settings)

    return app


def _register_metrics_endpoint(app: FastAPI, *, api_settings: ApiSettings, operations_settings: OperationsSettings) -> None:
    """`GET /metrics`: unversioned (Prometheus scrape convention), never
    under `/api/v1`. Disabled entirely via `METRICS_ENABLED=false`;
    `METRICS_REQUIRE_AUTH=true` additionally requires ADMIN - documented
    as the alternative to internal-network-only exposure for a public
    deployment."""
    if not operations_settings.metrics_enabled:
        return

    from fastapi import Depends, Response

    from stock_research_core.api.dependencies import require_admin

    dependencies = [Depends(require_admin)] if operations_settings.metrics_require_auth else []

    @app.get("/metrics", include_in_schema=False, dependencies=dependencies)
    async def metrics_endpoint() -> Response:
        metrics = app.state.metrics
        if not isinstance(metrics, PrometheusMetrics):
            return Response(content=b"", media_type="text/plain")
        body, content_type = metrics.render_latest()
        return Response(content=body, media_type=content_type)
