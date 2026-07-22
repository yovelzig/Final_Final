"""PostgreSQL integration tests: `PortfolioTransactionRepository`."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import Security
from stock_research_core.domain.virtual_portfolio.enums import (
    PortfolioTransactionStatus,
    PortfolioTransactionType,
    TradeRejectionReason,
)
from stock_research_core.domain.virtual_portfolio.models import PortfolioTransaction, VirtualPortfolio

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_portfolio_and_security(uow_factory):
    learner = LearnerProfile(display_name="Learner")
    security = Security(ticker=f"T{uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ, currency="USD")
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


def _pending_transaction(portfolio_id, security_id, idempotency_key: str) -> PortfolioTransaction:
    return PortfolioTransaction(
        portfolio_id=portfolio_id, security_id=security_id, transaction_type=PortfolioTransactionType.BUY,
        requested_at=NOW, requested_quantity=5.0, source_name="sim", interval="1d",
        execution_rule_version="next-available-open-v1", idempotency_key=idempotency_key,
    )


async def test_create_pending_and_get(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    transaction = _pending_transaction(portfolio.portfolio_id, security.security_id, "key-1")

    async with uow_factory() as uow:
        created = await uow.portfolio_transactions.create_pending(transaction)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.portfolio_transactions.get(created.transaction_id)

    assert fetched is not None
    assert fetched.status == PortfolioTransactionStatus.PENDING


async def test_get_by_idempotency_key_is_transaction_safe(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    transaction = _pending_transaction(portfolio.portfolio_id, security.security_id, "unique-key")

    async with uow_factory() as uow:
        await uow.portfolio_transactions.create_pending(transaction)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.portfolio_transactions.get_by_idempotency_key(portfolio.portfolio_id, "unique-key")
        missing = await uow.portfolio_transactions.get_by_idempotency_key(portfolio.portfolio_id, "no-such-key")

    assert found is not None
    assert missing is None


async def test_mark_executed_persists_execution_fields(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    transaction = _pending_transaction(portfolio.portfolio_id, security.security_id, "key-exec")
    async with uow_factory() as uow:
        created = await uow.portfolio_transactions.create_pending(transaction)
        await uow.commit()

    executed = created.model_copy(
        update={
            "status": PortfolioTransactionStatus.EXECUTED, "executed_at": NOW, "executed_quantity": 5.0,
            "execution_price": 100.0, "gross_amount": 500.0, "fee_amount": 0.0, "net_cash_effect": -500.0,
        }
    )
    async with uow_factory() as uow:
        result = await uow.portfolio_transactions.mark_executed(executed)
        await uow.commit()

    assert result.status == PortfolioTransactionStatus.EXECUTED
    assert result.execution_price == 100.0


async def test_mark_rejected_persists_reason_and_message(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    transaction = _pending_transaction(portfolio.portfolio_id, security.security_id, "key-rej")
    async with uow_factory() as uow:
        created = await uow.portfolio_transactions.create_pending(transaction)
        await uow.commit()

    rejected = created.model_copy(
        update={
            "status": PortfolioTransactionStatus.REJECTED,
            "rejection_reason": TradeRejectionReason.INSUFFICIENT_CASH,
            "rejection_message": "Not enough cash.",
        }
    )
    async with uow_factory() as uow:
        result = await uow.portfolio_transactions.mark_rejected(rejected)
        await uow.commit()

    assert result.rejection_reason == TradeRejectionReason.INSUFFICIENT_CASH


async def test_list_for_portfolio_orders_by_requested_at(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    from datetime import timedelta

    first = _pending_transaction(portfolio.portfolio_id, security.security_id, "key-a").model_copy(
        update={"requested_at": NOW}
    )
    second = _pending_transaction(portfolio.portfolio_id, security.security_id, "key-b").model_copy(
        update={"requested_at": NOW + timedelta(days=1)}
    )
    async with uow_factory() as uow:
        await uow.portfolio_transactions.create_pending(second)
        await uow.portfolio_transactions.create_pending(first)
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.portfolio_transactions.list_for_portfolio(portfolio.portfolio_id)

    assert [t.idempotency_key for t in listed] == ["key-a", "key-b"]


async def test_duplicate_idempotency_key_within_portfolio_is_enforced_by_db(uow_factory) -> None:
    portfolio, security = await _seed_portfolio_and_security(uow_factory)
    first = _pending_transaction(portfolio.portfolio_id, security.security_id, "dup-key")
    second = _pending_transaction(portfolio.portfolio_id, security.security_id, "dup-key")

    async with uow_factory() as uow:
        await uow.portfolio_transactions.create_pending(first)
        await uow.commit()

    with pytest.raises(Exception):
        async with uow_factory() as uow:
            await uow.portfolio_transactions.create_pending(second)
            await uow.commit()
