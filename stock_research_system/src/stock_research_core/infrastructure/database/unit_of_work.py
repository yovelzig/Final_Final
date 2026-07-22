"""SQLAlchemy implementation of the application `UnitOfWorkPort`.

The `UnitOfWorkPort` Protocol itself lives in
`stock_research_core.application.persistence.ports` (no SQLAlchemy
import there); this module only provides the concrete implementation.
"""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from stock_research_core.infrastructure.database.repositories.adaptive_decision_repository import (
    SqlAlchemyAdaptiveDecisionRepository,
)
from stock_research_core.infrastructure.database.repositories.adaptive_profile_repository import (
    SqlAlchemyAdaptiveProfileRepository,
)
from stock_research_core.infrastructure.database.repositories.attempt_repository import (
    SqlAlchemyAttemptRepository,
)
from stock_research_core.infrastructure.database.repositories.background_job_attempt_repository import (
    SqlAlchemyBackgroundJobAttemptRepository,
)
from stock_research_core.infrastructure.database.repositories.background_job_event_repository import (
    SqlAlchemyBackgroundJobEventRepository,
)
from stock_research_core.infrastructure.database.repositories.background_job_repository import (
    SqlAlchemyBackgroundJobRepository,
)
from stock_research_core.infrastructure.database.repositories.curriculum_repository import (
    SqlAlchemyCurriculumRepository,
)
from stock_research_core.infrastructure.database.repositories.authentication_audit_repository import (
    SqlAlchemyAuthenticationAuditRepository,
)
from stock_research_core.infrastructure.database.repositories.conversation_repository import (
    SqlAlchemyConversationRepository,
)
from stock_research_core.infrastructure.database.repositories.diagnostic_repository import (
    SqlAlchemyDiagnosticRepository,
)
from stock_research_core.infrastructure.database.repositories.guardrail_repository import (
    SqlAlchemyGuardrailRepository,
)
from stock_research_core.infrastructure.database.repositories.ingestion_run_repository import (
    SqlAlchemyIngestionRunRepository,
)
from stock_research_core.infrastructure.database.repositories.integration_client_repository import (
    SqlAlchemyIntegrationClientRepository,
)
from stock_research_core.infrastructure.database.repositories.integration_request_repository import (
    SqlAlchemyIntegrationRequestRepository,
)
from stock_research_core.infrastructure.database.repositories.learning_orchestrator_action_repository import (
    SqlAlchemyLearningOrchestratorActionRepository,
)
from stock_research_core.infrastructure.database.repositories.learning_orchestrator_event_repository import (
    SqlAlchemyLearningOrchestratorEventRepository,
)
from stock_research_core.infrastructure.database.repositories.learning_orchestrator_run_repository import (
    SqlAlchemyLearningOrchestratorRunRepository,
)
from stock_research_core.infrastructure.database.repositories.learning_orchestrator_thread_repository import (
    SqlAlchemyLearningOrchestratorThreadRepository,
)
from stock_research_core.infrastructure.database.repositories.learning_quality_repository import (
    SqlAlchemyLearningQualityRepository,
)
from stock_research_core.infrastructure.database.repositories.quality_evaluation_baseline_repository import (
    SqlAlchemyQualityEvaluationBaselineRepository,
)
from stock_research_core.infrastructure.database.repositories.quality_evaluation_result_repository import (
    SqlAlchemyQualityEvaluationResultRepository,
)
from stock_research_core.infrastructure.database.repositories.quality_evaluation_run_repository import (
    SqlAlchemyQualityEvaluationRunRepository,
)
from stock_research_core.infrastructure.database.repositories.quality_evaluation_suite_repository import (
    SqlAlchemyQualityEvaluationSuiteRepository,
)
from stock_research_core.infrastructure.database.repositories.knowledge_gap_repository import (
    SqlAlchemyKnowledgeGapRepository,
)
from stock_research_core.infrastructure.database.repositories.knowledge_repository import (
    SqlAlchemyKnowledgeRepository,
)
from stock_research_core.infrastructure.database.repositories.learner_repository import (
    SqlAlchemyLearnerRepository,
)
from stock_research_core.infrastructure.database.repositories.learning_session_repository import (
    SqlAlchemyLearningSessionRepository,
)
from stock_research_core.infrastructure.database.repositories.market_bar_repository import (
    SqlAlchemyMarketBarRepository,
)
from stock_research_core.infrastructure.database.repositories.market_scenario_repository import (
    SqlAlchemyMarketScenarioRepository,
)
from stock_research_core.infrastructure.database.repositories.mastery_repository import (
    SqlAlchemyMasteryRepository,
)
from stock_research_core.infrastructure.database.repositories.misconception_repository import (
    SqlAlchemyMisconceptionRepository,
)
from stock_research_core.infrastructure.database.repositories.portfolio_holding_repository import (
    SqlAlchemyPortfolioHoldingRepository,
)
from stock_research_core.infrastructure.database.repositories.portfolio_journal_repository import (
    SqlAlchemyPortfolioJournalRepository,
)
from stock_research_core.infrastructure.database.repositories.portfolio_risk_repository import (
    SqlAlchemyPortfolioRiskRepository,
)
from stock_research_core.infrastructure.database.repositories.portfolio_transaction_repository import (
    SqlAlchemyPortfolioTransactionRepository,
)
from stock_research_core.infrastructure.database.repositories.portfolio_valuation_repository import (
    SqlAlchemyPortfolioValuationRepository,
)
from stock_research_core.infrastructure.database.repositories.portfolio_valuation_run_repository import (
    SqlAlchemyPortfolioValuationRunRepository,
)
from stock_research_core.infrastructure.database.repositories.progress_repository import (
    SqlAlchemyProgressRepository,
)
from stock_research_core.infrastructure.database.repositories.review_schedule_repository import (
    SqlAlchemyReviewScheduleRepository,
)
from stock_research_core.infrastructure.database.repositories.scenario_generation_run_repository import (
    SqlAlchemyScenarioGenerationRunRepository,
)
from stock_research_core.infrastructure.database.repositories.scenario_outcome_repository import (
    SqlAlchemyScenarioOutcomeRepository,
)
from stock_research_core.infrastructure.database.repositories.scenario_rubric_repository import (
    SqlAlchemyScenarioRubricRepository,
)
from stock_research_core.infrastructure.database.repositories.scenario_submission_repository import (
    SqlAlchemyScenarioSubmissionRepository,
)
from stock_research_core.infrastructure.database.repositories.refresh_token_repository import (
    SqlAlchemyRefreshTokenRepository,
)
from stock_research_core.infrastructure.database.repositories.retrieval_audit_repository import (
    SqlAlchemyRetrievalAuditRepository,
)
from stock_research_core.infrastructure.database.repositories.security_repository import (
    SqlAlchemySecurityRepository,
)
from stock_research_core.infrastructure.database.repositories.tracked_security_repository import (
    SqlAlchemyTrackedSecurityRepository,
)
from stock_research_core.infrastructure.database.repositories.tutor_answer_repository import (
    SqlAlchemyTutorAnswerRepository,
)
from stock_research_core.infrastructure.database.repositories.user_account_repository import (
    SqlAlchemyUserAccountRepository,
)
from stock_research_core.infrastructure.database.repositories.virtual_portfolio_repository import (
    SqlAlchemyVirtualPortfolioRepository,
)


