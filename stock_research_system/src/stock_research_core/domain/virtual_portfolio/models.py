"""Domain models for the FinQuest virtual-portfolio and decision-journal engine.

Technology-independent: no SQLAlchemy, FastAPI, pandas, NumPy, SciPy,
yfinance, LangGraph, n8n, or LLM/RAG library may be imported here. This
is an **educational simulation**, not a brokerage account - nothing
here executes a real trade or provides investment advice.

Some cross-object rules from the specification (e.g. "a position's
price timestamp cannot exceed the snapshot's `as_of`", "no position
price may be later than the snapshot cutoff") span two different
models (`PortfolioPositionValuation` and `PortfolioValuationSnapshot`)
and cannot be enforced by either model in isolation - they are enforced
where both objects are constructed together, in the analytics
calculator (`application.virtual_portfolio.analytics` /
`infrastructure.virtual_portfolio.pandas_portfolio_analytics`).
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from stock_research_core.domain.models import DomainModel, utc_now
from stock_research_core.domain.virtual_portfolio.enums import (
    DecisionConfidence,
    PortfolioDecisionAction,
    PortfolioFeedbackCode,
    PortfolioRiskLevel,
    PortfolioTransactionStatus,
    PortfolioTransactionType,
    PortfolioValuationRunStatus,
    TradeRejectionReason,
    VirtualPortfolioStatus,
)

_TOLERANCE = 1e-6
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def _isclose(a: float, b: float, tolerance: float = _TOLERANCE) -> bool:
    return math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance)


def _normalize_unique(values: list[str]) -> list[str]:
    normalized = [value.strip().lower() for value in values]
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate values are not allowed")
    return normalized


class VirtualPortfolio(DomainModel):
    """One learner's educational, simulated investment portfolio.

    This is a simulation for learning purposes - it is not a brokerage
    account, and Phase 7 supports USD only.
    """

    portfolio_id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    initial_cash: float = Field(gt=0)
    cash_balance: float = Field(ge=0)

    benchmark_security_id: UUID | None = None
    status: VirtualPortfolioStatus = VirtualPortfolioStatus.ACTIVE

    allow_fractional_shares: bool = True
    require_decision_journal: bool = True

    fixed_transaction_fee: float = Field(default=0.0, ge=0)
    transaction_fee_bps: float = Field(default=0.0, ge=0, le=1000)

    simulation_start_at: datetime
    current_simulation_at: datetime

    portfolio_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("base_currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _CURRENCY_PATTERN.match(normalized):
            raise ValueError("base_currency must be an uppercase three-letter code")
        if normalized != "USD":
            raise ValueError("Phase 7 officially supports USD only")
        return normalized

    @model_validator(mode="after")
    def _validate_portfolio(self) -> VirtualPortfolio:
        if self.current_simulation_at < self.simulation_start_at:
            raise ValueError("current_simulation_at cannot precede simulation_start_at")
        return self


class PortfolioTransaction(DomainModel):
    """One simulated buy or sell trade, from request through execution/rejection."""

    transaction_id: UUID = Field(default_factory=uuid4)
    portfolio_id: UUID
    security_id: UUID

    transaction_type: PortfolioTransactionType
    status: PortfolioTransactionStatus = PortfolioTransactionStatus.PENDING

    requested_at: datetime
    executed_at: datetime | None = None

    requested_quantity: float = Field(gt=0)
    executed_quantity: float | None = Field(default=None, gt=0)

    execution_price: float | None = Field(default=None, gt=0)
    gross_amount: float | None = Field(default=None, gt=0)
    fee_amount: float | None = Field(default=None, ge=0)
    net_cash_effect: float | None = None

    source_name: str = Field(min_length=1)
    interval: str = Field(min_length=1)
    execution_rule_version: str = Field(min_length=1)

    idempotency_key: str = Field(min_length=1)
    rejection_reason: TradeRejectionReason | None = None
    rejection_message: str | None = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_transaction(self) -> PortfolioTransaction:
        if self.executed_quantity is not None and self.executed_quantity > self.requested_quantity:
            raise ValueError("executed_quantity cannot exceed requested_quantity")

        if self.status == PortfolioTransactionStatus.EXECUTED:
            missing = [
                name
                for name, value in (
                    ("executed_at", self.executed_at),
                    ("executed_quantity", self.executed_quantity),
                    ("execution_price", self.execution_price),
                    ("gross_amount", self.gross_amount),
                    ("fee_amount", self.fee_amount),
                    ("net_cash_effect", self.net_cash_effect),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"an executed transaction requires: {', '.join(missing)}")

        if self.status == PortfolioTransactionStatus.REJECTED:
            if self.rejection_reason is None or not self.rejection_message:
                raise ValueError("a rejected transaction requires rejection_reason and rejection_message")

        if self.status == PortfolioTransactionStatus.PENDING:
            execution_fields = (
                self.executed_at,
                self.executed_quantity,
                self.execution_price,
                self.gross_amount,
                self.fee_amount,
                self.net_cash_effect,
            )
            if any(value is not None for value in execution_fields):
                raise ValueError("a pending transaction must not contain execution values")

        return self


class PortfolioHolding(DomainModel):
    """A portfolio's current position in one security. Never short."""

    holding_id: UUID = Field(default_factory=uuid4)
    portfolio_id: UUID
    security_id: UUID

    quantity: float = Field(ge=0)
    average_cost: float = Field(ge=0)
    cost_basis: float = Field(ge=0)
    realized_pnl: float = 0.0

    first_acquired_at: datetime
    last_transaction_at: datetime
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_holding(self) -> PortfolioHolding:
        if self.quantity == 0:
            if self.average_cost != 0 or self.cost_basis != 0:
                raise ValueError("average_cost and cost_basis must be zero when quantity is zero")
        else:
            if self.average_cost <= 0 or self.cost_basis <= 0:
                raise ValueError("a positive quantity requires a positive average_cost and cost_basis")
            if not _isclose(self.cost_basis, self.quantity * self.average_cost):
                raise ValueError("cost_basis must equal quantity * average_cost within tolerance")
        return self


