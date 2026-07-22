"""Unit tests for `AverageCostPortfolioAccountingPolicy` (average-cost-accounting-v1)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.virtual_portfolio.execution import AverageCostPortfolioAccountingPolicy
from stock_research_core.domain.virtual_portfolio.models import PortfolioHolding

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = AverageCostPortfolioAccountingPolicy()


def test_policy_version_is_stable() -> None:
    assert POLICY.accounting_version == "average-cost-accounting-v1"


def test_first_buy_creates_new_holding_with_average_cost() -> None:
    portfolio_id, security_id = uuid4(), uuid4()
    holding = POLICY.apply_buy(
        holding=None, portfolio_id=portfolio_id, security_id=security_id,
        quantity=10, execution_price=100.0, fee=5.0, executed_at=NOW,
    )
    assert holding.quantity == 10
    assert holding.cost_basis == 1005.0
    assert holding.average_cost == pytest.approx(100.5)
    assert holding.realized_pnl == 0.0


def test_second_buy_updates_weighted_average_cost() -> None:
    portfolio_id, security_id = uuid4(), uuid4()
    first = POLICY.apply_buy(
        holding=None, portfolio_id=portfolio_id, security_id=security_id,
        quantity=10, execution_price=100.0, fee=0.0, executed_at=NOW,
    )
    second = POLICY.apply_buy(
        holding=first, portfolio_id=portfolio_id, security_id=security_id,
        quantity=10, execution_price=120.0, fee=0.0, executed_at=NOW,
    )
    # (1000 + 1200) / 20 = 110
    assert second.quantity == 20
    assert second.cost_basis == 2200.0
    assert second.average_cost == pytest.approx(110.0)


def test_partial_sell_calculates_realized_pnl_and_keeps_average_cost() -> None:
    holding = PortfolioHolding(
        portfolio_id=uuid4(), security_id=uuid4(), quantity=10, average_cost=100.0,
        cost_basis=1000.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    updated, realized_pnl = POLICY.apply_sell(
        holding=holding, quantity=4, execution_price=150.0, fee=2.0, executed_at=NOW
    )
    # gross proceeds 600 - fee 2 - removed cost basis (100*4=400) = 198
    assert realized_pnl == pytest.approx(198.0)
    assert updated.quantity == 6
    assert updated.cost_basis == pytest.approx(600.0)
    assert updated.average_cost == pytest.approx(100.0)  # unchanged on partial sell
    assert updated.realized_pnl == pytest.approx(198.0)


def test_full_sell_clears_cost_basis_and_average_cost() -> None:
    holding = PortfolioHolding(
        portfolio_id=uuid4(), security_id=uuid4(), quantity=10, average_cost=100.0,
        cost_basis=1000.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    updated, realized_pnl = POLICY.apply_sell(
        holding=holding, quantity=10, execution_price=150.0, fee=0.0, executed_at=NOW
    )
    assert updated.quantity == 0.0
    assert updated.average_cost == 0.0
    assert updated.cost_basis == 0.0
    assert realized_pnl == pytest.approx(500.0)


def test_selling_more_than_held_quantity_raises() -> None:
    holding = PortfolioHolding(
        portfolio_id=uuid4(), security_id=uuid4(), quantity=5, average_cost=100.0,
        cost_basis=500.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    with pytest.raises(ValueError):
        POLICY.apply_sell(holding=holding, quantity=10, execution_price=100.0, fee=0.0, executed_at=NOW)


def test_repeated_realized_pnl_accumulates_across_sells() -> None:
    holding = PortfolioHolding(
        portfolio_id=uuid4(), security_id=uuid4(), quantity=10, average_cost=100.0,
        cost_basis=1000.0, first_acquired_at=NOW, last_transaction_at=NOW, realized_pnl=50.0,
    )
    updated, realized_pnl = POLICY.apply_sell(
        holding=holding, quantity=5, execution_price=120.0, fee=0.0, executed_at=NOW
    )
    assert realized_pnl == pytest.approx(100.0)  # 600 - 500 removed cost basis
    assert updated.realized_pnl == pytest.approx(150.0)  # 50 previous + 100 new


def test_accounting_is_deterministic() -> None:
    holding = PortfolioHolding(
        portfolio_id=uuid4(), security_id=uuid4(), quantity=10, average_cost=100.0,
        cost_basis=1000.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    kwargs = dict(holding=holding, quantity=5, execution_price=120.0, fee=1.0, executed_at=NOW)
    first_holding, first_pnl = POLICY.apply_sell(**kwargs)
    second_holding, second_pnl = POLICY.apply_sell(**kwargs)
    assert first_pnl == second_pnl
    assert first_holding.quantity == second_holding.quantity
