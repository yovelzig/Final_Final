"""PostgreSQL integration tests: `PortfolioHoldingRepository`."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import Security
from stock_research_core.domain.virtual_portfolio.models import PortfolioHolding, VirtualPortfolio

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_portfolio_and_security(uow_factory):
    learner = LearnerProfile(display_name="Learner")
    security = Security(
        ticker=f"T{uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ, currency="USD"
    )
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        stored_security = await uow.securities.upsert(security)
        portfolio = VirtualPortfolio(
            learner_id=stored_learner.learner_id, name="P", initial_cash=10_000.0, cash_balance=10_000.0,
            simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
        )
        stored_portfolio = await uow.virtual_portfolios.create(portfolio)
        await uow.commit()
    return stored_portfolio, stored_security


async def test_upsert_is_idempotent_and_preserves_holding_id(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=security.security_id, quantity=10.0,
        average_cost=100.0, cost_basis=1000.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )

    async with uow_factory() as uow:
        first = await uow.portfolio_holdings.upsert(holding)
        await uow.commit()

    updated = holding.model_copy(update={"quantity": 15.0, "average_cost": 105.0, "cost_basis": 1575.0})
    async with uow_factory() as uow:
        second = await uow.portfolio_holdings.upsert(updated)
        await uow.commit()

    assert first.holding_id == second.holding_id
    assert second.quantity == 15.0


async def test_get_returns_none_when_missing(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    async with uow_factory() as uow:
        result = await uow.portfolio_holdings.get(portfolio.portfolio_id, security.security_id)
    assert result is None


async def test_list_for_portfolio_excludes_zero_quantity_by_default(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=security.security_id, quantity=0.0,
        average_cost=0.0, cost_basis=0.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    async with uow_factory() as uow:
        await uow.portfolio_holdings.upsert(holding)
        await uow.commit()

    async with uow_factory() as uow:
        default_list = await uow.portfolio_holdings.list_for_portfolio(portfolio.portfolio_id)
        include_zero_list = await uow.portfolio_holdings.list_for_portfolio(
            portfolio.portfolio_id, include_zero=True
        )

    assert default_list == []
    assert len(include_zero_list) == 1


async def test_get_with_for_update_lock(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=security.security_id, quantity=5.0,
        average_cost=100.0, cost_basis=500.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    async with uow_factory() as uow:
        await uow.portfolio_holdings.upsert(holding)
        await uow.commit()

    async with uow_factory() as uow:
        locked = await uow.portfolio_holdings.get(portfolio.portfolio_id, security.security_id, for_update=True)
        await uow.commit()

    assert locked is not None
    assert locked.quantity == 5.0
