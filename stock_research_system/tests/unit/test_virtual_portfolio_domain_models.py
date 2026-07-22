"""Unit tests for the virtual-portfolio domain models and their validation rules.

Pure Pydantic model tests: no SQLAlchemy, no fakes, no I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.virtual_portfolio.enums import (
    DecisionConfidence,
    PortfolioDecisionAction,
    PortfolioTransactionStatus,
    PortfolioTransactionType,
    PortfolioValuationRunStatus,
    TradeRejectionReason,
)
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioHolding,
    PortfolioPositionValuation,
    PortfolioTransaction,
    PortfolioValuationRun,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# VirtualPortfolio
# ---------------------------------------------------------------------------


def _portfolio(**overrides: object) -> VirtualPortfolio:
    defaults: dict = dict(
        learner_id=uuid4(),
        name="My Portfolio",
        initial_cash=10_000.0,
        cash_balance=10_000.0,
        simulation_start_at=NOW,
        current_simulation_at=NOW,
        portfolio_version="virtual-portfolio-v1",
    )
    defaults.update(overrides)
    return VirtualPortfolio(**defaults)


def test_portfolio_requires_positive_initial_cash() -> None:
    with pytest.raises(ValidationError):
        _portfolio(initial_cash=0)


def test_portfolio_rejects_negative_cash_balance() -> None:
    with pytest.raises(ValidationError):
        _portfolio(cash_balance=-1.0)


def test_portfolio_only_supports_usd() -> None:
    with pytest.raises(ValidationError):
        _portfolio(base_currency="EUR")


def test_portfolio_normalizes_lowercase_currency_before_validating() -> None:
    # Case-insensitive input is normalized to uppercase before the
    # USD-only / three-letter-code checks run.
    portfolio = _portfolio(base_currency="usd")
    assert portfolio.base_currency == "USD"


def test_portfolio_rejects_malformed_currency_code() -> None:
    with pytest.raises(ValidationError):
        _portfolio(base_currency="US1")
    with pytest.raises(ValidationError):
        _portfolio(base_currency="US")


def test_portfolio_rejects_fee_bps_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _portfolio(transaction_fee_bps=1001)


def test_portfolio_rejects_simulation_time_regression() -> None:
    with pytest.raises(ValidationError):
        _portfolio(simulation_start_at=NOW, current_simulation_at=NOW - timedelta(days=1))


def test_portfolio_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        VirtualPortfolio(
            learner_id=uuid4(),
            name="X",
            initial_cash=1.0,
            cash_balance=1.0,
            simulation_start_at=NOW,
            current_simulation_at=NOW,
            portfolio_version="v1",
            not_a_real_field="oops",
        )


# ---------------------------------------------------------------------------
# PortfolioTransaction
# ---------------------------------------------------------------------------


def _transaction(**overrides: object) -> PortfolioTransaction:
    defaults: dict = dict(
        portfolio_id=uuid4(),
        security_id=uuid4(),
        transaction_type=PortfolioTransactionType.BUY,
        requested_at=NOW,
        requested_quantity=5.0,
        source_name="sim",
        interval="1d",
        execution_rule_version="next-available-open-v1",
        idempotency_key="key-1",
    )
    defaults.update(overrides)
    return PortfolioTransaction(**defaults)


def test_transaction_rejects_executed_quantity_exceeding_requested() -> None:
    with pytest.raises(ValidationError):
        _transaction(executed_quantity=10.0)


def test_transaction_executed_requires_all_execution_fields() -> None:
    with pytest.raises(ValidationError):
        _transaction(status=PortfolioTransactionStatus.EXECUTED)
    executed = _transaction(
        status=PortfolioTransactionStatus.EXECUTED,
        executed_at=NOW,
        executed_quantity=5.0,
        execution_price=100.0,
        gross_amount=500.0,
        fee_amount=0.0,
        net_cash_effect=-500.0,
    )
    assert executed.executed_quantity == 5.0


def test_transaction_rejected_requires_reason_and_message() -> None:
    with pytest.raises(ValidationError):
        _transaction(status=PortfolioTransactionStatus.REJECTED)
    rejected = _transaction(
        status=PortfolioTransactionStatus.REJECTED,
        rejection_reason=TradeRejectionReason.INSUFFICIENT_CASH,
        rejection_message="Not enough cash.",
    )
    assert rejected.rejection_reason == TradeRejectionReason.INSUFFICIENT_CASH


def test_transaction_pending_must_not_contain_execution_values() -> None:
    with pytest.raises(ValidationError):
        _transaction(status=PortfolioTransactionStatus.PENDING, execution_price=100.0)


# ---------------------------------------------------------------------------
# PortfolioHolding
# ---------------------------------------------------------------------------


def _holding(**overrides: object) -> PortfolioHolding:
    defaults: dict = dict(
        portfolio_id=uuid4(),
        security_id=uuid4(),
        quantity=10.0,
        average_cost=100.0,
        cost_basis=1000.0,
        first_acquired_at=NOW,
        last_transaction_at=NOW,
    )
    defaults.update(overrides)
    return PortfolioHolding(**defaults)


def test_holding_rejects_negative_quantity() -> None:
    with pytest.raises(ValidationError):
        _holding(quantity=-1.0)


def test_holding_zero_quantity_requires_zero_cost_fields() -> None:
    with pytest.raises(ValidationError):
        _holding(quantity=0.0, average_cost=100.0, cost_basis=1000.0)
    zeroed = _holding(quantity=0.0, average_cost=0.0, cost_basis=0.0)
    assert zeroed.quantity == 0.0


def test_holding_positive_quantity_requires_positive_average_cost() -> None:
    with pytest.raises(ValidationError):
        _holding(quantity=10.0, average_cost=0.0, cost_basis=0.0)


def test_holding_cost_basis_must_match_quantity_times_average_cost() -> None:
    with pytest.raises(ValidationError):
        _holding(quantity=10.0, average_cost=100.0, cost_basis=5000.0)


# ---------------------------------------------------------------------------
# PortfolioDecisionJournalEntry
# ---------------------------------------------------------------------------


def _journal_entry(**overrides: object) -> PortfolioDecisionJournalEntry:
    defaults: dict = dict(
        portfolio_id=uuid4(),
        learner_id=uuid4(),
        action=PortfolioDecisionAction.HOLD,
        decision_at=NOW,
        rationale="This is a sufficiently long rationale.",
        confidence=DecisionConfidence.MEDIUM,
    )
    defaults.update(overrides)
    return PortfolioDecisionJournalEntry(**defaults)


def test_journal_entry_rejects_too_short_rationale() -> None:
    with pytest.raises(ValidationError):
        _journal_entry(rationale="short")


def test_journal_entry_rejects_horizon_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _journal_entry(expected_horizon_days=0)
    with pytest.raises(ValidationError):
        _journal_entry(expected_horizon_days=3651)


def test_journal_entry_rejects_tags_that_normalize_to_duplicates() -> None:
    # normalization (strip + lowercase) collapses these two into the
    # same string, which the duplicate check then rejects
    with pytest.raises(ValidationError):
        _journal_entry(risk_tags=["Concentration", " concentration "])


def test_journal_entry_normalizes_distinct_risk_tags() -> None:
    entry = _journal_entry(risk_tags=["Concentration", "Volatility"])
    assert entry.risk_tags == ["concentration", "volatility"]


# ---------------------------------------------------------------------------
# PortfolioPositionValuation
# ---------------------------------------------------------------------------


def _position_valuation(**overrides: object) -> PortfolioPositionValuation:
    defaults: dict = dict(
        snapshot_id=uuid4(),
        portfolio_id=uuid4(),
        security_id=uuid4(),
        quantity=10.0,
        market_price=110.0,
        market_value=1100.0,
        average_cost=100.0,
        cost_basis=1000.0,
        unrealized_pnl=100.0,
        unrealized_return=0.1,
        portfolio_weight=0.5,
        price_timestamp=NOW,
    )
    defaults.update(overrides)
    return PortfolioPositionValuation(**defaults)


def test_position_valuation_requires_consistent_market_value() -> None:
    with pytest.raises(ValidationError):
        _position_valuation(market_value=9999.0)


def test_position_valuation_requires_consistent_unrealized_pnl() -> None:
    with pytest.raises(ValidationError):
        _position_valuation(unrealized_pnl=1.0)


def test_position_valuation_requires_consistent_unrealized_return() -> None:
    with pytest.raises(ValidationError):
        _position_valuation(unrealized_return=0.5)


def test_position_valuation_rejects_weight_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _position_valuation(portfolio_weight=1.5)


# ---------------------------------------------------------------------------
# PortfolioValuationSnapshot
# ---------------------------------------------------------------------------


def _snapshot(**overrides: object) -> PortfolioValuationSnapshot:
    defaults: dict = dict(
        portfolio_id=uuid4(),
        as_of=NOW,
        data_cutoff_at=NOW,
        cash_balance=5000.0,
        holdings_value=5000.0,
        total_value=10000.0,
        total_cost_basis=4500.0,
        realized_pnl=0.0,
        unrealized_pnl=500.0,
        net_profit=500.0,
        total_return=0.0,
        largest_position_weight=0.5,
        cash_weight=0.5,
        position_count=1,
        portfolio_hhi=0.25,
        diversification_score=0.6,
        valuation_version="portfolio-valuation-v1",
    )
    defaults.update(overrides)
    return PortfolioValuationSnapshot(**defaults)


def test_snapshot_rejects_data_cutoff_after_as_of() -> None:
    with pytest.raises(ValidationError):
        _snapshot(as_of=NOW, data_cutoff_at=NOW + timedelta(days=1))


def test_snapshot_requires_total_value_consistency() -> None:
    with pytest.raises(ValidationError):
        _snapshot(total_value=9999.0)


def test_snapshot_rejects_weight_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _snapshot(cash_weight=1.5)


def test_snapshot_rejects_negative_position_count() -> None:
    with pytest.raises(ValidationError):
        _snapshot(position_count=-1)


# ---------------------------------------------------------------------------
# PortfolioValuationRun
# ---------------------------------------------------------------------------


def _run(**overrides: object) -> PortfolioValuationRun:
    defaults: dict = dict(
        portfolio_id=uuid4(),
        requested_as_of=NOW,
        valuation_version="portfolio-valuation-v1",
        risk_policy_version="portfolio-feedback-v1",
        holding_count=2,
        priced_holding_count=2,
        missing_price_count=0,
    )
    defaults.update(overrides)
    return PortfolioValuationRun(**defaults)


def test_run_rejects_priced_plus_missing_exceeding_holding_count() -> None:
    with pytest.raises(ValidationError):
        _run(holding_count=2, priced_holding_count=2, missing_price_count=1)


def test_run_completed_requires_completed_at() -> None:
    with pytest.raises(ValidationError):
        _run(status=PortfolioValuationRunStatus.COMPLETED)
    completed = _run(status=PortfolioValuationRunStatus.COMPLETED, completed_at=NOW)
    assert completed.completed_at == NOW


def test_run_failed_requires_error_fields() -> None:
    with pytest.raises(ValidationError):
        _run(status=PortfolioValuationRunStatus.FAILED, completed_at=NOW)
    failed = _run(
        status=PortfolioValuationRunStatus.FAILED,
        completed_at=NOW,
        error_type="ValueError",
        error_message="something went wrong",
    )
    assert failed.error_type == "ValueError"
