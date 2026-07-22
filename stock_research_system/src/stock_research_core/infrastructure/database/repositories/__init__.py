"""Concrete SQLAlchemy repository implementations of the persistence ports."""

from stock_research_core.infrastructure.database.repositories.adaptive_decision_repository import (
    SqlAlchemyAdaptiveDecisionRepository,
)
from stock_research_core.infrastructure.database.repositories.adaptive_profile_repository import (
    SqlAlchemyAdaptiveProfileRepository,
)
from stock_research_core.infrastructure.database.repositories.attempt_repository import (
    SqlAlchemyAttemptRepository,
)
from stock_research_core.infrastructure.database.repositories.curriculum_repository import (
    SqlAlchemyCurriculumRepository,
)
from stock_research_core.infrastructure.database.repositories.diagnostic_repository import (
    SqlAlchemyDiagnosticRepository,
)
from stock_research_core.infrastructure.database.repositories.ingestion_run_repository import (
    SqlAlchemyIngestionRunRepository,
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
from stock_research_core.infrastructure.database.repositories.security_repository import (
    SqlAlchemySecurityRepository,
)
from stock_research_core.infrastructure.database.repositories.tracked_security_repository import (
    SqlAlchemyTrackedSecurityRepository,
)
from stock_research_core.infrastructure.database.repositories.virtual_portfolio_repository import (
    SqlAlchemyVirtualPortfolioRepository,
)

__all__ = [
    "SqlAlchemyAdaptiveDecisionRepository",
    "SqlAlchemyAdaptiveProfileRepository",
    "SqlAlchemyAttemptRepository",
    "SqlAlchemyCurriculumRepository",
    "SqlAlchemyDiagnosticRepository",
    "SqlAlchemyIngestionRunRepository",
    "SqlAlchemyLearnerRepository",
    "SqlAlchemyLearningSessionRepository",
    "SqlAlchemyMarketBarRepository",
    "SqlAlchemyMasteryRepository",
    "SqlAlchemyMisconceptionRepository",
    "SqlAlchemyPortfolioHoldingRepository",
    "SqlAlchemyPortfolioJournalRepository",
    "SqlAlchemyPortfolioRiskRepository",
    "SqlAlchemyPortfolioTransactionRepository",
    "SqlAlchemyPortfolioValuationRepository",
    "SqlAlchemyPortfolioValuationRunRepository",
    "SqlAlchemyProgressRepository",
    "SqlAlchemyReviewScheduleRepository",
    "SqlAlchemySecurityRepository",
    "SqlAlchemyTrackedSecurityRepository",
    "SqlAlchemyVirtualPortfolioRepository",
]
