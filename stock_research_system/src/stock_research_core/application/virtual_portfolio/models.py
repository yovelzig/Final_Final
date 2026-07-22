"""Application-level result models for the virtual-portfolio engine.

Composite views assembled from virtual-portfolio-domain and
market-data-domain objects. Plain Pydantic models; no SQLAlchemy or
other infrastructure dependency here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stock_research_core.domain.models import DomainModel, Security
from stock_research_core.domain.virtual_portfolio.enums import PortfolioTransactionType, PortfolioValuationRunStatus
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioHolding,
    PortfolioPositionValuation,
    PortfolioRiskAssessment,
    PortfolioTransaction,
    PortfolioValuationRun,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)


class TradePreview(DomainModel):
    """A non-mutating preview of what executing a trade would do."""

    portfolio: VirtualPortfolio
    security: Security
    transaction_type: PortfolioTransactionType
    requested_quantity: float = Field(gt=0)

    expected_execution_at: datetime
    expected_execution_price: float = Field(gt=0)
    gross_amount: float = Field(gt=0)
    estimated_fee: float = Field(ge=0)
    estimated_cash_effect: float

    cash_before: float = Field(ge=0)
    cash_after: float
    quantity_before: float = Field(ge=0)
    quantity_after: float = Field(ge=0)

    execution_rule_version: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class TradeExecutionResult(DomainModel):
    """The result of successfully executing a trade."""

    transaction: PortfolioTransaction
    portfolio: VirtualPortfolio
    holding: PortfolioHolding
    journal_entry: PortfolioDecisionJournalEntry | None = None


class PortfolioOverview(DomainModel):
    """A composite dashboard view of one portfolio's current state."""

    portfolio: VirtualPortfolio
    holdings: list[PortfolioHolding] = Field(default_factory=list)
    latest_valuation: PortfolioValuationSnapshot | None = None
    position_valuations: list[PortfolioPositionValuation] = Field(default_factory=list)
    latest_risk_assessment: PortfolioRiskAssessment | None = None
    recent_transactions: list[PortfolioTransaction] = Field(default_factory=list)
    recent_journal_entries: list[PortfolioDecisionJournalEntry] = Field(default_factory=list)


class PortfolioValuationResult(DomainModel):
    """The result of one successful `value_portfolio` call."""

    run: PortfolioValuationRun
    snapshot: PortfolioValuationSnapshot
    positions: list[PortfolioPositionValuation] = Field(default_factory=list)
    risk_assessment: PortfolioRiskAssessment


class BatchPortfolioValuationItem(DomainModel):
    """One portfolio's outcome within a `value_many` batch call."""

    portfolio_id: UUID
    status: PortfolioValuationRunStatus
    result: PortfolioValuationResult | None = None
    error_type: str | None = None
    error_message: str | None = None
