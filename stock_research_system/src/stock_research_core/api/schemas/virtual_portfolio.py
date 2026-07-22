"""Request/response DTOs for `/api/v1/portfolios`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
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
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioHolding,
    PortfolioPerformanceSummary,
    PortfolioPositionValuation,
    PortfolioRiskAssessment,
    PortfolioTransaction,
    PortfolioValuationRun,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)


class CreatePortfolioRequest(ApiSchema):
    name: str = Field(min_length=1, max_length=200)
    initial_cash: float = Field(gt=0)
    simulation_start_at: datetime
    benchmark_ticker: str | None = None
    allow_fractional_shares: bool = True
    require_decision_journal: bool = True
    fixed_transaction_fee: float = Field(default=0.0, ge=0)
    transaction_fee_bps: float = Field(default=0.0, ge=0, le=1000)


class VirtualPortfolioResponse(ApiSchema):
    portfolio_id: UUID
    name: str
    description: str | None
    base_currency: str
    initial_cash: float
    cash_balance: float
    benchmark_security_id: UUID | None
    status: VirtualPortfolioStatus
    allow_fractional_shares: bool
    require_decision_journal: bool
    fixed_transaction_fee: float
    transaction_fee_bps: float
    simulation_start_at: datetime
    current_simulation_at: datetime

    @staticmethod
    def from_domain(portfolio: VirtualPortfolio) -> VirtualPortfolioResponse:
        return VirtualPortfolioResponse(
            portfolio_id=portfolio.portfolio_id, name=portfolio.name, description=portfolio.description,
            base_currency=portfolio.base_currency, initial_cash=portfolio.initial_cash,
            cash_balance=portfolio.cash_balance, benchmark_security_id=portfolio.benchmark_security_id,
            status=portfolio.status, allow_fractional_shares=portfolio.allow_fractional_shares,
            require_decision_journal=portfolio.require_decision_journal,
            fixed_transaction_fee=portfolio.fixed_transaction_fee,
            transaction_fee_bps=portfolio.transaction_fee_bps,
            simulation_start_at=portfolio.simulation_start_at,
            current_simulation_at=portfolio.current_simulation_at,
        )


class PreviewTradeRequest(ApiSchema):
    ticker: str = Field(min_length=1, max_length=20)
    transaction_type: PortfolioTransactionType
    quantity: float = Field(gt=0)
    requested_at: datetime


class TradePreviewResponse(ApiSchema):
    ticker: str
    transaction_type: PortfolioTransactionType
    requested_quantity: float
    expected_execution_at: datetime
    expected_execution_price: float
    gross_amount: float
    estimated_fee: float
    estimated_cash_effect: float
    cash_before: float
    cash_after: float
    quantity_before: float
    quantity_after: float
    warnings: list[str]


class JournalEntryRequest(ApiSchema):
    action: PortfolioDecisionAction
    decision_at: datetime
    rationale: str = Field(min_length=10, max_length=5000)
    expected_horizon_days: int | None = Field(default=None, ge=1, le=3650)
    confidence: DecisionConfidence
    risk_tags: list[str] = Field(default_factory=list)
    information_considered: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ExecuteTradeRequest(ApiSchema):
    ticker: str = Field(min_length=1, max_length=20)
    transaction_type: PortfolioTransactionType
    quantity: float = Field(gt=0)
    requested_at: datetime
    journal_entry: JournalEntryRequest | None = None


class PortfolioTransactionResponse(ApiSchema):
    transaction_id: UUID
    portfolio_id: UUID
    security_id: UUID
    transaction_type: PortfolioTransactionType
    status: PortfolioTransactionStatus
    requested_at: datetime
    executed_at: datetime | None
    requested_quantity: float
    executed_quantity: float | None
    execution_price: float | None
    gross_amount: float | None
    fee_amount: float | None
    net_cash_effect: float | None
    rejection_reason: TradeRejectionReason | None
    rejection_message: str | None

    @staticmethod
    def from_domain(transaction: PortfolioTransaction) -> PortfolioTransactionResponse:
        return PortfolioTransactionResponse(
            transaction_id=transaction.transaction_id, portfolio_id=transaction.portfolio_id,
            security_id=transaction.security_id, transaction_type=transaction.transaction_type,
            status=transaction.status, requested_at=transaction.requested_at,
            executed_at=transaction.executed_at, requested_quantity=transaction.requested_quantity,
            executed_quantity=transaction.executed_quantity, execution_price=transaction.execution_price,
            gross_amount=transaction.gross_amount, fee_amount=transaction.fee_amount,
            net_cash_effect=transaction.net_cash_effect, rejection_reason=transaction.rejection_reason,
            rejection_message=transaction.rejection_message,
        )


class PortfolioHoldingResponse(ApiSchema):
    holding_id: UUID
    security_id: UUID
    quantity: float
    average_cost: float
    cost_basis: float
    realized_pnl: float
    first_acquired_at: datetime
    last_transaction_at: datetime

    @staticmethod
    def from_domain(holding: PortfolioHolding) -> PortfolioHoldingResponse:
        return PortfolioHoldingResponse(
            holding_id=holding.holding_id, security_id=holding.security_id, quantity=holding.quantity,
            average_cost=holding.average_cost, cost_basis=holding.cost_basis,
            realized_pnl=holding.realized_pnl, first_acquired_at=holding.first_acquired_at,
            last_transaction_at=holding.last_transaction_at,
        )


class JournalEntryResponse(ApiSchema):
    journal_entry_id: UUID
    portfolio_id: UUID
    security_id: UUID | None
    related_transaction_id: UUID | None
    action: PortfolioDecisionAction
    decision_at: datetime
    rationale: str
    expected_horizon_days: int | None
    confidence: DecisionConfidence
    risk_tags: list[str]
    information_considered: list[str]
    assumptions: list[str]

    @staticmethod
    def from_domain(entry: PortfolioDecisionJournalEntry) -> JournalEntryResponse:
        return JournalEntryResponse(
            journal_entry_id=entry.journal_entry_id, portfolio_id=entry.portfolio_id,
            security_id=entry.security_id, related_transaction_id=entry.related_transaction_id,
            action=entry.action, decision_at=entry.decision_at, rationale=entry.rationale,
            expected_horizon_days=entry.expected_horizon_days, confidence=entry.confidence,
            risk_tags=list(entry.risk_tags), information_considered=list(entry.information_considered),
            assumptions=list(entry.assumptions),
        )


class TradeExecutionResponse(ApiSchema):
    transaction: PortfolioTransactionResponse
    portfolio: VirtualPortfolioResponse
    holding: PortfolioHoldingResponse
    journal_entry: JournalEntryResponse | None


class RecordJournalEntryRequest(ApiSchema):
    ticker: str | None = None
    action: PortfolioDecisionAction
    decision_at: datetime
    rationale: str = Field(min_length=10, max_length=5000)
    expected_horizon_days: int | None = Field(default=None, ge=1, le=3650)
    confidence: DecisionConfidence
    risk_tags: list[str] = Field(default_factory=list)
    information_considered: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class PositionValuationResponse(ApiSchema):
    position_valuation_id: UUID
    security_id: UUID
    quantity: float
    market_price: float
    market_value: float
    average_cost: float
    cost_basis: float
    unrealized_pnl: float
    unrealized_return: float
    portfolio_weight: float
    sector: str | None
    price_timestamp: datetime

    @staticmethod
    def from_domain(position: PortfolioPositionValuation) -> PositionValuationResponse:
        return PositionValuationResponse(
            position_valuation_id=position.position_valuation_id, security_id=position.security_id,
            quantity=position.quantity, market_price=position.market_price,
            market_value=position.market_value, average_cost=position.average_cost,
            cost_basis=position.cost_basis, unrealized_pnl=position.unrealized_pnl,
            unrealized_return=position.unrealized_return, portfolio_weight=position.portfolio_weight,
            sector=position.sector, price_timestamp=position.price_timestamp,
        )


class ValuationSnapshotResponse(ApiSchema):
    snapshot_id: UUID
    portfolio_id: UUID
    as_of: datetime
    data_cutoff_at: datetime
    cash_balance: float
    holdings_value: float
    total_value: float
    total_cost_basis: float
    realized_pnl: float
    unrealized_pnl: float
    net_profit: float
    total_return: float
    benchmark_return: float | None
    excess_return: float | None
    largest_position_weight: float
    largest_sector_weight: float | None
    cash_weight: float
    position_count: int
    portfolio_hhi: float
    sector_hhi: float | None
    diversification_score: float

    @staticmethod
    def from_domain(snapshot: PortfolioValuationSnapshot) -> ValuationSnapshotResponse:
        return ValuationSnapshotResponse(
            snapshot_id=snapshot.snapshot_id, portfolio_id=snapshot.portfolio_id, as_of=snapshot.as_of,
            data_cutoff_at=snapshot.data_cutoff_at, cash_balance=snapshot.cash_balance,
            holdings_value=snapshot.holdings_value, total_value=snapshot.total_value,
            total_cost_basis=snapshot.total_cost_basis, realized_pnl=snapshot.realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl, net_profit=snapshot.net_profit,
            total_return=snapshot.total_return, benchmark_return=snapshot.benchmark_return,
            excess_return=snapshot.excess_return, largest_position_weight=snapshot.largest_position_weight,
            largest_sector_weight=snapshot.largest_sector_weight, cash_weight=snapshot.cash_weight,
            position_count=snapshot.position_count, portfolio_hhi=snapshot.portfolio_hhi,
            sector_hhi=snapshot.sector_hhi, diversification_score=snapshot.diversification_score,
        )


class RiskAssessmentResponse(ApiSchema):
    assessment_id: UUID
    portfolio_id: UUID
    risk_level: PortfolioRiskLevel
    feedback_codes: list[PortfolioFeedbackCode]
    position_concentration_score: float
    sector_concentration_score: float | None
    diversification_score: float
    drawdown_risk_score: float | None
    volatility_risk_score: float | None
    turnover_risk_score: float | None
    summary: str
    educational_feedback: list[str]
    related_skill_ids: list[UUID]

    @staticmethod
    def from_domain(assessment: PortfolioRiskAssessment) -> RiskAssessmentResponse:
        return RiskAssessmentResponse(
            assessment_id=assessment.assessment_id, portfolio_id=assessment.portfolio_id,
            risk_level=assessment.risk_level, feedback_codes=list(assessment.feedback_codes),
            position_concentration_score=assessment.position_concentration_score,
            sector_concentration_score=assessment.sector_concentration_score,
            diversification_score=assessment.diversification_score,
            drawdown_risk_score=assessment.drawdown_risk_score,
            volatility_risk_score=assessment.volatility_risk_score,
            turnover_risk_score=assessment.turnover_risk_score, summary=assessment.summary,
            educational_feedback=list(assessment.educational_feedback),
            related_skill_ids=list(assessment.related_skill_ids),
        )


class PortfolioOverviewResponse(ApiSchema):
    portfolio: VirtualPortfolioResponse
    holdings: list[PortfolioHoldingResponse]
    latest_valuation: ValuationSnapshotResponse | None
    position_valuations: list[PositionValuationResponse]
    latest_risk_assessment: RiskAssessmentResponse | None
    recent_transactions: list[PortfolioTransactionResponse]
    recent_journal_entries: list[JournalEntryResponse]


class ValueAsOfRequest(ApiSchema):
    as_of: datetime


class ValuationRunResponse(ApiSchema):
    run_id: UUID
    portfolio_id: UUID
    status: PortfolioValuationRunStatus
    requested_as_of: datetime
    holding_count: int
    priced_holding_count: int
    missing_price_count: int
    started_at: datetime
    completed_at: datetime | None
    error_type: str | None
    error_message: str | None

    @staticmethod
    def from_domain(run: PortfolioValuationRun) -> ValuationRunResponse:
        return ValuationRunResponse(
            run_id=run.run_id, portfolio_id=run.portfolio_id, status=run.status,
            requested_as_of=run.requested_as_of, holding_count=run.holding_count,
            priced_holding_count=run.priced_holding_count, missing_price_count=run.missing_price_count,
            started_at=run.started_at, completed_at=run.completed_at, error_type=run.error_type,
            error_message=run.error_message,
        )


class PortfolioValuationResultResponse(ApiSchema):
    run: ValuationRunResponse
    snapshot: ValuationSnapshotResponse
    positions: list[PositionValuationResponse]
    risk_assessment: RiskAssessmentResponse


class LatestValuationResponse(ApiSchema):
    snapshot: ValuationSnapshotResponse | None
    positions: list[PositionValuationResponse]


class PerformanceRequest(ApiSchema):
    start_at: datetime
    end_at: datetime


class PerformanceSummaryResponse(ApiSchema):
    portfolio_id: UUID
    start_at: datetime
    end_at: datetime
    start_value: float
    end_value: float
    total_return: float
    annualized_volatility: float | None
    maximum_drawdown: float | None
    benchmark_return: float | None
    excess_return: float | None
    turnover_ratio: float
    average_cash_weight: float
    average_position_count: float
    warnings: list[str]

    @staticmethod
    def from_domain(summary: PortfolioPerformanceSummary) -> PerformanceSummaryResponse:
        return PerformanceSummaryResponse(
            portfolio_id=summary.portfolio_id, start_at=summary.start_at, end_at=summary.end_at,
            start_value=summary.start_value, end_value=summary.end_value,
            total_return=summary.total_return, annualized_volatility=summary.annualized_volatility,
            maximum_drawdown=summary.maximum_drawdown, benchmark_return=summary.benchmark_return,
            excess_return=summary.excess_return, turnover_ratio=summary.turnover_ratio,
            average_cash_weight=summary.average_cash_weight,
            average_position_count=summary.average_position_count, warnings=list(summary.warnings),
        )
