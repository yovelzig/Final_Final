"""PostgreSQL end-to-end integration tests for the virtual-portfolio engine.

Exercises the real `VirtualPortfolioService` and `PortfolioValuationService`
together against the actual test database - full create -> buy -> sell ->
value -> performance flow, point-in-time correctness, rollback safety,
and bounded parallel valuation across several portfolios.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import TradeRejectedError
from stock_research_core.application.virtual_portfolio.execution import (
    AverageCostPortfolioAccountingPolicy,
    NextAvailableOpenExecutionPolicy,
)
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.enums import (
    DecisionConfidence,
    PortfolioDecisionAction,
    PortfolioTransactionType,
    PortfolioValuationRunStatus,
)
from stock_research_core.domain.virtual_portfolio.models import PortfolioDecisionJournalEntry
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import (
    PandasPortfolioAnalytics,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_services(uow_factory):
    portfolio_service = VirtualPortfolioService(
        unit_of_work_factory=uow_factory, execution_policy=NextAvailableOpenExecutionPolicy(),
        accounting_policy=AverageCostPortfolioAccountingPolicy(), clock=lambda: NOW,
    )
    valuation_service = PortfolioValuationService(
        unit_of_work_factory=uow_factory, analytics=PandasPortfolioAnalytics(),
        feedback_policy=RuleBasedPortfolioFeedbackPolicy(), clock=lambda: NOW,
    )
    return portfolio_service, valuation_service


async def _seed_security_with_bars(uow_factory, day_prices: dict[int, float]):
    security = Security(
        ticker=f"T{uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ, currency="USD",
        sector="Technology",
    )
    bars = [
        MarketBar(
            security_id=security.security_id, timestamp=NOW + timedelta(days=day), open=price, high=price + 2,
            low=price - 2, close=price + 1, adjusted_close=price + 1, volume=1000, source_name="test",
        )
        for day, price in day_prices.items()
    ]
    async with uow_factory() as uow:
        stored_security = await uow.securities.upsert(security)
        await uow.market_bars.upsert_many(bars)
        await uow.commit()
    return stored_security


async def _seed_learner(uow_factory) -> LearnerProfile:
    async with uow_factory() as uow:
        learner = await uow.learners.create(LearnerProfile(display_name="End To End Learner"))
        await uow.commit()
    return learner


async def test_full_trade_and_valuation_flow_end_to_end(uow_factory) -> None:
    security = await _seed_security_with_bars(uow_factory, {1: 100.0, 5: 110.0, 10: 120.0})
    learner = await _seed_learner(uow_factory)
    portfolio_service, valuation_service = _make_services(uow_factory)

    portfolio = await portfolio_service.create_portfolio(
        learner_id=learner.learner_id, name="E2E Portfolio", initial_cash=10_000.0,
        simulation_start_at=NOW, require_decision_journal=True,
    )

    journal_entry = PortfolioDecisionJournalEntry(
        portfolio_id=portfolio.portfolio_id, learner_id=learner.learner_id, action=PortfolioDecisionAction.BUY,
        decision_at=NOW, rationale="A well-documented rationale for this simulated purchase.",
        confidence=DecisionConfidence.MEDIUM, expected_horizon_days=90, risk_tags=["concentration"],
    )
    buy_result = await portfolio_service.execute_trade(
        portfolio_id=portfolio.portfolio_id, ticker=security.ticker, transaction_type=PortfolioTransactionType.BUY,
        quantity=10, requested_at=NOW, idempotency_key="buy-1", journal_entry=journal_entry,
    )
    assert buy_result.holding.quantity == 10.0

    valuation = await valuation_service.value_portfolio(
        portfolio_id=portfolio.portfolio_id, as_of=NOW + timedelta(days=5)
    )
    assert valuation.run.status == PortfolioValuationRunStatus.COMPLETED
    assert valuation.snapshot.holdings_value > 0
    assert valuation.risk_assessment.risk_level is not None

    sell_journal_entry = journal_entry.model_copy(
        update={
            "journal_entry_id": uuid4(), "action": PortfolioDecisionAction.SELL,
            "decision_at": NOW + timedelta(days=6), "related_transaction_id": None,
        }
    )
    sell_result = await portfolio_service.execute_trade(
        portfolio_id=portfolio.portfolio_id, ticker=security.ticker, transaction_type=PortfolioTransactionType.SELL,
        quantity=4, requested_at=NOW + timedelta(days=6), idempotency_key="sell-1",
        journal_entry=sell_journal_entry,
    )
    assert sell_result.holding.quantity == 6.0
    assert sell_result.holding.realized_pnl != 0.0

    final_valuation = await valuation_service.value_portfolio(
        portfolio_id=portfolio.portfolio_id, as_of=NOW + timedelta(days=10)
    )
    assert final_valuation.snapshot.total_cost_basis > 0

    performance = await valuation_service.calculate_performance(
        portfolio_id=portfolio.portfolio_id, start_at=NOW, end_at=NOW + timedelta(days=10)
    )
    assert performance.turnover_ratio >= 0


async def test_rejected_trade_leaves_no_partial_state(uow_factory) -> None:
    security = await _seed_security_with_bars(uow_factory, {1: 100.0})
    learner = await _seed_learner(uow_factory)
    portfolio_service, _valuation_service = _make_services(uow_factory)
    portfolio = await portfolio_service.create_portfolio(
        learner_id=learner.learner_id, name="Rollback Portfolio", initial_cash=100.0,
        simulation_start_at=NOW, require_decision_journal=False,
    )

    with pytest.raises(TradeRejectedError):
        await portfolio_service.execute_trade(
            portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
            transaction_type=PortfolioTransactionType.BUY, quantity=1_000_000, requested_at=NOW,
            idempotency_key="huge-buy", journal_entry=None,
        )

    async with uow_factory() as uow:
        holdings = await uow.portfolio_holdings.list_for_portfolio(portfolio.portfolio_id, include_zero=True)
        stored_portfolio = await uow.virtual_portfolios.get(portfolio.portfolio_id)

    assert holdings == []
    assert stored_portfolio.cash_balance == 100.0


async def test_bounded_parallel_valuation_across_several_portfolios(uow_factory) -> None:
    security = await _seed_security_with_bars(uow_factory, {1: 100.0})
    learner = await _seed_learner(uow_factory)
    portfolio_service, valuation_service = _make_services(uow_factory)

    portfolio_ids = []
    for i in range(5):
        portfolio = await portfolio_service.create_portfolio(
            learner_id=learner.learner_id, name=f"Batch Portfolio {i}", initial_cash=5_000.0,
            simulation_start_at=NOW, require_decision_journal=False,
        )
        portfolio_ids.append(portfolio.portfolio_id)

    results = await valuation_service.value_many(portfolio_ids=portfolio_ids, as_of=NOW, max_concurrency=3)

    assert len(results) == 5
    assert all(r.status == PortfolioValuationRunStatus.COMPLETED for r in results)
    assert [r.portfolio_id for r in results] == portfolio_ids
