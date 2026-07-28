"""Shared `BackgroundJobRegistry` composition, used identically by the API
process (`api.app_factory.create_app`, for `create_job`/`cancel_job`/
`requeue_job`/listing) and by Celery workers (`celery_tasks.py`, which
additionally calls `execute_job`) - so job-type configuration (parameter
models, queues, retry policy, resource keys) never drifts between the
two processes.

Building this registry constructs real handler objects (holding real
adapters such as the market-data provider) but opens no network
connection itself - identical in spirit to how `api.app_factory` already
eagerly constructs `embedding_provider`/`tutor_model` in `lifespan`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stock_research_core.application.ai_tutor.guardrails import GUARDRAIL_POLICY_VERSION, RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.ports import EmbeddingPort, KnowledgeChunkerPort
from stock_research_core.application.ai_tutor.prompt_builder import PROMPT_VERSION, GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.retrieval import HYBRID_RETRIEVAL_VERSION, HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.service import TUTOR_POLICY_VERSION, GroundedAITutorService
from stock_research_core.application.ai_tutor.sufficiency import DisabledKnowledgeSufficiencyGate
from stock_research_core.application.language.ports import LanguageServicePort
from stock_research_core.application.language.unavailable_language_service import UnavailableLanguageService
from stock_research_core.application.live_research.provider_ports import (
    DiscoverySearchProviderPort,
    OfficialCompanyDataProviderPort,
)
from stock_research_core.application.live_research.service import ResearchRequestService
from stock_research_core.application.market_data.service import MarketDataIngestionService
from stock_research_core.application.operations.handlers import (
    CurriculumKnowledgeRefreshJobHandler,
    KnowledgeGapSummaryJobHandler,
    KnowledgeReembedJobHandler,
    LearningQualityAggregationJobHandler,
    LiveResearchRunExecutionJobHandler,
    LocalDocumentIngestionJobHandler,
    PortfolioBatchValuationJobHandler,
    PortfolioValuationJobHandler,
    QualityBaselineComparisonJobHandler,
    RagasQualityEvaluationJobHandler,
    RetrievalEvaluationJobHandler,
    SecurityMarketRefreshJobHandler,
    SystemMaintenanceJobHandler,
    TrackedMarketRefreshJobHandler,
)
from stock_research_core.application.operations.job_registry import BackgroundJobRegistry, build_default_registry
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.quality_evaluation.models import EvaluationConfiguration
from stock_research_core.application.quality_evaluation.service import QualityEvaluationService
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import DeterministicExtractiveTutor
from stock_research_core.infrastructure.live_research.config import PerplexitySearchSettings, SecEdgarSettings
from stock_research_core.infrastructure.live_research.perplexity_search_adapter import PerplexitySearchAdapter
from stock_research_core.infrastructure.live_research.sec_edgar_adapter import SecEdgarAdapter
from stock_research_core.infrastructure.market_data.yfinance_adapter import YFinanceMarketDataAdapter
from stock_research_core.infrastructure.operations.config import OperationsSettings
from stock_research_core.infrastructure.operations.metrics import NoOpMetrics
from stock_research_core.infrastructure.operations.tracing import NoOpTracing
from stock_research_core.infrastructure.quality_evaluation.config import QualityEvaluationSettings
from stock_research_core.infrastructure.quality_evaluation.evaluation_cache import InMemoryEvaluationCache
from stock_research_core.infrastructure.quality_evaluation.learning_quality_calculator import (
    NotYetImplementedLearningQualityCalculator,
)
from stock_research_core.infrastructure.quality_evaluation.tutor_case_executor import (
    EVALUATION_FIXTURE_LEARNER_ID,
    TutorGroundedCaseExecutor,
)
from stock_research_core.infrastructure.security.yfinance_resolver import YFinanceSecurityResolver
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import (
    PandasPortfolioAnalytics,
)


def _build_ragas_evaluator(*, embedding_provider: EmbeddingPort, settings: QualityEvaluationSettings):
    """Only imports `ragas` (an optional extra) when actually enabled -
    a deployment that never installed `.[quality_evaluation]` and never
    sets `RAGAS_ENABLED=true` must never even attempt this import."""
    if not settings.ragas_enabled:
        return None
    from stock_research_core.infrastructure.quality_evaluation.ragas_adapter import RagasEvaluationAdapter
    from stock_research_core.infrastructure.quality_evaluation.ragas_model_factory import (
        build_ragas_embeddings,
        build_ragas_llm,
    )

    llm = build_ragas_llm(settings)
    embeddings = build_ragas_embeddings(embedding_provider)
    return RagasEvaluationAdapter(llm=llm, embeddings=embeddings, settings=settings)


@dataclass
class QualityEvaluationComposition:
    service: QualityEvaluationService
    default_configuration: EvaluationConfiguration
    learning_quality_calculator: NotYetImplementedLearningQualityCalculator


def build_quality_evaluation_service(
    *, unit_of_work_factory: Callable[[], UnitOfWorkPort], embedding_provider: EmbeddingPort,
) -> QualityEvaluationComposition:
    """The one place `QualityEvaluationService` is composed - shared by
    `build_operations_registry` (for the job handlers) and
    `api.app_factory` (for the admin API's direct read/compare/approve
    endpoints), so the executor/RAGAS/lineage wiring never drifts
    between the two."""
    quality_evaluation_settings = QualityEvaluationSettings()
    retriever = HybridKnowledgeRetriever(unit_of_work_factory=unit_of_work_factory, embedding_provider=embedding_provider)
    guardrail = RuleBasedTutorGuardrail()
    tutor_service_for_evaluation = GroundedAITutorService(
        unit_of_work_factory=unit_of_work_factory, retriever=retriever, tutor_model=DeterministicExtractiveTutor(),
        guardrail=guardrail, prompt_builder=GroundedTutorPromptBuilder(),
        # Quality evaluation exercises the full generate/validate pipeline
        # independent of the (opt-in, learner-facing) Phase E1 gate.
        sufficiency_gate=DisabledKnowledgeSufficiencyGate(),
    )
    learning_quality_calculator = NotYetImplementedLearningQualityCalculator()
    service = QualityEvaluationService(
        unit_of_work_factory=unit_of_work_factory,
        case_executor=TutorGroundedCaseExecutor(
            tutor_service=tutor_service_for_evaluation, unit_of_work_factory=unit_of_work_factory,
            evaluation_learner_id=EVALUATION_FIXTURE_LEARNER_ID,
        ),
        ragas_evaluator=_build_ragas_evaluator(embedding_provider=embedding_provider, settings=quality_evaluation_settings),
        learning_quality_calculator=learning_quality_calculator,
        evaluation_cache=InMemoryEvaluationCache(),
        metrics=NoOpMetrics(), tracing=NoOpTracing(),
    )
    default_configuration = EvaluationConfiguration(
        system_version="finquest-phase-13", retrieval_policy_version=HYBRID_RETRIEVAL_VERSION,
        embedding_model="finquest-embedding-provider", embedding_version="v1",
        tutor_policy_version=TUTOR_POLICY_VERSION, prompt_version=PROMPT_VERSION,
        guardrail_version=GUARDRAIL_POLICY_VERSION,
    )
    return QualityEvaluationComposition(
        service=service, default_configuration=default_configuration, learning_quality_calculator=learning_quality_calculator,
    )


def _build_discovery_search_provider(settings: PerplexitySearchSettings) -> DiscoverySearchProviderPort | None:
    """Only constructs the adapter when Perplexity is itself enabled in
    its own G2A1 settings - never a network call either way (adapter
    construction only validates configuration). Reuses
    `PerplexitySearchSettings`/`PerplexitySearchAdapter` unchanged."""
    if not settings.live_research_perplexity_enabled:
        return None
    return PerplexitySearchAdapter(
        base_url=settings.live_research_perplexity_base_url,
        api_key=settings.live_research_perplexity_api_key.get_secret_value(),
        timeout_seconds=settings.live_research_perplexity_timeout_seconds,
        max_tokens=settings.live_research_perplexity_max_tokens,
        max_tokens_per_page=settings.live_research_perplexity_max_tokens_per_page,
    )


def _build_official_company_data_provider(settings: SecEdgarSettings) -> OfficialCompanyDataProviderPort | None:
    """Only constructs the adapter when SEC EDGAR is itself enabled in
    its own G2A1 settings. Reuses `SecEdgarSettings`/`SecEdgarAdapter`
    unchanged."""
    if not settings.live_research_sec_enabled:
        return None
    return SecEdgarAdapter(
        base_url=settings.live_research_sec_base_url,
        user_agent=settings.live_research_sec_user_agent,
        timeout_seconds=settings.live_research_sec_timeout_seconds,
        requests_per_second=settings.live_research_sec_requests_per_second,
    )


def build_operations_registry(
    *,
    unit_of_work_factory: Callable[[], UnitOfWorkPort],
    embedding_provider: EmbeddingPort,
    chunker: KnowledgeChunkerPort,
    language_service: LanguageServicePort | None = None,
    language_service_enabled: bool = False,
) -> BackgroundJobRegistry:
    # Phase G2E2A: defaults to the safe, pure, translation-incapable
    # adapter - callers that don't yet pass a real language service (or
    # pass `language_service_enabled=False`, the default) get exactly
    # today's behavior from `LiveResearchRunExecutionJobHandler`.
    language_service = language_service or UnavailableLanguageService()
    knowledge_ingestion_service = KnowledgeIngestionService(
        unit_of_work_factory=unit_of_work_factory, chunker=chunker, embedding_provider=embedding_provider
    )
    market_data_service = MarketDataIngestionService(
        security_resolver=YFinanceSecurityResolver(), market_data_provider=YFinanceMarketDataAdapter()
    )
    portfolio_valuation_service = PortfolioValuationService(
        unit_of_work_factory=unit_of_work_factory, analytics=PandasPortfolioAnalytics(),
        feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
    )
    retriever = HybridKnowledgeRetriever(unit_of_work_factory=unit_of_work_factory, embedding_provider=embedding_provider)
    guardrail = RuleBasedTutorGuardrail()

    quality_evaluation = build_quality_evaluation_service(
        unit_of_work_factory=unit_of_work_factory, embedding_provider=embedding_provider,
    )
    quality_evaluation_service = quality_evaluation.service
    default_evaluation_configuration = quality_evaluation.default_configuration
    learning_quality_calculator = quality_evaluation.learning_quality_calculator

    # Phase G2B: disabled-by-default orchestration switch, independent of
    # each G2A1 provider's own enabled flag. Constructing settings/adapters
    # here never makes a network call - only when `live_research_jobs_enabled`
    # is True are the (still individually gated) adapters even constructed.
    operations_settings = OperationsSettings()
    research_request_service = ResearchRequestService(unit_of_work_factory=unit_of_work_factory)
    discovery_search_provider: DiscoverySearchProviderPort | None = None
    official_company_data_provider: OfficialCompanyDataProviderPort | None = None
    # Default matches `PerplexitySearchSettings.live_research_perplexity_max_results`'s
    # own field default - only overridden below when jobs are enabled, so
    # the handler's `discovery_max_results` always reflects the real
    # configured value rather than `DiscoverySearchRequest`'s own silent
    # default (G2B Correction V2, item 5).
    discovery_max_results = PerplexitySearchSettings.model_fields["live_research_perplexity_max_results"].default
    if operations_settings.live_research_jobs_enabled:
        perplexity_settings = PerplexitySearchSettings()
        discovery_search_provider = _build_discovery_search_provider(perplexity_settings)
        discovery_max_results = perplexity_settings.live_research_perplexity_max_results
        official_company_data_provider = _build_official_company_data_provider(SecEdgarSettings())

    handlers = {
        BackgroundJobType.TRACKED_MARKET_REFRESH: TrackedMarketRefreshJobHandler(
            unit_of_work_factory=unit_of_work_factory, market_data_service=market_data_service
        ),
        BackgroundJobType.SECURITY_MARKET_REFRESH: SecurityMarketRefreshJobHandler(
            unit_of_work_factory=unit_of_work_factory, security_resolver=YFinanceSecurityResolver(),
            market_data_service=market_data_service,
        ),
        BackgroundJobType.PORTFOLIO_VALUATION: PortfolioValuationJobHandler(
            portfolio_valuation_service=portfolio_valuation_service
        ),
        BackgroundJobType.PORTFOLIO_BATCH_VALUATION: PortfolioBatchValuationJobHandler(
            unit_of_work_factory=unit_of_work_factory, portfolio_valuation_service=portfolio_valuation_service
        ),
        BackgroundJobType.CURRICULUM_KNOWLEDGE_REFRESH: CurriculumKnowledgeRefreshJobHandler(
            knowledge_ingestion_service=knowledge_ingestion_service
        ),
        BackgroundJobType.LOCAL_DOCUMENT_INGESTION: LocalDocumentIngestionJobHandler(
            knowledge_ingestion_service=knowledge_ingestion_service
        ),
        BackgroundJobType.KNOWLEDGE_REEMBED: KnowledgeReembedJobHandler(
            unit_of_work_factory=unit_of_work_factory, knowledge_ingestion_service=knowledge_ingestion_service
        ),
        BackgroundJobType.RETRIEVAL_EVALUATION: RetrievalEvaluationJobHandler(retriever=retriever, guardrail=guardrail),
        BackgroundJobType.KNOWLEDGE_GAP_SUMMARY: KnowledgeGapSummaryJobHandler(unit_of_work_factory=unit_of_work_factory),
        BackgroundJobType.SYSTEM_MAINTENANCE: SystemMaintenanceJobHandler(unit_of_work_factory=unit_of_work_factory),
        BackgroundJobType.RAGAS_QUALITY_EVALUATION: RagasQualityEvaluationJobHandler(
            quality_evaluation_service=quality_evaluation_service, default_configuration=default_evaluation_configuration,
        ),
        BackgroundJobType.QUALITY_BASELINE_COMPARISON: QualityBaselineComparisonJobHandler(
            quality_evaluation_service=quality_evaluation_service
        ),
        BackgroundJobType.LEARNING_QUALITY_AGGREGATION: LearningQualityAggregationJobHandler(
            calculator=learning_quality_calculator, unit_of_work_factory=unit_of_work_factory,
        ),
        BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION: LiveResearchRunExecutionJobHandler(
            research_request_service=research_request_service,
            discovery_search_provider=discovery_search_provider,
            official_company_data_provider=official_company_data_provider,
            jobs_enabled=operations_settings.live_research_jobs_enabled,
            discovery_max_results=discovery_max_results,
            language_service=language_service,
            language_service_enabled=language_service_enabled,
        ),
    }
    return build_default_registry(handlers)
