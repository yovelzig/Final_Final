"""Shared `PersonalizedLearningOrchestratorService`/LangGraph composition,
used identically by the API process (`api.app_factory.create_app`),
`finquest-worker-coach` (`infrastructure.operations.celery_tasks`), and
the graph-validation CLI (`cli.learning_orchestrator_admin`) - so the
Coach graph's node/subgraph/service wiring never drifts between the
three processes, exactly like `infrastructure.operations.registry_factory`
already does for the operations job registry.

Building this composition opens a PostgreSQL checkpointer connection
pool (when `settings.langgraph_enabled`) - the caller owns that pool's
lifecycle (`LearningOrchestratorRuntimeComposition.checkpointer_pool`
and `.intent_model_client`, both `None`-safe to close), exactly as
`api.app_factory`'s own `lifespan` already did before this extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from stock_research_core.application.adaptive_learning.policies import (
    DeterministicReviewSchedulingPolicy,
    RuleBasedAdaptivePolicy,
    RuleBasedDiagnosticPolicy,
    RuleBasedDifficultyPolicy,
)
from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.lesson_tutor import LessonTutorService
from stock_research_core.application.ai_tutor.portfolio_tutor import PortfolioTutorService
from stock_research_core.application.ai_tutor.ports import EmbeddingPort, KnowledgeSufficiencyGatePort, TutorModelPort
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.scenario_tutor import ScenarioTutorService
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.learning_orchestrator.actions import AllowlistedLearningActionExecutor
from stock_research_core.application.learning_orchestrator.graph_builder import build_graph
from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier
from stock_research_core.application.learning_orchestrator.nodes import (
    GraphNodes,
    LiveResearchTriggerDependencies,
    NodeDependencies,
)
from stock_research_core.application.learning_orchestrator.service import PersonalizedLearningOrchestratorService
from stock_research_core.application.learning_orchestrator.subgraphs import Subgraphs, SubgraphDependencies
from stock_research_core.application.live_research.ports import ResearchModelPort
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.application.operations.ports import DistributedLockPort, MetricsPort, TracingPort
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.virtual_portfolio.execution import (
    AverageCostPortfolioAccountingPolicy,
    NextAvailableOpenExecutionPolicy,
)
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.models import utc_now
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
from stock_research_core.infrastructure.operations.redis_lock import RedisDistributedLock
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import PandasPortfolioAnalytics


@dataclass
class LearningOrchestratorRuntimeComposition:
    #: `None` when `settings.langgraph_enabled` is `False` - callers
    #: check this instead of pre-checking the flag themselves.
    service: PersonalizedLearningOrchestratorService | None
    #: Caller-owned - close in a `finally` block; `None`-safe.
    checkpointer_pool: Any | None
    #: Caller-owned - `aclose()` in a `finally` block; `None`-safe.
    intent_model_client: HttpIntentClassificationModelClient | None


async def build_learning_orchestrator_runtime(
    *,
    settings: LangGraphSettings,
    database_url: str,
    unit_of_work_factory: Callable[[], UnitOfWorkPort],
    embedding_provider: EmbeddingPort,
    tutor_model: TutorModelPort,
    knowledge_sufficiency_gate: KnowledgeSufficiencyGatePort,
    lock_port: DistributedLockPort,
    metrics: MetricsPort,
    tracing: TracingPort,
    language_service: LanguageServicePort | None = None,
    language_service_enabled: bool = False,
    live_research: LiveResearchTriggerDependencies | None = None,
    research_model_router: ResearchModelPort | None = None,
) -> LearningOrchestratorRuntimeComposition:
    """Composes the full 26-node Coach graph (spec G2D2: the original 22
    plus the automatic Live Research trigger's 4) and its owning
    `PersonalizedLearningOrchestratorService` - identical logic and
    identical `build_graph()` call for every caller, never a second or
    reduced graph."""
    if not settings.langgraph_enabled:
        return LearningOrchestratorRuntimeComposition(service=None, checkpointer_pool=None, intent_model_client=None)

    configure_langsmith_tracing(
        enabled=settings.langsmith_tracing, api_key=settings.langsmith_api_key,
        project=settings.langsmith_project, trace_content=settings.langsmith_trace_content,
    )

    checkpointer_pool = build_checkpointer_pool(
        to_psycopg_conninfo(database_url), min_size=settings.langgraph_checkpointer_pool_min_size,
        max_size=settings.langgraph_checkpointer_pool_max_size,
    )
    await checkpointer_pool.open(
        wait=True,
        timeout=30,
    )
    checkpointer = build_checkpointer(checkpointer_pool)

    language_service = language_service or UnavailableLanguageService()
    retriever = HybridKnowledgeRetriever(unit_of_work_factory=unit_of_work_factory, embedding_provider=embedding_provider)
    tutor_service = GroundedAITutorService(
        unit_of_work_factory=unit_of_work_factory, retriever=retriever, tutor_model=tutor_model,
        guardrail=RuleBasedTutorGuardrail(), prompt_builder=GroundedTutorPromptBuilder(),
        sufficiency_gate=knowledge_sufficiency_gate, language_service=language_service,
        language_service_enabled=language_service_enabled,
    )
    lesson_tutor_service = LessonTutorService(tutor_service=tutor_service, unit_of_work_factory=unit_of_work_factory)
    scenario_service = HistoricalMarketScenarioService(
        unit_of_work_factory=unit_of_work_factory, scenario_calculator=PandasScenarioCalculator(),
        scenario_grading_policy=RuleBasedScenarioGradingPolicy(),
        graded_answer_submitter=LearningService(unit_of_work_factory),
    )
    scenario_tutor_service = ScenarioTutorService(
        tutor_service=tutor_service, unit_of_work_factory=unit_of_work_factory, scenario_service=scenario_service,
    )
    portfolio_service = VirtualPortfolioService(
        unit_of_work_factory=unit_of_work_factory, execution_policy=NextAvailableOpenExecutionPolicy(),
        accounting_policy=AverageCostPortfolioAccountingPolicy(),
    )
    valuation_service = PortfolioValuationService(
        unit_of_work_factory=unit_of_work_factory, analytics=PandasPortfolioAnalytics(),
        feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
    )
    portfolio_tutor_service = PortfolioTutorService(
        tutor_service=tutor_service, unit_of_work_factory=unit_of_work_factory,
        portfolio_service=portfolio_service, valuation_service=valuation_service,
    )
    adaptive_learning_service = AdaptiveLearningService(
        unit_of_work_factory, adaptive_policy=RuleBasedAdaptivePolicy(), difficulty_policy=RuleBasedDifficultyPolicy(),
        review_policy=DeterministicReviewSchedulingPolicy(), diagnostic_policy=RuleBasedDiagnosticPolicy(),
    )
    context_loader = SqlAlchemyLearningContextLoader(
        unit_of_work_factory=unit_of_work_factory,
        learning_service=LearningService(unit_of_work_factory), portfolio_service=portfolio_service,
    )
    action_executor = AllowlistedLearningActionExecutor(
        unit_of_work_factory=unit_of_work_factory, adaptive_learning_service=adaptive_learning_service,
        tutor_service=tutor_service, lesson_tutor_service=lesson_tutor_service,
        scenario_tutor_service=scenario_tutor_service, portfolio_tutor_service=portfolio_tutor_service,
    )

    rule_based_classifier = RuleBasedLearningIntentClassifier()
    intent_classifier = rule_based_classifier
    intent_model_client: HttpIntentClassificationModelClient | None = None
    if settings.langgraph_model_intent_classification:
        intent_model_client = HttpIntentClassificationModelClient(
            base_url=settings.langgraph_intent_model_base_url, api_key=settings.langgraph_intent_model_api_key,
            model_name=settings.langgraph_intent_model_name,
        )
        intent_classifier = ModelAssistedLearningIntentClassifier(
            rule_based=rule_based_classifier, model_client=intent_model_client, enabled=True,
        )

    node_deps = NodeDependencies(
        unit_of_work_factory=unit_of_work_factory, intent_classifier=intent_classifier,
        context_loader=context_loader, action_executor=action_executor, guardrail=RuleBasedTutorGuardrail(),
        clock=utc_now, max_context_characters=settings.langgraph_max_context_characters,
        max_state_list_items=settings.langgraph_max_state_list_items, live_research=live_research,
        research_model_router=research_model_router,
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
        graph=compiled_graph, max_steps=settings.langgraph_max_steps,
        run_timeout_seconds=settings.langgraph_run_timeout_seconds,
    )
    service = PersonalizedLearningOrchestratorService(
        unit_of_work_factory=unit_of_work_factory, graph_runtime=graph_runtime, lock_port=lock_port,
        metrics=metrics, tracing=tracing, graph_version=settings.langgraph_graph_version,
        max_steps=settings.langgraph_max_steps, thread_lock_ttl_seconds=settings.langgraph_thread_lock_ttl_seconds,
        thread_lock_wait_seconds=settings.langgraph_thread_lock_wait_seconds,
    )
    return LearningOrchestratorRuntimeComposition(
        service=service, checkpointer_pool=checkpointer_pool, intent_model_client=intent_model_client,
    )