class PortfolioDecisionJournalEntry(DomainModel):
    """A learner's documented rationale for a trade or a deliberate non-trade decision."""

    journal_entry_id: UUID = Field(default_factory=uuid4)
    portfolio_id: UUID
    learner_id: UUID
    security_id: UUID | None = None
    related_transaction_id: UUID | None = None

    action: PortfolioDecisionAction
    decision_at: datetime

    rationale: str = Field(min_length=10, max_length=5000)
    expected_horizon_days: int | None = Field(default=None, ge=1, le=3650)
    confidence: DecisionConfidence

    risk_tags: list[str] = Field(default_factory=list)
    information_considered: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("risk_tags", "information_considered", "assumptions")
    @classmethod
    def _normalize_lists(cls, value: list[str]) -> list[str]:
        return _normalize_unique(value)


class PortfolioPositionValuation(DomainModel):
    """One holding's valuation as of a `PortfolioValuationSnapshot`."""

    position_valuation_id: UUID = Field(default_factory=uuid4)
    snapshot_id: UUID
    portfolio_id: UUID
    security_id: UUID

    quantity: float = Field(gt=0)
    market_price: float = Field(gt=0)
    market_value: float = Field(gt=0)

    average_cost: float = Field(ge=0)
    cost_basis: float = Field(ge=0)
    unrealized_pnl: float
    unrealized_return: float

    portfolio_weight: float = Field(ge=0, le=1)
    sector: str | None = None

    price_timestamp: datetime
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_position_valuation(self) -> PortfolioPositionValuation:
        if not _isclose(self.market_value, self.quantity * self.market_price):
            raise ValueError("market_value must equal quantity * market_price within tolerance")
        if not _isclose(self.unrealized_pnl, self.market_value - self.cost_basis):
            raise ValueError("unrealized_pnl must equal market_value - cost_basis within tolerance")
        if self.cost_basis > 0 and not _isclose(
            self.unrealized_return, self.unrealized_pnl / self.cost_basis
        ):
            raise ValueError("unrealized_return must equal unrealized_pnl / cost_basis within tolerance")
        return self


