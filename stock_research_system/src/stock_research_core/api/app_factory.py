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
from stock_research_core.application.adaptive_learning.policies import (
    DeterministicReviewSchedulingPolicy,
    RuleBasedAdaptivePolicy,
    RuleBasedDiagnosticPolicy,
    RuleBasedDifficultyPolicy,
)
from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.lesson_tutor import LessonTutorService
from stock_research_core.application.ai_tutor.portfolio_tutor import PortfolioTutorService
from stock_research_core.application.ai_tutor.ports import TutorModelPort
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.scenario_tutor import ScenarioTutorService
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.learning_orchestrator.actions import AllowlistedLearningActionExecutor
from stock_research_core.application.learning_orchestrator.graph_builder import build_graph
from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier
from stock_research_core.application.learning_orchestrator.nodes import GraphNodes, NodeDependencies
from stock_research_core.application.learning_orchestrator.service import PersonalizedLearningOrchestratorService
from stock_research_core.application.learning_orchestrator.subgraphs import Subgraphs, SubgraphDependencies
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.models import utc_now
from stock_research_core.application.virtual_portfolio.execution import (
    AverageCostPortfolioAccountingPolicy,
    NextAvailableOpenExecutionPolicy,
)
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings, TutorModelSettings
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import DeterministicExtractiveTutor
from stock_research_core.infrastructure.ai_tutor.openai_compatible_tutor import OpenAICompatibleTutorAdapter
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
from stock_research_core.infrastructure.learning_orchestrator.config import LangGraphSettings
from stock_research_core.infrastructure.learning_orchestrator.context_loader import SqlAlchemyLearningContextLoader
from stock_research_core.infrastructure.learning_orchestrator.graph_runtime import LangGraphOrchestratorRuntime
from stock_research_core.infrastructure.learning_orchestrator.langsmith_tracing import configure_langsmith_tracing
from stock_research_core.infrastructure.learning_orchestrator.optional_model_intent_classifier import (
    HttpIntentClassificationModelClient,
    ModelAssistedLearningIntentClassifier,
)
from stock_research_core.infrastructure.learning_orchestrator.postgres_checkpointer import (
    build_checkpointer,
    build_checkpointer_pool,
    to_psycopg_conninfo,
)
from stock_research_core.infrastructure.market_scenarios.pandas_scenario_calculator import PandasScenarioCalculator
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
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import PandasPortfolioAnalytics


def _build_embedding_provider(settings: EmbeddingSettings):
    if settings.embedding_provider == "deterministic_fake":
        return DeterministicFakeEmbeddingAdapter(dimension=settings.embedding_dimension)
    return SentenceTransformerEmbeddingAdapter(
        model_name=settings.embedding_model_name, dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
    )


def _build_tutor_model(settings: TutorModelSettings) -> TutorModelPort:
    if settings.tutor_model_provider == "openai_compatible":
        return OpenAICompatibleTutorAdapter(
            base_url=settings.tutor_model_base_url, api_key=settings.tutor_model_api_key,
            model_name=settings.tutor_model_name, timeout_seconds=settings.tutor_model_timeout_seconds,
        )
    return DeterministicExtractiveTutor()


