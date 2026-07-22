"""FastAPI dependency-injection wiring: Unit-of-Work access, application
service construction, authentication/authorization, and rate limiting.

Every service constructor here mirrors the exact composition already
used by the corresponding CLI (`cli/virtual_portfolio.py`,
`cli/market_scenarios.py`, `cli/adaptive_learning.py`, `cli/ai_tutor.py`)
- no business logic is reimplemented, only wired. Services are cheap,
stateless wrappers around `unit_of_work_factory` + injected policy
objects, so constructing a fresh one per request is intentional and
correct: it guarantees no state (and no `AsyncSession`) is ever shared
between concurrent requests.

Every composite service builder below depends on the leaf `app.state`
accessors *through `Depends()`*, not by reading `request.app.state`
directly - this is what makes `app.dependency_overrides[get_uow_factory]
= ...` (the standard FastAPI test pattern) actually propagate into
every derived service a test exercises, instead of only the outermost
one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from stock_research_core.api.settings import ApiSettings, AuthSettings
from stock_research_core.application.adaptive_learning.policies import (
    DeterministicReviewSchedulingPolicy,
    RuleBasedAdaptivePolicy,
    RuleBasedDiagnosticPolicy,
    RuleBasedDifficultyPolicy,
)
from stock_research_core.application.adaptive_learning.orchestrator import AdaptiveLearningOrchestrator
from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.lesson_tutor import LessonTutorService
from stock_research_core.application.ai_tutor.portfolio_tutor import PortfolioTutorService
from stock_research_core.application.ai_tutor.ports import EmbeddingPort, KnowledgeChunkerPort, TutorModelPort
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.scenario_tutor import ScenarioTutorService
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import (
    InsufficientPermissionError,
    RateLimitExceededError,
    StockResearchError,
)
from stock_research_core.application.identity.models import AuthenticatedPrincipal
from stock_research_core.application.identity.ports import (
    AccessTokenServicePort,
    PasswordHasherPort,
    RateLimiterPort,
    RefreshTokenServicePort,
)
from stock_research_core.application.identity.service import IdentityService
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.learning_orchestrator.service import PersonalizedLearningOrchestratorService
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.application.operations.ports import MetricsPort
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.application.quality_evaluation.models import EvaluationConfiguration
from stock_research_core.application.quality_evaluation.service import QualityEvaluationService
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.virtual_portfolio.execution import (
    AverageCostPortfolioAccountingPolicy,
    NextAvailableOpenExecutionPolicy,
)
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.identity.enums import AccountRole
from stock_research_core.infrastructure.identity.client_identity import resolve_client_ip
from stock_research_core.infrastructure.operations.config import ProxySettings
from stock_research_core.infrastructure.market_scenarios.pandas_scenario_calculator import (
    PandasScenarioCalculator,
)
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import (
    PandasPortfolioAnalytics,
)

_bearer_scheme = HTTPBearer(auto_error=False)

_ROLE_LEVEL: dict[AccountRole, int] = {
    AccountRole.LEARNER: 1,
    AccountRole.CONTENT_EDITOR: 2,
    AccountRole.ADMIN: 3,
}


# -- leaf accessors: read from app.state -----------------------------------------------
# (the only functions in this module allowed to touch `request.app.state`
# directly - everything else composes these via `Depends()`)


def get_uow_factory(request: Request) -> Callable[[], UnitOfWorkPort]:
    return request.app.state.uow_factory


def get_api_settings(request: Request) -> ApiSettings:
    return request.app.state.api_settings


def get_auth_settings(request: Request) -> AuthSettings:
    return request.app.state.auth_settings


def get_proxy_settings(request: Request) -> ProxySettings:
    return request.app.state.proxy_settings


def get_password_hasher(request: Request) -> PasswordHasherPort:
    return request.app.state.password_hasher


def get_access_token_service(request: Request) -> AccessTokenServicePort:
    return request.app.state.access_token_service


def get_refresh_token_service(request: Request) -> RefreshTokenServicePort:
    return request.app.state.refresh_token_service


def get_rate_limiter(request: Request) -> RateLimiterPort:
    return request.app.state.rate_limiter


def get_embedding_provider(request: Request) -> EmbeddingPort:
    return request.app.state.embedding_provider


def get_chunker(request: Request) -> KnowledgeChunkerPort:
    return request.app.state.chunker


def get_tutor_model(request: Request) -> TutorModelPort:
    return request.app.state.tutor_model


def get_correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


def get_background_job_service(request: Request) -> BackgroundJobService:
    return request.app.state.background_job_service


def get_quality_evaluation_service(request: Request) -> QualityEvaluationService:
    return request.app.state.quality_evaluation_service


def get_quality_evaluation_default_configuration(request: Request) -> EvaluationConfiguration:
    return request.app.state.quality_evaluation_default_configuration


def get_learning_orchestrator_service(request: Request) -> PersonalizedLearningOrchestratorService:
    """Only ever set on `app.state` when `LANGGRAPH_ENABLED=true` - the
    router that depends on this is itself only registered in that case
    (see `api.app_factory`), so a 404 (route not found) is what an
    unconfigured deployment returns, never an internal error here."""
    return request.app.state.learning_orchestrator_service


def get_metrics(request: Request) -> MetricsPort:
    return request.app.state.metrics


def _hash_optional(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resolve_client_ip(request: Request, proxy_settings: ProxySettings) -> str | None:
    resolved = resolve_client_ip(
        request, trust_forwarded_headers=proxy_settings.trust_forwarded_headers,
        trusted_proxy_cidrs=proxy_settings.trusted_proxy_cidr_list,
    )
    return None if resolved == "unknown" else resolved


def get_client_ip_hash(
    request: Request, proxy_settings: Annotated[ProxySettings, Depends(get_proxy_settings)]
) -> str | None:
    """The resolved client IP, hashed - safe for authentication audit
    storage (never the raw address; see `client_identity.resolve_client_ip`
    for the trusted-proxy resolution rules)."""
    return _hash_optional(_resolve_client_ip(request, proxy_settings))


def get_user_agent_hash(request: Request) -> str | None:
    return _hash_optional(request.headers.get("user-agent"))


# -- composite application service builders -----------------------------------------------


def get_identity_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    password_hasher: Annotated[PasswordHasherPort, Depends(get_password_hasher)],
    access_token_service: Annotated[AccessTokenServicePort, Depends(get_access_token_service)],
    refresh_token_service: Annotated[RefreshTokenServicePort, Depends(get_refresh_token_service)],
    auth_settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> IdentityService:
    return IdentityService(
        unit_of_work_factory=uow_factory,
        password_hasher=password_hasher,
        access_token_service=access_token_service,
        refresh_token_service=refresh_token_service,
        max_failed_logins=auth_settings.auth_max_failed_logins,
        lockout_minutes=auth_settings.auth_lockout_minutes,
    )


def get_learning_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
) -> LearningService:
    return LearningService(uow_factory)


def get_adaptive_learning_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
) -> AdaptiveLearningService:
    return AdaptiveLearningService(
        unit_of_work_factory=uow_factory,
        adaptive_policy=RuleBasedAdaptivePolicy(),
        difficulty_policy=RuleBasedDifficultyPolicy(),
        review_policy=DeterministicReviewSchedulingPolicy(),
        diagnostic_policy=RuleBasedDiagnosticPolicy(),
    )


def get_adaptive_learning_orchestrator(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    learning_service: Annotated[LearningService, Depends(get_learning_service)],
    adaptive_learning_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> AdaptiveLearningOrchestrator:
    return AdaptiveLearningOrchestrator(learning_service, adaptive_learning_service)


def get_scenario_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
) -> HistoricalMarketScenarioService:
    return HistoricalMarketScenarioService(
        unit_of_work_factory=uow_factory,
        scenario_calculator=PandasScenarioCalculator(),
        scenario_grading_policy=RuleBasedScenarioGradingPolicy(),
        graded_answer_submitter=LearningService(uow_factory),
    )


def get_portfolio_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
) -> VirtualPortfolioService:
    return VirtualPortfolioService(
        unit_of_work_factory=uow_factory,
        execution_policy=NextAvailableOpenExecutionPolicy(),
        accounting_policy=AverageCostPortfolioAccountingPolicy(),
    )


def get_portfolio_valuation_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
) -> PortfolioValuationService:
    return PortfolioValuationService(
        unit_of_work_factory=uow_factory, analytics=PandasPortfolioAnalytics(),
        feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
    )


def get_knowledge_retriever(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    embedding_provider: Annotated[EmbeddingPort, Depends(get_embedding_provider)],
) -> HybridKnowledgeRetriever:
    return HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)


def get_knowledge_ingestion_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    chunker: Annotated[KnowledgeChunkerPort, Depends(get_chunker)],
    embedding_provider: Annotated[EmbeddingPort, Depends(get_embedding_provider)],
) -> KnowledgeIngestionService:
    return KnowledgeIngestionService(
        unit_of_work_factory=uow_factory, chunker=chunker, embedding_provider=embedding_provider
    )


def get_ai_tutor_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    retriever: Annotated[HybridKnowledgeRetriever, Depends(get_knowledge_retriever)],
    tutor_model: Annotated[TutorModelPort, Depends(get_tutor_model)],
) -> GroundedAITutorService:
    return GroundedAITutorService(
        unit_of_work_factory=uow_factory, retriever=retriever, tutor_model=tutor_model,
        guardrail=RuleBasedTutorGuardrail(), prompt_builder=GroundedTutorPromptBuilder(),
    )


def get_lesson_tutor_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    tutor_service: Annotated[GroundedAITutorService, Depends(get_ai_tutor_service)],
) -> LessonTutorService:
    return LessonTutorService(tutor_service=tutor_service, unit_of_work_factory=uow_factory)


def get_scenario_tutor_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    tutor_service: Annotated[GroundedAITutorService, Depends(get_ai_tutor_service)],
    scenario_service: Annotated[HistoricalMarketScenarioService, Depends(get_scenario_service)],
) -> ScenarioTutorService:
    return ScenarioTutorService(
        tutor_service=tutor_service, unit_of_work_factory=uow_factory, scenario_service=scenario_service
    )


def get_portfolio_tutor_service(
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    tutor_service: Annotated[GroundedAITutorService, Depends(get_ai_tutor_service)],
    portfolio_service: Annotated[VirtualPortfolioService, Depends(get_portfolio_service)],
    valuation_service: Annotated[PortfolioValuationService, Depends(get_portfolio_valuation_service)],
) -> PortfolioTutorService:
    return PortfolioTutorService(
        tutor_service=tutor_service, unit_of_work_factory=uow_factory, portfolio_service=portfolio_service,
        valuation_service=valuation_service,
    )


# -- authentication / authorization -----------------------------------------------


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    access_token_service: Annotated[AccessTokenServicePort, Depends(get_access_token_service)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
) -> AuthenticatedPrincipal:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.")
    claims = access_token_service.decode_access_token(credentials.credentials)
    return await identity_service.get_principal(claims)


def require_roles(*roles: AccountRole) -> Callable[..., Annotated[AuthenticatedPrincipal, object]]:
    """Require the principal's role to be exactly one of `roles` (no hierarchy)."""
    allowed = frozenset(roles)

    async def _dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    ) -> AuthenticatedPrincipal:
        if principal.role not in allowed:
            raise InsufficientPermissionError("You do not have permission to perform this action.")
        return principal

    return _dependency


