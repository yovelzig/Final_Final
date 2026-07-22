"""PostgreSQL integration tests: `PortfolioValuationRepository`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import Security
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioPositionValuation,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)

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
            learner_id=stored_learner.learner_id, name="P", initial_cash=10_000.0, cash_balance=8_000.0,
            simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
        )
        stored_portfolio = await uow.virtual_portfolios.create(portfolio)
        await uow.commit()
    return stored_portfolio, stored_security


def _snapshot(portfolio_id, as_of=NOW, **overrides) -> PortfolioValuationSnapshot:
    defaults: dict = dict(
        portfolio_id=portfolio_id, as_of=as_of, data_cutoff_at=as_of, cash_balance=8000.0, holdings_value=2000.0,
        total_value=10000.0, total_cost_basis=1800.0, realized_pnl=0.0, unrealized_pnl=200.0, net_profit=200.0,
        total_return=0.0, largest_position_weight=0.2, cash_weight=0.8, position_count=1, portfolio_hhi=0.04,
        diversification_score=0.7, valuation_version="portfolio-valuation-v1",
    )
    defaults.update(overrides)
    return PortfolioValuationSnapshot(**defaults)


async def test_upsert_snapshot_is_idempotent_for_same_as_of_and_version(uow_factory) -> None:
    portfolio, _security = await _seed_portfolio_and_security(uow_factory)
    snapshot = _snapshot(portfolio.portfolio_id)

    async with uow_factory() as uow:
        first = await uow.portfolio_valuations.upsert_snapshot(snapshot)
        await uow.commit()

    updated = snapshot.model_copy(update={"total_value": 12000.0, "holdings_value": 4000.0})
    async with uow_factory() as uow:
        second = await uow.portfolio_valuations.upsert_snapshot(updated)
        await uow.commit()

    assert first.snapshot_id == second.snapshot_id
    assert second.total_value == 12000.0

    async with uow_factory() as uow:
        listed = await uow.portfolio_valuations.list_range(
            portfolio.portfolio_id, NOW - timedelta(days=1), NOW + timedelta(days=1)
        )
    assert len(listed) == 1


async def test_upsert_positions_is_idempotent(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    snapshot = _snapshot(portfolio.portfolio_id)
    async with uow_factory() as uow:
        stored_snapshot = await uow.portfolio_valuations.upsert_snapshot(snapshot)
        await uow.commit()

    position = PortfolioPositionValuation(
        snapshot_id=stored_snapshot.snapshot_id, portfolio_id=portfolio.portfolio_id,
        security_id=security.security_id, quantity=10.0, market_price=200.0, market_value=2000.0,
        average_cost=180.0, cost_basis=1800.0, unrealized_pnl=200.0, unrealized_return=200.0 / 1800.0,
        portfolio_weight=0.2, price_timestamp=NOW,
    )
    async with uow_factory() as uow:
        first = await uow.portfolio_valuations.upsert_positions([position])
        await uow.commit()

    updated_position = position.model_copy(
        update={
            "market_price": 210.0, "market_value": 2100.0, "unrealized_pnl": 300.0,
            "unrealized_return": 300.0 / 1800.0,
        }
    )
    async with uow_factory() as uow:
        second = await uow.portfolio_valuations.upsert_positions([updated_position])
        await uow.commit()

    assert first[0].position_valuation_id == second[0].position_valuation_id
    assert second[0].market_price == 210.0

    async with uow_factory() as uow:
        listed = await uow.portfolio_valuations.list_positions(stored_snapshot.snapshot_id)
    assert len(listed) == 1


async def test_get_latest_returns_most_recent_snapshot(uow_factory) -> None:
    portfolio, _security = await _seed_portfolio_and_security(uow_factory)
    earlier = _snapshot(portfolio.portfolio_id, as_of=NOW)
    later = _snapshot(portfolio.portfolio_id, as_of=NOW + timedelta(days=1))

    async with uow_factory() as uow:
        await uow.portfolio_valuations.upsert_snapshot(earlier)
        await uow.portfolio_valuations.upsert_snapshot(later)
        await uow.commit()

    async with uow_factory() as uow:
        latest = await uow.portfolio_valuations.get_latest(portfolio.portfolio_id)

    assert latest is not None
    assert latest.as_of == later.as_of


async def test_get_by_as_of_and_version(uow_factory) -> None:
    portfolio, _security = await _seed_portfolio_and_security(uow_factory)
    snapshot = _snapshot(portfolio.portfolio_id)
    async with uow_factory() as uow:
        await uow.portfolio_valuations.upsert_snapshot(snapshot)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.portfolio_valuations.get_by_as_of(
            portfolio.portfolio_id, NOW, "portfolio-valuation-v1"
        )
        missing = await uow.portfolio_valuations.get_by_as_of(
            portfolio.portfolio_id, NOW, "some-other-version"
        )

    assert found is not None
    assert missing is None
