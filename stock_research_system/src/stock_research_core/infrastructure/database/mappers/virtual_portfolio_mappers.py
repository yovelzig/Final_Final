"""Maps between virtual-portfolio ORM rows and virtual-portfolio domain models.

`PortfolioDecisionJournalEntry.risk_tags`/`.information_considered`/
`.assumptions`, and `PortfolioRiskAssessment.feedback_codes`/
`.related_skill_ids` live in separate association tables, not on the
primary ORM row - repositories query those separately and pass the
resulting lists into these mapper functions.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
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
    PortfolioPositionValuation,
    PortfolioRiskAssessment,
    PortfolioTransaction,
    PortfolioValuationRun,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)
from stock_research_core.infrastructure.database.orm.portfolio_decision_journal import (
    PortfolioDecisionJournalEntryORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_holding import PortfolioHoldingORM
from stock_research_core.infrastructure.database.orm.portfolio_position_valuation import (
    PortfolioPositionValuationORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_risk_assessment import (
    PortfolioRiskAssessmentORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_transaction import PortfolioTransactionORM
from stock_research_core.infrastructure.database.orm.portfolio_valuation_run import PortfolioValuationRunORM
from stock_research_core.infrastructure.database.orm.portfolio_valuation_snapshot import (
    PortfolioValuationSnapshotORM,
)
from stock_research_core.infrastructure.database.orm.virtual_portfolio import VirtualPortfolioORM


def virtual_portfolio_orm_to_domain(row: VirtualPortfolioORM) -> VirtualPortfolio:
    try:
        return VirtualPortfolio(
            portfolio_id=row.portfolio_id,
            learner_id=row.learner_id,
            name=row.name,
            description=row.description,
            base_currency=row.base_currency,
            initial_cash=float(row.initial_cash),
            cash_balance=float(row.cash_balance),
            benchmark_security_id=row.benchmark_security_id,
            status=VirtualPortfolioStatus(row.status),
            allow_fractional_shares=row.allow_fractional_shares,
            require_decision_journal=row.require_decision_journal,
            fixed_transaction_fee=float(row.fixed_transaction_fee),
            transaction_fee_bps=float(row.transaction_fee_bps),
            simulation_start_at=row.simulation_start_at,
            current_simulation_at=row.current_simulation_at,
            portfolio_version=row.portfolio_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored virtual portfolio row '{row.portfolio_id}' could not be mapped to a domain "
            "VirtualPortfolio."
        ) from exc


def portfolio_transaction_orm_to_domain(row: PortfolioTransactionORM) -> PortfolioTransaction:
    try:
        return PortfolioTransaction(
            transaction_id=row.transaction_id,
            portfolio_id=row.portfolio_id,
            security_id=row.security_id,
            transaction_type=PortfolioTransactionType(row.transaction_type),
            status=PortfolioTransactionStatus(row.status),
            requested_at=row.requested_at,
            executed_at=row.executed_at,
            requested_quantity=float(row.requested_quantity),
            executed_quantity=float(row.executed_quantity) if row.executed_quantity is not None else None,
            execution_price=float(row.execution_price) if row.execution_price is not None else None,
            gross_amount=float(row.gross_amount) if row.gross_amount is not None else None,
            fee_amount=float(row.fee_amount) if row.fee_amount is not None else None,
            net_cash_effect=float(row.net_cash_effect) if row.net_cash_effect is not None else None,
            source_name=row.source_name,
            interval=row.interval,
            execution_rule_version=row.execution_rule_version,
            idempotency_key=row.idempotency_key,
            rejection_reason=(
                TradeRejectionReason(row.rejection_reason) if row.rejection_reason is not None else None
            ),
            rejection_message=row.rejection_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored portfolio transaction row '{row.transaction_id}' could not be mapped to a domain "
            "PortfolioTransaction."
        ) from exc


def portfolio_holding_orm_to_domain(row: PortfolioHoldingORM) -> PortfolioHolding:
    try:
        return PortfolioHolding(
            holding_id=row.holding_id,
            portfolio_id=row.portfolio_id,
            security_id=row.security_id,
            quantity=float(row.quantity),
            average_cost=float(row.average_cost),
            cost_basis=float(row.cost_basis),
            realized_pnl=float(row.realized_pnl),
            first_acquired_at=row.first_acquired_at,
            last_transaction_at=row.last_transaction_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored portfolio holding row '{row.holding_id}' could not be mapped to a domain "
            "PortfolioHolding."
        ) from exc


def portfolio_decision_journal_entry_orm_to_domain(
    row: PortfolioDecisionJournalEntryORM,
    risk_tags: list[str],
    information_considered: list[str],
    assumptions: list[str],
) -> PortfolioDecisionJournalEntry:
    try:
        return PortfolioDecisionJournalEntry(
            journal_entry_id=row.journal_entry_id,
            portfolio_id=row.portfolio_id,
            learner_id=row.learner_id,
            security_id=row.security_id,
            related_transaction_id=row.related_transaction_id,
            action=PortfolioDecisionAction(row.action),
            decision_at=row.decision_at,
            rationale=row.rationale,
            expected_horizon_days=row.expected_horizon_days,
            confidence=DecisionConfidence(row.confidence),
            risk_tags=risk_tags,
            information_considered=information_considered,
            assumptions=assumptions,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored decision journal entry row '{row.journal_entry_id}' could not be mapped to a "
            "domain PortfolioDecisionJournalEntry."
        ) from exc


def portfolio_valuation_snapshot_orm_to_domain(
    row: PortfolioValuationSnapshotORM,
) -> PortfolioValuationSnapshot:
    try:
        return PortfolioValuationSnapshot(
            snapshot_id=row.snapshot_id,
            portfolio_id=row.portfolio_id,
            as_of=row.as_of,
            data_cutoff_at=row.data_cutoff_at,
            cash_balance=float(row.cash_balance),
            holdings_value=float(row.holdings_value),
            total_value=float(row.total_value),
            total_cost_basis=float(row.total_cost_basis),
            realized_pnl=float(row.realized_pnl),
            unrealized_pnl=float(row.unrealized_pnl),
            net_profit=float(row.net_profit),
            total_return=float(row.total_return),
            benchmark_return=float(row.benchmark_return) if row.benchmark_return is not None else None,
            excess_return=float(row.excess_return) if row.excess_return is not None else None,
            largest_position_weight=float(row.largest_position_weight),
            largest_sector_weight=(
                float(row.largest_sector_weight) if row.largest_sector_weight is not None else None
            ),
            cash_weight=float(row.cash_weight),
            position_count=row.position_count,
            portfolio_hhi=float(row.portfolio_hhi),
            sector_hhi=float(row.sector_hhi) if row.sector_hhi is not None else None,
            diversification_score=float(row.diversification_score),
            valuation_version=row.valuation_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored valuation snapshot row '{row.snapshot_id}' could not be mapped to a domain "
            "PortfolioValuationSnapshot."
        ) from exc


def portfolio_position_valuation_orm_to_domain(
    row: PortfolioPositionValuationORM,
) -> PortfolioPositionValuation:
    try:
        return PortfolioPositionValuation(
            position_valuation_id=row.position_valuation_id,
            snapshot_id=row.snapshot_id,
            portfolio_id=row.portfolio_id,
            security_id=row.security_id,
            quantity=float(row.quantity),
            market_price=float(row.market_price),
            market_value=float(row.market_value),
            average_cost=float(row.average_cost),
            cost_basis=float(row.cost_basis),
            unrealized_pnl=float(row.unrealized_pnl),
            unrealized_return=float(row.unrealized_return),
            portfolio_weight=float(row.portfolio_weight),
            sector=row.sector,
            price_timestamp=row.price_timestamp,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored position valuation row '{row.position_valuation_id}' could not be mapped to a "
            "domain PortfolioPositionValuation."
        ) from exc


def portfolio_risk_assessment_orm_to_domain(
    row: PortfolioRiskAssessmentORM,
    feedback_codes: list[str],
    related_skill_ids: list[UUID],
) -> PortfolioRiskAssessment:
    try:
        return PortfolioRiskAssessment(
            assessment_id=row.assessment_id,
            portfolio_id=row.portfolio_id,
            snapshot_id=row.snapshot_id,
            risk_level=PortfolioRiskLevel(row.risk_level),
            feedback_codes=[PortfolioFeedbackCode(code) for code in feedback_codes],
            position_concentration_score=float(row.position_concentration_score),
            sector_concentration_score=(
                float(row.sector_concentration_score) if row.sector_concentration_score is not None else None
            ),
            diversification_score=float(row.diversification_score),
            drawdown_risk_score=(
                float(row.drawdown_risk_score) if row.drawdown_risk_score is not None else None
            ),
            volatility_risk_score=(
                float(row.volatility_risk_score) if row.volatility_risk_score is not None else None
            ),
            turnover_risk_score=(
                float(row.turnover_risk_score) if row.turnover_risk_score is not None else None
            ),
            summary=row.summary,
            educational_feedback=list(row.educational_feedback or []),
            related_skill_ids=related_skill_ids,
            policy_version=row.policy_version,
            calculated_at=row.calculated_at,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored risk assessment row '{row.assessment_id}' could not be mapped to a domain "
            "PortfolioRiskAssessment."
        ) from exc


def portfolio_valuation_run_orm_to_domain(row: PortfolioValuationRunORM) -> PortfolioValuationRun:
    try:
        return PortfolioValuationRun(
            run_id=row.run_id,
            portfolio_id=row.portfolio_id,
            status=PortfolioValuationRunStatus(row.status),
            requested_as_of=row.requested_as_of,
            valuation_version=row.valuation_version,
            risk_policy_version=row.risk_policy_version,
            holding_count=row.holding_count,
            priced_holding_count=row.priced_holding_count,
            missing_price_count=row.missing_price_count,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error_type=row.error_type,
            error_message=row.error_message,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored valuation run row '{row.run_id}' could not be mapped to a domain "
            "PortfolioValuationRun."
        ) from exc
