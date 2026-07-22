"""Virtual-portfolio engine use cases: result models, repository ports,
deterministic execution/accounting/analytics/feedback policies,
`VirtualPortfolioService`, and `PortfolioValuationService`.

`VirtualPortfolioService` and `PortfolioValuationService` are
intentionally not re-exported here: both import
`stock_research_core.application.persistence.ports` (for
`UnitOfWorkPort`), which in turn imports
`stock_research_core.application.virtual_portfolio.ports` - eagerly
importing either service from this package's `__init__.py` would make
that a circular import (the same issue already solved for
`application.learning` and `application.adaptive_learning`). Import
them directly:
`from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService`
`from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService`
"""

from stock_research_core.application.virtual_portfolio.execution import (
    ACCOUNTING_VERSION,
    EXECUTION_RULE_VERSION,
    AverageCostPortfolioAccountingPolicy,
    NextAvailableOpenExecutionPolicy,
)
from stock_research_core.application.virtual_portfolio.feedback import (
    FEEDBACK_VERSION,
    RuleBasedPortfolioFeedbackPolicy,
)
from stock_research_core.application.virtual_portfolio.models import (
    BatchPortfolioValuationItem,
    PortfolioOverview,
    PortfolioValuationResult,
    TradeExecutionResult,
    TradePreview,
)

__all__ = [
    "ACCOUNTING_VERSION",
    "EXECUTION_RULE_VERSION",
    "FEEDBACK_VERSION",
    "AverageCostPortfolioAccountingPolicy",
    "BatchPortfolioValuationItem",
    "NextAvailableOpenExecutionPolicy",
    "PortfolioOverview",
    "PortfolioValuationResult",
    "RuleBasedPortfolioFeedbackPolicy",
    "TradeExecutionResult",
    "TradePreview",
]