class SqlAlchemyUnitOfWork:
    """Opens one async session/transaction per `async with` block.

    Repositories only exist after `__aenter__` runs, so using them
    before entering (or after exiting) the context manager fails
    naturally with an `AttributeError`. Commit and rollback are always
    explicit - nothing here commits implicitly, and exiting the block
    after an exception rolls back automatically.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        session = self._session_factory()
        self._session = session
        self.securities = SqlAlchemySecurityRepository(session)
        self.market_bars = SqlAlchemyMarketBarRepository(session)
        self.ingestion_runs = SqlAlchemyIngestionRunRepository(session)
        self.tracked_securities = SqlAlchemyTrackedSecurityRepository(session)
        self.learners = SqlAlchemyLearnerRepository(session)
        self.curriculum = SqlAlchemyCurriculumRepository(session)
        self.attempts = SqlAlchemyAttemptRepository(session)
        self.mastery = SqlAlchemyMasteryRepository(session)
        self.progress = SqlAlchemyProgressRepository(session)
        self.misconceptions = SqlAlchemyMisconceptionRepository(session)
        self.adaptive_profiles = SqlAlchemyAdaptiveProfileRepository(session)
        self.learning_sessions = SqlAlchemyLearningSessionRepository(session)
        self.diagnostics = SqlAlchemyDiagnosticRepository(session)
        self.review_schedules = SqlAlchemyReviewScheduleRepository(session)
        self.adaptive_decisions = SqlAlchemyAdaptiveDecisionRepository(session)
        self.market_scenarios = SqlAlchemyMarketScenarioRepository(session)
        self.scenario_rubrics = SqlAlchemyScenarioRubricRepository(session)
        self.scenario_outcomes = SqlAlchemyScenarioOutcomeRepository(session)
        self.scenario_submissions = SqlAlchemyScenarioSubmissionRepository(session)
        self.scenario_generation_runs = SqlAlchemyScenarioGenerationRunRepository(session)
        self.virtual_portfolios = SqlAlchemyVirtualPortfolioRepository(session)
        self.portfolio_transactions = SqlAlchemyPortfolioTransactionRepository(session)
        self.portfolio_holdings = SqlAlchemyPortfolioHoldingRepository(session)
        self.portfolio_journal = SqlAlchemyPortfolioJournalRepository(session)
        self.portfolio_valuations = SqlAlchemyPortfolioValuationRepository(session)
        self.portfolio_risk = SqlAlchemyPortfolioRiskRepository(session)
        self.portfolio_valuation_runs = SqlAlchemyPortfolioValuationRunRepository(session)
        self.knowledge = SqlAlchemyKnowledgeRepository(session)
        self.tutor_conversations = SqlAlchemyConversationRepository(session)
        self.tutor_answers = SqlAlchemyTutorAnswerRepository(session)
        self.tutor_guardrails = SqlAlchemyGuardrailRepository(session)
        self.tutor_retrieval = SqlAlchemyRetrievalAuditRepository(session)
        self.tutor_knowledge_gaps = SqlAlchemyKnowledgeGapRepository(session)
        self.user_accounts = SqlAlchemyUserAccountRepository(session)
        self.refresh_tokens = SqlAlchemyRefreshTokenRepository(session)
        self.authentication_audit = SqlAlchemyAuthenticationAuditRepository(session)
        self.background_jobs = SqlAlchemyBackgroundJobRepository(session)
        self.background_job_attempts = SqlAlchemyBackgroundJobAttemptRepository(session)
        self.background_job_events = SqlAlchemyBackgroundJobEventRepository(session)
        self.integration_clients = SqlAlchemyIntegrationClientRepository(session)
        self.integration_requests = SqlAlchemyIntegrationRequestRepository(session)
        self.learning_orchestrator_threads = SqlAlchemyLearningOrchestratorThreadRepository(session)
        self.learning_orchestrator_runs = SqlAlchemyLearningOrchestratorRunRepository(session)
        self.learning_orchestrator_events = SqlAlchemyLearningOrchestratorEventRepository(session)
        self.learning_orchestrator_actions = SqlAlchemyLearningOrchestratorActionRepository(session)
        self.quality_evaluation_suites = SqlAlchemyQualityEvaluationSuiteRepository(session)
        self.quality_evaluation_runs = SqlAlchemyQualityEvaluationRunRepository(session)
        self.quality_evaluation_results = SqlAlchemyQualityEvaluationResultRepository(session)
        self.quality_evaluation_baselines = SqlAlchemyQualityEvaluationBaselineRepository(session)
        self.learning_quality = SqlAlchemyLearningQualityRepository(session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None, "__aexit__ called without a matching __aenter__"
        try:
            if exc_type is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None, "commit() called outside an active Unit of Work"
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None, "rollback() called outside an active Unit of Work"
        await self._session.rollback()
