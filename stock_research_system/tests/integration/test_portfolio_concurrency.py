"""PostgreSQL integration tests: concurrency safety for trade execution.

Uses the real `VirtualPortfolioService` against the real test database
(not fakes) so `SELECT ... FOR UPDATE` row locking is genuinely
exercised under concurrent `asyncio.gather` calls.
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
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.enums import PortfolioTransactionType, TradeRejectionReason

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_portfolio(uow_factory, initial_cash: float):
    learner = LearnerProfile(display_name="Concurrency Test Learner")
    security = Security(
        ticker=f"T{uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ, currency="USD"
    )
    bar = MarketBar(
        security_id=security.security_id, timestamp=NOW + timedelta(days=1), open=100.0, high=105.0,
        low=95.0, close=102.0, adjusted_close=102.0, volume=1000, source_name="test",
    )
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        stored_security = await uow.securities.upsert(security)
        await uow.market_bars.upsert_many([bar])
        await uow.commit()

    service = VirtualPortfolioService(
        unit_of_work_factory=uow_factory, execution_policy=NextAvailableOpenExecutionPolicy(),
        accounting_policy=AverageCostPortfolioAccountingPolicy(), clock=lambda: NOW,
    )
    portfolio = await service.create_portfolio(
        learner_id=stored_learner.learner_id, name="Concurrency Portfolio", initial_cash=initial_cash,
        simulation_start_at=NOW, require_decision_journal=False,
    )
    return service, portfolio, stored_security


async def test_two_concurrent_buys_only_one_succeeds_when_cash_is_insufficient_for_both(uow_factory) -> None:
    service, portfolio, security = await _seed_portfolio(uow_factory, initial_cash=1000.0)

    async def _attempt(key: str):
        try:
            result = await service.execute_trade(
                portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
                transaction_type=PortfolioTransactionType.BUY, quantity=8, requested_at=NOW,
                idempotency_key=key, journal_entry=None,
            )
            return ("executed", result)
        except TradeRejectedError as exc:
            return ("rejected", exc.reason)

    results = await asyncio.gather(_attempt("buy-a"), _attempt("buy-b"))

    outcomes = [outcome for outcome, _ in results]
    assert outcomes.count("executed") == 1
    assert outcomes.count("rejected") == 1
    # The loser may be rejected for INSUFFICIENT_CASH (the winner spent
    # the cash first) or SIMULATION_DATE_REGRESSION (the winner already
    # advanced the portfolio's simulation clock) - which one fires is a
    # timing detail; either is a correct, safe rejection.
    rejected_reason = next(value for outcome, value in results if outcome == "rejected")
    assert rejected_reason in (
        TradeRejectionReason.INSUFFICIENT_CASH, TradeRejectionReason.SIMULATION_DATE_REGRESSION
    )

    async with uow_factory() as uow:
        final_portfolio = await uow.virtual_portfolios.get(portfolio.portfolio_id)
    assert final_portfolio.cash_balance >= 0


async def test_same_idempotency_key_concurrently_produces_one_canonical_transaction(uow_factory) -> None:
    service, portfolio, security = await _seed_portfolio(uow_factory, initial_cash=10_000.0)

    async def _attempt():
        return await service.execute_trade(
            portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
            transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
            idempotency_key="shared-key", journal_entry=None,
        )

    results = await asyncio.gather(_attempt(), _attempt())

    transaction_ids = {r.transaction.transaction_id for r in results}
    assert len(transaction_ids) == 1

    async with uow_factory() as uow:
        holding = await uow.portfolio_holdings.get(portfolio.portfolio_id, security.security_id)
    assert holding is not None
    assert holding.quantity == 5.0  # not doubled


async def test_concurrent_sells_cannot_oversell_holding(uow_factory) -> None:
    service, portfolio, security = await _seed_portfolio(uow_factory, initial_cash=10_000.0)
    await service.execute_trade(
        portfolio_id=portfolio.portfolio_id, ticker=security.ticker, transaction_type=PortfolioTransactionType.BUY,
        quantity=10, requested_at=NOW, idempotency_key="initial-buy", journal_entry=None,
    )
    # A second future bar so that whichever sell goes second (after the
    # winner has already advanced the simulation clock to the first
    # bar's timestamp) still has a valid execution price to attempt
    # against - isolating the oversell check as the actual reason it's
    # rejected, rather than a missing price.
    extra_bar = MarketBar(
        security_id=security.security_id, timestamp=NOW + timedelta(days=2), open=101.0, high=106.0,
        low=96.0, close=103.0, adjusted_close=103.0, volume=1000, source_name="test",
    )
    async with uow_factory() as uow:
        await uow.market_bars.upsert_many([extra_bar])
        await uow.commit()

    async def _attempt(key: str):
        try:
            result = await service.execute_trade(
                portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
                transaction_type=PortfolioTransactionType.SELL, quantity=8, requested_at=NOW + timedelta(days=1),
                idempotency_key=key, journal_entry=None,
            )
            return ("executed", result)
        except TradeRejectedError as exc:
            return ("rejected", exc.reason)

    results = await asyncio.gather(_attempt("sell-a"), _attempt("sell-b"))

    outcomes = [outcome for outcome, _ in results]
    assert outcomes.count("executed") == 1
    assert outcomes.count("rejected") == 1

    async with uow_factory() as uow:
        holding = await uow.portfolio_holdings.get(portfolio.portfolio_id, security.security_id)
    assert holding.quantity >= 0
    assert holding.quantity == 2.0  # 10 bought - 8 sold once


async def test_portfolio_and_holding_locks_are_released_after_rollback(uow_factory) -> None:
    """A failed trade (rejected, transaction rolled back mid-flow) must not
    leave the portfolio/holding rows locked for subsequent operations."""
    service, portfolio, security = await _seed_portfolio(uow_factory, initial_cash=100.0)

    with pytest.raises(TradeRejectedError):
        await service.execute_trade(
            portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
            transaction_type=PortfolioTransactionType.BUY, quantity=100_000, requested_at=NOW,
            idempotency_key="too-big", journal_entry=None,
        )

    # If the lock were not released, this next call would hang or time out.
    overview = await service.get_overview(portfolio.portfolio_id)
    assert overview.portfolio.cash_balance == 100.0
