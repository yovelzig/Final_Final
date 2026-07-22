"""Application-level repository and Unit-of-Work contracts for persistence.

Pure `Protocol` definitions describing what the persistence layer does,
not how. No SQLAlchemy (or any other infrastructure library) is
imported here; concrete implementations live under
`stock_research_core.infrastructure.database`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.application.adaptive_learning.ports import (
    AdaptiveDecisionRepositoryPort,
    AdaptiveProfileRepositoryPort,
    DiagnosticRepositoryPort,
    LearningSessionRepositoryPort,
    ReviewScheduleRepositoryPort,
)
from stock_research_core.application.ai_tutor.ports import (
    ConversationRepositoryPort,
    GuardrailRepositoryPort,
    KnowledgeGapRepositoryPort,
    KnowledgeRepositoryPort,
    RetrievalAuditRepositoryPort,
    TutorAnswerRepositoryPort,
)
from stock_research_core.application.identity.ports import (
    AuthenticationAuditRepositoryPort,
    RefreshTokenRepositoryPort,
    UserAccountRepositoryPort,
)
from stock_research_core.application.learning.ports import (
    AttemptRepositoryPort,
    CurriculumRepositoryPort,
    LearnerRepositoryPort,
    MasteryRepositoryPort,
    MisconceptionRepositoryPort,
    ProgressRepositoryPort,
)
from stock_research_core.application.learning_orchestrator.ports import (
    LearningOrchestratorActionRepositoryPort,
    LearningOrchestratorEventRepositoryPort,
    LearningOrchestratorRunRepositoryPort,
    LearningOrchestratorThreadRepositoryPort,
)
from stock_research_core.application.market_data.models import DataQualityIssue
from stock_research_core.application.quality_evaluation.ports import (
    LearningQualityRepositoryPort,
    QualityEvaluationBaselineRepositoryPort,
    QualityEvaluationResultRepositoryPort,
    QualityEvaluationRunRepositoryPort,
    QualityEvaluationSuiteRepositoryPort,
)
from stock_research_core.application.operations.ports import (
    BackgroundJobAttemptRepositoryPort,
    BackgroundJobEventRepositoryPort,
    BackgroundJobRepositoryPort,
    IntegrationClientRepositoryPort,
    IntegrationRequestRepositoryPort,
)
from stock_research_core.application.market_scenarios.ports import (
    MarketScenarioRepositoryPort,
    ScenarioGenerationRunRepositoryPort,
    ScenarioOutcomeRepositoryPort,
    ScenarioRubricRepositoryPort,
    ScenarioSubmissionRepositoryPort,
)
from stock_research_core.application.persistence.models import IngestionRunRecord
from stock_research_core.application.virtual_portfolio.ports import (
    PortfolioHoldingRepositoryPort,
    PortfolioJournalRepositoryPort,
    PortfolioRiskRepositoryPort,
    PortfolioTransactionRepositoryPort,
    PortfolioValuationRepositoryPort,
    PortfolioValuationRunRepositoryPort,
    VirtualPortfolioRepositoryPort,
)
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security, TrackedSecurity


class SecurityRepositoryPort(Protocol):
    """Persists and retrieves `Security` objects."""

    async def upsert(self, security: Security) -> Security: ...

    async def get_by_id(self, security_id: UUID) -> Security | None: ...

    async def get_by_ticker(
        self, ticker: str, exchange: Exchange | None = None
    ) -> Security | None: ...


class MarketBarRepositoryPort(Protocol):
    """Persists and queries `MarketBar` objects."""

    async def upsert_many(self, bars: list[MarketBar]) -> int: ...

    async def list_range(
        self,
        security_id: UUID,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> list[MarketBar]: ...

    async def get_latest_timestamp(
        self,
        security_id: UUID,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> datetime | None: ...

    async def count(self, security_id: UUID, interval: str = "1d") -> int: ...

    async def get_next_bar_after(
        self,
        security_id: UUID,
        after_at: datetime,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> MarketBar | None:
        """The first stored bar strictly later than `after_at`.

        Added for the virtual-portfolio engine's point-in-time trade
        execution rule (Phase 7): a trade executes at the open of the
        first bar strictly after the request time, never at or before
        it. Not in the original Phase 3 spec, but a minimal, necessary
        addition mirroring the pattern already used for similar
        lookup-by-id additions in later phases.
        """
        ...

    async def get_latest_bar_at_or_before(
        self,
        security_id: UUID,
        as_of: datetime,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> MarketBar | None:
        """The most recent stored bar at or before `as_of`.

        Added for point-in-time portfolio valuation (Phase 7): a
        valuation as of a given moment must never use a price bar later
        than that moment.
        """
        ...


class IngestionRunRepositoryPort(Protocol):
    """Creates and updates ingestion-run audit records and their quality issues."""

    async def start(
        self,
        *,
        security_id: UUID,
        provider_name: str,
        interval: str,
        requested_start_at: datetime,
        requested_end_at: datetime,
        is_incremental: bool,
    ) -> IngestionRunRecord: ...

    async def mark_completed(
        self,
        run_id: UUID,
        *,
        provider_rows_received: int,
        valid_bars_returned: int,
        bars_persisted: int,
        duplicate_rows_removed: int,
        invalid_rows_removed: int,
    ) -> IngestionRunRecord: ...

    async def mark_no_new_data(
        self,
        run_id: UUID,
        *,
        provider_rows_received: int = 0,
        valid_bars_returned: int = 0,
        duplicate_rows_removed: int = 0,
        invalid_rows_removed: int = 0,
    ) -> IngestionRunRecord: ...

    async def mark_failed(
        self,
        run_id: UUID,
        *,
        error_type: str,
        error_message: str,
    ) -> IngestionRunRecord: ...

    async def save_quality_issues(
        self,
        run_id: UUID,
        issues: list[DataQualityIssue],
    ) -> int: ...

    async def get_by_id(self, run_id: UUID) -> IngestionRunRecord | None: ...

    async def list_recent(self, security_id: UUID, limit: int = 10) -> list[IngestionRunRecord]: ...


class TrackedSecurityRepositoryPort(Protocol):
    """Persists and queries `TrackedSecurity` objects."""

    async def upsert(self, tracked_security: TrackedSecurity) -> TrackedSecurity: ...

    async def get(self, security_id: UUID) -> TrackedSecurity | None: ...

    async def list_enabled(self) -> list[TrackedSecurity]: ...

    async def set_enabled(self, security_id: UUID, enabled: bool) -> TrackedSecurity: ...

    async def update_last_successful_update(
        self, security_id: UUID, timestamp: datetime
    ) -> TrackedSecurity: ...


class UnitOfWorkPort(Protocol):
    """Application-level Unit-of-Work contract.

    A concrete implementation opens a session/transaction on
    `__aenter__`, exposes repositories bound to that same session, and
    only commits or rolls back when explicitly told to. Repositories
    must not be used before entering the context manager.
    """

    securities: SecurityRepositoryPort
    market_bars: MarketBarRepositoryPort
    ingestion_runs: IngestionRunRepositoryPort
    tracked_securities: TrackedSecurityRepositoryPort
    learners: LearnerRepositoryPort
    curriculum: CurriculumRepositoryPort
    attempts: AttemptRepositoryPort
    mastery: MasteryRepositoryPort
    progress: ProgressRepositoryPort
    misconceptions: MisconceptionRepositoryPort
    adaptive_profiles: AdaptiveProfileRepositoryPort
    learning_sessions: LearningSessionRepositoryPort
    diagnostics: DiagnosticRepositoryPort
    review_schedules: ReviewScheduleRepositoryPort
    adaptive_decisions: AdaptiveDecisionRepositoryPort
    market_scenarios: MarketScenarioRepositoryPort
    scenario_rubrics: ScenarioRubricRepositoryPort
    scenario_outcomes: ScenarioOutcomeRepositoryPort
    scenario_submissions: ScenarioSubmissionRepositoryPort
    scenario_generation_runs: ScenarioGenerationRunRepositoryPort
    virtual_portfolios: VirtualPortfolioRepositoryPort
    portfolio_transactions: PortfolioTransactionRepositoryPort
    portfolio_holdings: PortfolioHoldingRepositoryPort
    portfolio_journal: PortfolioJournalRepositoryPort
    portfolio_valuations: PortfolioValuationRepositoryPort
    portfolio_risk: PortfolioRiskRepositoryPort
    portfolio_valuation_runs: PortfolioValuationRunRepositoryPort
    knowledge: KnowledgeRepositoryPort
    tutor_conversations: ConversationRepositoryPort
    tutor_answers: TutorAnswerRepositoryPort
    tutor_guardrails: GuardrailRepositoryPort
    tutor_retrieval: RetrievalAuditRepositoryPort
    tutor_knowledge_gaps: KnowledgeGapRepositoryPort
    user_accounts: UserAccountRepositoryPort
    refresh_tokens: RefreshTokenRepositoryPort
    authentication_audit: AuthenticationAuditRepositoryPort
    background_jobs: BackgroundJobRepositoryPort
    background_job_attempts: BackgroundJobAttemptRepositoryPort
    background_job_events: BackgroundJobEventRepositoryPort
    integration_clients: IntegrationClientRepositoryPort
    integration_requests: IntegrationRequestRepositoryPort
    learning_orchestrator_threads: LearningOrchestratorThreadRepositoryPort
    learning_orchestrator_runs: LearningOrchestratorRunRepositoryPort
    learning_orchestrator_events: LearningOrchestratorEventRepositoryPort
    learning_orchestrator_actions: LearningOrchestratorActionRepositoryPort
    quality_evaluation_suites: QualityEvaluationSuiteRepositoryPort
    quality_evaluation_runs: QualityEvaluationRunRepositoryPort
    quality_evaluation_results: QualityEvaluationResultRepositoryPort
    quality_evaluation_baselines: QualityEvaluationBaselineRepositoryPort
    learning_quality: LearningQualityRepositoryPort

    async def __aenter__(self) -> UnitOfWorkPort: ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