def create_app(
    *,
    api_settings: ApiSettings | None = None,
    auth_settings: AuthSettings | None = None,
    database_settings: DatabaseSettings | None = None,
    embedding_settings: EmbeddingSettings | None = None,
    tutor_model_settings: TutorModelSettings | None = None,
    operations_settings: OperationsSettings | None = None,
    proxy_settings: ProxySettings | None = None,
    learning_orchestrator_settings: LangGraphSettings | None = None,
    testing: bool = False,
) -> FastAPI:
    api_settings = api_settings or ApiSettings()
    auth_settings = auth_settings or AuthSettings()
    database_settings = database_settings or DatabaseSettings()
    embedding_settings = embedding_settings or EmbeddingSettings()
    tutor_model_settings = tutor_model_settings or TutorModelSettings()
    operations_settings = operations_settings or OperationsSettings()
    learning_orchestrator_settings = learning_orchestrator_settings or LangGraphSettings()
    proxy_settings = proxy_settings or ProxySettings()

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
        app.state.tutor_model = _build_tutor_model(tutor_model_settings)

        # Phase 11: background jobs. `redis.asyncio.from_url()` and
        # `Celery.send_task`/`control.inspect` are lazy - constructing
        # these here never opens a connection at startup, matching the
        # spec's "no worker or Redis connection during import" rule (this
        # is `lifespan`, called at app *startup*, not at module import).
        redis_client = build_redis_client(operations_settings.redis_url)
        app.state.redis_client = redis_client
        app.state.celery_app_instance = _celery_app
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
        )
        app.state.background_job_service = BackgroundJobService(
            unit_of_work_factory=app.state.uow_factory, job_registry=registry,
            job_queue=CeleryJobQueue(_celery_app), lock_port=RedisDistributedLock(redis_client),
            metrics=metrics, tracing=tracing,
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
        # existing Phase 1-11 capability is completely unaffected.
        app.state.learning_orchestrator_settings = learning_orchestrator_settings
        app.state.learning_orchestrator_service = None
        app.state.learning_orchestrator_checkpointer_pool = None
        checkpointer_pool = None
        intent_model_client: HttpIntentClassificationModelClient | None = None
        if learning_orchestrator_settings.langgraph_enabled:
            configure_langsmith_tracing(
                enabled=learning_orchestrator_settings.langsmith_tracing,
                api_key=learning_orchestrator_settings.langsmith_api_key,
                project=learning_orchestrator_settings.langsmith_project,
                trace_content=learning_orchestrator_settings.langsmith_trace_content,
            )

            checkpointer_pool = build_checkpointer_pool(
                to_psycopg_conninfo(database_settings.database_url),
                min_size=learning_orchestrator_settings.langgraph_checkpointer_pool_min_size,
                max_size=learning_orchestrator_settings.langgraph_checkpointer_pool_max_size,
            )
            await checkpointer_pool.open()
            app.state.learning_orchestrator_checkpointer_pool = checkpointer_pool
            checkpointer = build_checkpointer(checkpointer_pool)

            retriever = HybridKnowledgeRetriever(
                unit_of_work_factory=app.state.uow_factory, embedding_provider=app.state.embedding_provider
            )
            tutor_service = GroundedAITutorService(
                unit_of_work_factory=app.state.uow_factory,
                retriever=retriever,
                tutor_model=app.state.tutor_model, guardrail=RuleBasedTutorGuardrail(),
                prompt_builder=GroundedTutorPromptBuilder(),
            )
            lesson_tutor_service = LessonTutorService(
                tutor_service=tutor_service, unit_of_work_factory=app.state.uow_factory
            )
            scenario_service = HistoricalMarketScenarioService(
                unit_of_work_factory=app.state.uow_factory, scenario_calculator=PandasScenarioCalculator(),
                scenario_grading_policy=RuleBasedScenarioGradingPolicy(),
                graded_answer_submitter=LearningService(app.state.uow_factory),
            )
            scenario_tutor_service = ScenarioTutorService(
                tutor_service=tutor_service, unit_of_work_factory=app.state.uow_factory,
                scenario_service=scenario_service,
            )
            portfolio_service = VirtualPortfolioService(
                unit_of_work_factory=app.state.uow_factory, execution_policy=NextAvailableOpenExecutionPolicy(),
                accounting_policy=AverageCostPortfolioAccountingPolicy(),
            )
            valuation_service = PortfolioValuationService(
                unit_of_work_factory=app.state.uow_factory, analytics=PandasPortfolioAnalytics(),
                feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
            )
            portfolio_tutor_service = PortfolioTutorService(
                tutor_service=tutor_service, unit_of_work_factory=app.state.uow_factory,
                portfolio_service=portfolio_service, valuation_service=valuation_service,
            )
            adaptive_learning_service = AdaptiveLearningService(
                app.state.uow_factory, adaptive_policy=RuleBasedAdaptivePolicy(),
                difficulty_policy=RuleBasedDifficultyPolicy(), review_policy=DeterministicReviewSchedulingPolicy(),
                diagnostic_policy=RuleBasedDiagnosticPolicy(),
            )
            context_loader = SqlAlchemyLearningContextLoader(
                unit_of_work_factory=app.state.uow_factory,
                learning_service=LearningService(app.state.uow_factory), portfolio_service=portfolio_service,
            )
            action_executor = AllowlistedLearningActionExecutor(
                unit_of_work_factory=app.state.uow_factory, adaptive_learning_service=adaptive_learning_service,
                tutor_service=tutor_service, lesson_tutor_service=lesson_tutor_service,
                scenario_tutor_service=scenario_tutor_service, portfolio_tutor_service=portfolio_tutor_service,
            )

            rule_based_classifier = RuleBasedLearningIntentClassifier()
            intent_classifier = rule_based_classifier
            if learning_orchestrator_settings.langgraph_model_intent_classification:
                intent_model_client = HttpIntentClassificationModelClient(
                    base_url=learning_orchestrator_settings.langgraph_intent_model_base_url,
                    api_key=learning_orchestrator_settings.langgraph_intent_model_api_key,
                    model_name=learning_orchestrator_settings.langgraph_intent_model_name,
                )
                intent_classifier = ModelAssistedLearningIntentClassifier(
                    rule_based=rule_based_classifier, model_client=intent_model_client, enabled=True,
                )

            node_deps = NodeDependencies(
                unit_of_work_factory=app.state.uow_factory, intent_classifier=intent_classifier,
                context_loader=context_loader, action_executor=action_executor, guardrail=RuleBasedTutorGuardrail(),
                clock=utc_now,
                max_context_characters=learning_orchestrator_settings.langgraph_max_context_characters,
                max_state_list_items=learning_orchestrator_settings.langgraph_max_state_list_items,
            )
            graph_nodes = GraphNodes(node_deps)
            subgraphs = Subgraphs(
                SubgraphDependencies(
                    tutor_service=tutor_service, lesson_tutor_service=lesson_tutor_service,
                    scenario_tutor_service=scenario_tutor_service, portfolio_tutor_service=portfolio_tutor_service,
                    adaptive_learning_service=adaptive_learning_service, context_loader=context_loader,
                )
            )
            compiled_graph = build_graph(graph_nodes=graph_nodes, subgraphs=subgraphs, checkpointer=checkpointer)
            graph_runtime = LangGraphOrchestratorRuntime(
                graph=compiled_graph, max_steps=learning_orchestrator_settings.langgraph_max_steps,
                run_timeout_seconds=learning_orchestrator_settings.langgraph_run_timeout_seconds,
            )
            app.state.learning_orchestrator_service = PersonalizedLearningOrchestratorService(
                unit_of_work_factory=app.state.uow_factory, graph_runtime=graph_runtime,
                lock_port=RedisDistributedLock(redis_client), metrics=metrics, tracing=tracing,
                graph_version=learning_orchestrator_settings.langgraph_graph_version,
                max_steps=learning_orchestrator_settings.langgraph_max_steps,
                thread_lock_ttl_seconds=learning_orchestrator_settings.langgraph_thread_lock_ttl_seconds,
                thread_lock_wait_seconds=learning_orchestrator_settings.langgraph_thread_lock_wait_seconds,
            )

        try:
            yield
        finally:
            if isinstance(app.state.tutor_model, OpenAICompatibleTutorAdapter):
                await app.state.tutor_model.aclose()
            if intent_model_client is not None:
                await intent_model_client.aclose()
            if checkpointer_pool is not None:
                await checkpointer_pool.close()
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