class PortfolioValuationSnapshot(DomainModel):
    """A point-in-time valuation of an entire portfolio."""

    snapshot_id: UUID = Field(default_factory=uuid4)
    portfolio_id: UUID
    as_of: datetime
    data_cutoff_at: datetime

    cash_balance: float = Field(ge=0)
    holdings_value: float = Field(ge=0)
    total_value: float = Field(ge=0)

    total_cost_basis: float = Field(ge=0)
    realized_pnl: float
    unrealized_pnl: float

    net_profit: float
    total_return: float

    benchmark_return: float | None = None
    excess_return: float | None = None

    largest_position_weight: float = Field(ge=0, le=1)
    largest_sector_weight: float | None = Field(default=None, ge=0, le=1)
    cash_weight: float = Field(ge=0, le=1)
    position_count: int = Field(ge=0)

    portfolio_hhi: float = Field(ge=0, le=1)
    sector_hhi: float | None = Field(default=None, ge=0, le=1)
    diversification_score: float = Field(ge=0, le=1)

    valuation_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_snapshot(self) -> PortfolioValuationSnapshot:
        if self.data_cutoff_at > self.as_of:
            raise ValueError("data_cutoff_at cannot exceed as_of")
        if not _isclose(self.total_value, self.cash_balance + self.holdings_value):
            raise ValueError("total_value must equal cash_balance + holdings_value within tolerance")
        return self


class PortfolioPerformanceSummary(DomainModel):
    """A portfolio's performance over a bounded date range."""

    portfolio_id: UUID
    start_at: datetime
    end_at: datetime

    start_value: float = Field(gt=0)
    end_value: float = Field(gt=0)
    total_return: float
    annualized_volatility: float | None = Field(default=None, ge=0)
    maximum_drawdown: float | None = Field(default=None, le=0)

    benchmark_return: float | None = None
    excess_return: float | None = None

    turnover_ratio: float = Field(ge=0)
    average_cash_weight: float = Field(ge=0, le=1)
    average_position_count: float = Field(ge=0)

    calculation_version: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_summary(self) -> PortfolioPerformanceSummary:
        if self.start_at >= self.end_at:
            raise ValueError("start_at must precede end_at")
        return self


class PortfolioRiskAssessment(DomainModel):
    """Deterministic, educational risk/diversification feedback for one snapshot."""

    assessment_id: UUID = Field(default_factory=uuid4)
    portfolio_id: UUID
    snapshot_id: UUID

    risk_level: PortfolioRiskLevel
    feedback_codes: list[PortfolioFeedbackCode] = Field(default_factory=list)

    position_concentration_score: float = Field(ge=0, le=1)
    sector_concentration_score: float | None = Field(default=None, ge=0, le=1)
    diversification_score: float = Field(ge=0, le=1)
    drawdown_risk_score: float | None = Field(default=None, ge=0, le=1)
    volatility_risk_score: float | None = Field(default=None, ge=0, le=1)
    turnover_risk_score: float | None = Field(default=None, ge=0, le=1)

    summary: str = Field(min_length=1)
    educational_feedback: list[str] = Field(default_factory=list)
    related_skill_ids: list[UUID] = Field(default_factory=list)

    policy_version: str = Field(min_length=1)
    calculated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_assessment(self) -> PortfolioRiskAssessment:
        if len(set(self.feedback_codes)) != len(self.feedback_codes):
            raise ValueError("duplicate feedback_codes are not allowed")
        if len(set(self.related_skill_ids)) != len(self.related_skill_ids):
            raise ValueError("duplicate related_skill_ids are not allowed")
        return self


class PortfolioValuationRun(DomainModel):
    """An auditable record of one valuation calculation attempt."""

    run_id: UUID = Field(default_factory=uuid4)
    portfolio_id: UUID
    status: PortfolioValuationRunStatus = PortfolioValuationRunStatus.STARTED
    requested_as_of: datetime
    valuation_version: str = Field(min_length=1)
    risk_policy_version: str = Field(min_length=1)

    holding_count: int = Field(ge=0)
    priced_holding_count: int = Field(ge=0)
    missing_price_count: int = Field(ge=0)

    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _validate_run(self) -> PortfolioValuationRun:
        if self.priced_holding_count + self.missing_price_count > self.holding_count:
            raise ValueError("priced_holding_count + missing_price_count cannot exceed holding_count")
        if self.status == PortfolioValuationRunStatus.COMPLETED and self.completed_at is None:
            raise ValueError("a completed run requires completed_at")
        if self.status == PortfolioValuationRunStatus.FAILED and (
            not self.error_type or not self.error_message
        ):
            raise ValueError("a failed run requires error_type and error_message")
        return self
