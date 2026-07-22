"""Unit tests for virtual-portfolio ORM-to-domain mapper functions.

ORM classes are instantiated as plain Python objects (no database
connection, no PostgreSQL required).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.virtual_portfolio.enums import (
    PortfolioTransactionStatus,
    PortfolioTransactionType,
    VirtualPortfolioStatus,
)
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    portfolio_decision_journal_entry_orm_to_domain,
    portfolio_holding_orm_to_domain,
    portfolio_position_valuation_orm_to_domain,
    portfolio_risk_assessment_orm_to_domain,
    portfolio_transaction_orm_to_domain,
    portfolio_valuation_run_orm_to_domain,
    portfolio_valuation_snapshot_orm_to_domain,
    virtual_portfolio_orm_to_domain,
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

UTC_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_virtual_portfolio_orm_to_domain_maps_all_fields() -> None:
    row = VirtualPortfolioORM(
        portfolio_id=uuid4(), learner_id=uuid4(), name="P", description=None, base_currency="USD",
        initial_cash=Decimal("10000.00000000"), cash_balance=Decimal("9000.00000000"),
        benchmark_security_id=None, status="ACTIVE", allow_fractional_shares=True,
        require_decision_journal=True, fixed_transaction_fee=Decimal("0"), transaction_fee_bps=Decimal("0"),
        simulation_start_at=UTC_NOW, current_simulation_at=UTC_NOW, portfolio_version="virtual-portfolio-v1",
        created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    portfolio = virtual_portfolio_orm_to_domain(row)
    assert portfolio.status == VirtualPortfolioStatus.ACTIVE
    assert portfolio.cash_balance == 9000.0


def test_virtual_portfolio_orm_to_domain_wraps_invalid_status() -> None:
    row = VirtualPortfolioORM(
        portfolio_id=uuid4(), learner_id=uuid4(), name="P", description=None, base_currency="USD",
        initial_cash=Decimal("10000"), cash_balance=Decimal("9000"), benchmark_security_id=None,
        status="NOT_A_REAL_STATUS", allow_fractional_shares=True, require_decision_journal=True,
        fixed_transaction_fee=Decimal("0"), transaction_fee_bps=Decimal("0"),
        simulation_start_at=UTC_NOW, current_simulation_at=UTC_NOW, portfolio_version="v1",
        created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    with pytest.raises(DatabaseMappingError):
        virtual_portfolio_orm_to_domain(row)


def test_portfolio_transaction_orm_to_domain_maps_optional_execution_fields() -> None:
    row = PortfolioTransactionORM(
        transaction_id=uuid4(), portfolio_id=uuid4(), security_id=uuid4(), transaction_type="BUY",
        status="PENDING", requested_at=UTC_NOW, executed_at=None, requested_quantity=Decimal("5"),
        executed_quantity=None, execution_price=None, gross_amount=None, fee_amount=None,
        net_cash_effect=None, source_name="sim", interval="1d", execution_rule_version="next-available-open-v1",
        idempotency_key="k1", rejection_reason=None, rejection_message=None, created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )
    transaction = portfolio_transaction_orm_to_domain(row)
    assert transaction.status == PortfolioTransactionStatus.PENDING
    assert transaction.executed_quantity is None


def test_portfolio_holding_orm_to_domain_maps_decimals() -> None:
    row = PortfolioHoldingORM(
        holding_id=uuid4(), portfolio_id=uuid4(), security_id=uuid4(), quantity=Decimal("10"),
        average_cost=Decimal("100"), cost_basis=Decimal("1000"), realized_pnl=Decimal("50"),
        first_acquired_at=UTC_NOW, last_transaction_at=UTC_NOW, updated_at=UTC_NOW,
    )
    holding = portfolio_holding_orm_to_domain(row)
    assert holding.quantity == 10.0
    assert holding.realized_pnl == 50.0


def test_portfolio_decision_journal_entry_orm_to_domain_maps_lists() -> None:
    row = PortfolioDecisionJournalEntryORM(
        journal_entry_id=uuid4(), portfolio_id=uuid4(), learner_id=uuid4(), security_id=None,
        related_transaction_id=None, action="HOLD", decision_at=UTC_NOW,
        rationale="A sufficiently long rationale here.", expected_horizon_days=30, confidence="MEDIUM",
        created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    entry = portfolio_decision_journal_entry_orm_to_domain(row, ["concentration"], ["earnings report"], ["market stable"])
    assert entry.risk_tags == ["concentration"]
    assert entry.information_considered == ["earnings report"]
    assert entry.assumptions == ["market stable"]


def test_portfolio_valuation_snapshot_orm_to_domain_maps_optional_fields() -> None:
    row = PortfolioValuationSnapshotORM(
        snapshot_id=uuid4(), as_of=UTC_NOW, portfolio_id=uuid4(), data_cutoff_at=UTC_NOW,
        cash_balance=Decimal("5000"), holdings_value=Decimal("5000"), total_value=Decimal("10000"),
        total_cost_basis=Decimal("4500"), realized_pnl=Decimal("0"), unrealized_pnl=Decimal("500"),
        net_profit=Decimal("500"), total_return=Decimal("0.05"), benchmark_return=None, excess_return=None,
        largest_position_weight=Decimal("0.5"), largest_sector_weight=None, cash_weight=Decimal("0.5"),
        position_count=1, portfolio_hhi=Decimal("0.25"), sector_hhi=None, diversification_score=Decimal("0.6"),
        valuation_version="portfolio-valuation-v1", created_at=UTC_NOW, updated_at=UTC_NOW,
    )
    snapshot = portfolio_valuation_snapshot_orm_to_domain(row)
    assert snapshot.benchmark_return is None
    assert snapshot.total_return == 0.05


def test_portfolio_position_valuation_orm_to_domain_maps_all_fields() -> None:
    row = PortfolioPositionValuationORM(
        position_valuation_id=uuid4(), snapshot_id=uuid4(), portfolio_id=uuid4(), security_id=uuid4(),
        quantity=Decimal("10"), market_price=Decimal("110"), market_value=Decimal("1100"),
        average_cost=Decimal("100"), cost_basis=Decimal("1000"), unrealized_pnl=Decimal("100"),
        unrealized_return=Decimal("0.1"), portfolio_weight=Decimal("0.5"), sector="Technology",
        price_timestamp=UTC_NOW, created_at=UTC_NOW,
    )
    position = portfolio_position_valuation_orm_to_domain(row)
    assert position.sector == "Technology"
    assert position.market_value == 1100.0


def test_portfolio_risk_assessment_orm_to_domain_maps_codes_and_skills() -> None:
    skill_id = uuid4()
    row = PortfolioRiskAssessmentORM(
        assessment_id=uuid4(), portfolio_id=uuid4(), snapshot_id=uuid4(), risk_level="MODERATE",
        position_concentration_score=Decimal("0.3"), sector_concentration_score=None,
        diversification_score=Decimal("0.6"), drawdown_risk_score=None, volatility_risk_score=None,
        turnover_risk_score=None, summary="A summary.", educational_feedback=["Feedback line."],
        policy_version="portfolio-feedback-v1", calculated_at=UTC_NOW,
    )
    assessment = portfolio_risk_assessment_orm_to_domain(row, ["POSITION_CONCENTRATION"], [skill_id])
    assert assessment.feedback_codes[0].value == "POSITION_CONCENTRATION"
    assert assessment.related_skill_ids == [skill_id]


def test_portfolio_risk_assessment_orm_to_domain_wraps_invalid_code() -> None:
    row = PortfolioRiskAssessmentORM(
        assessment_id=uuid4(), portfolio_id=uuid4(), snapshot_id=uuid4(), risk_level="MODERATE",
        position_concentration_score=Decimal("0.3"), sector_concentration_score=None,
        diversification_score=Decimal("0.6"), drawdown_risk_score=None, volatility_risk_score=None,
        turnover_risk_score=None, summary="A summary.", educational_feedback=[],
        policy_version="portfolio-feedback-v1", calculated_at=UTC_NOW,
    )
    with pytest.raises(DatabaseMappingError):
        portfolio_risk_assessment_orm_to_domain(row, ["NOT_A_REAL_CODE"], [])


def test_portfolio_valuation_run_orm_to_domain_maps_counts() -> None:
    row = PortfolioValuationRunORM(
        run_id=uuid4(), portfolio_id=uuid4(), status="COMPLETED", requested_as_of=UTC_NOW,
        valuation_version="portfolio-valuation-v1", risk_policy_version="portfolio-feedback-v1",
        holding_count=2, priced_holding_count=2, missing_price_count=0, started_at=UTC_NOW,
        completed_at=UTC_NOW, error_type=None, error_message=None,
    )
    run = portfolio_valuation_run_orm_to_domain(row)
    assert run.holding_count == 2
    assert run.completed_at == UTC_NOW
