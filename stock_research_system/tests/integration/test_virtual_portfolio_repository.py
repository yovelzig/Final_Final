"""PostgreSQL integration tests: migration 0005 and `VirtualPortfolioRepository`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.virtual_portfolio.enums import VirtualPortfolioStatus
from stock_research_core.domain.virtual_portfolio.models import VirtualPortfolio

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

_PORTFOLIO_TABLES = {
    "virtual_portfolios",
    "portfolio_transactions",
    "portfolio_holdings",
    "portfolio_decision_journal_entries",
    "portfolio_decision_journal_risk_tags",
    "portfolio_decision_journal_information_items",
    "portfolio_decision_journal_assumptions",
    "portfolio_valuation_snapshots",
    "portfolio_position_valuations",
    "portfolio_risk_assessments",
    "portfolio_risk_assessment_feedback_codes",
    "portfolio_risk_assessment_skills",
    "portfolio_valuation_runs",
}


async def test_all_portfolio_tables_exist(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync_conn: sa_inspect(sync_conn).get_table_names())
    assert _PORTFOLIO_TABLES <= set(table_names)


async def test_valuation_snapshots_is_a_hypertable(test_engine: AsyncEngine) -> None:
    from sqlalchemy import text

    async with test_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT hypertable_name FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = 'portfolio_valuation_snapshots'"
            )
        )
        row = result.scalar_one_or_none()
    assert row == "portfolio_valuation_snapshots"


async def test_existing_market_and_learning_tables_remain_intact(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        table_names = set(
            await connection.run_sync(lambda sync_conn: sa_inspect(sync_conn).get_table_names())
        )
    assert {"securities", "market_bars", "learner_profiles", "financial_skills"} <= table_names


async def _seed_learner(uow_factory) -> LearnerProfile:
    learner = LearnerProfile(display_name="Portfolio Test Learner")
    async with uow_factory() as uow:
        stored = await uow.learners.create(learner)
        await uow.commit()
    return stored


def _portfolio(learner_id, **overrides) -> VirtualPortfolio:
    defaults: dict = dict(
        learner_id=learner_id, name="Test Portfolio", initial_cash=10_000.0, cash_balance=10_000.0,
        simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
    )
    defaults.update(overrides)
    return VirtualPortfolio(**defaults)


async def test_create_and_get_portfolio(uow_factory) -> None:
    learner = await _seed_learner(uow_factory)
    portfolio = _portfolio(learner.learner_id)

    async with uow_factory() as uow:
        created = await uow.virtual_portfolios.create(portfolio)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.virtual_portfolios.get(created.portfolio_id)

    assert fetched is not None
    assert fetched.name == "Test Portfolio"
    assert fetched.status == VirtualPortfolioStatus.ACTIVE


async def test_update_portfolio_persists_cash_and_status(uow_factory) -> None:
    learner = await _seed_learner(uow_factory)
    portfolio = _portfolio(learner.learner_id)
    async with uow_factory() as uow:
        created = await uow.virtual_portfolios.create(portfolio)
        await uow.commit()

    updated = created.model_copy(
        update={"cash_balance": 5000.0, "status": VirtualPortfolioStatus.FROZEN}
    )
    async with uow_factory() as uow:
        result = await uow.virtual_portfolios.update(updated)
        await uow.commit()

    assert result.cash_balance == 5000.0
    assert result.status == VirtualPortfolioStatus.FROZEN


async def test_list_for_learner_filters_active_only(uow_factory) -> None:
    learner = await _seed_learner(uow_factory)
    active = _portfolio(learner.learner_id, name="Active")
    frozen = _portfolio(learner.learner_id, name="Frozen", status=VirtualPortfolioStatus.FROZEN)
    async with uow_factory() as uow:
        await uow.virtual_portfolios.create(active)
        await uow.virtual_portfolios.create(frozen)
        await uow.commit()

    async with uow_factory() as uow:
        active_only = await uow.virtual_portfolios.list_for_learner(learner.learner_id, active_only=True)
        every_one = await uow.virtual_portfolios.list_for_learner(learner.learner_id, active_only=False)

    assert {p.portfolio_id for p in active_only} == {active.portfolio_id}
    assert {p.portfolio_id for p in every_one} == {active.portfolio_id, frozen.portfolio_id}


async def test_get_with_for_update_lock_returns_same_row(uow_factory) -> None:
    learner = await _seed_learner(uow_factory)
    portfolio = _portfolio(learner.learner_id)
    async with uow_factory() as uow:
        created = await uow.virtual_portfolios.create(portfolio)
        await uow.commit()

    async with uow_factory() as uow:
        locked = await uow.virtual_portfolios.get(created.portfolio_id, for_update=True)
        await uow.commit()

    assert locked is not None
    assert locked.portfolio_id == created.portfolio_id