def _require_minimum_role(minimum: AccountRole) -> Callable[..., Annotated[AuthenticatedPrincipal, object]]:
    """Require the principal's role to be `minimum` or higher in the ADMIN > CONTENT_EDITOR > LEARNER hierarchy."""
    minimum_level = _ROLE_LEVEL[minimum]

    async def _dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    ) -> AuthenticatedPrincipal:
        if _ROLE_LEVEL[principal.role] < minimum_level:
            raise InsufficientPermissionError("You do not have permission to perform this action.")
        return principal

    return _dependency


require_learner = _require_minimum_role(AccountRole.LEARNER)
require_content_editor = _require_minimum_role(AccountRole.CONTENT_EDITOR)
require_admin = _require_minimum_role(AccountRole.ADMIN)


async def require_learner_identity(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
) -> UUID:
    """The caller's own learner ID - never a client-supplied value. Routes under
    `/learners/me/*` (and any endpoint scoped to "my own" data) depend on this,
    not on a path/body parameter, so a learner can never impersonate another."""
    if principal.learner_id is None:
        raise InsufficientPermissionError("This account is not linked to a learner profile.")
    return principal.learner_id


def ensure_owned_by_learner(
    resource_learner_id: UUID | None,
    principal: AuthenticatedPrincipal,
    *,
    not_found_error: type[StockResearchError],
    message: str,
) -> None:
    """Raise `not_found_error` (mapped to 404) if `resource_learner_id` isn't the
    caller's own - unless the caller is ADMIN. Never reveals whether a resource
    exists to a non-owner (403 would; 404 does not)."""
    if principal.role == AccountRole.ADMIN:
        return
    if resource_learner_id is None or resource_learner_id != principal.learner_id:
        raise not_found_error(message)


# -- rate limiting -----------------------------------------------


def rate_limit(*, action: str, limit: int, window_seconds: int) -> Callable[..., object]:
    """A FastAPI dependency enforcing `limit` requests per `window_seconds` per
    (action, client IP), via the process-local `RateLimiterPort` on `app.state`."""

    async def _dependency(
        request: Request,
        api_settings: Annotated[ApiSettings, Depends(get_api_settings)],
        proxy_settings: Annotated[ProxySettings, Depends(get_proxy_settings)],
        limiter: Annotated[RateLimiterPort, Depends(get_rate_limiter)],
    ) -> None:
        if not api_settings.api_rate_limit_enabled:
            return
        client_host = resolve_client_ip(
            request, trust_forwarded_headers=proxy_settings.trust_forwarded_headers,
            trusted_proxy_cidrs=proxy_settings.trusted_proxy_cidr_list,
        )
        key = f"{action}:{client_host}"
        allowed = await limiter.check(key=key, limit=limit, window_seconds=window_seconds)
        if not allowed:
            raise RateLimitExceededError("Too many requests. Please try again later.")

    return _dependency
