"""PostgreSQL integration tests: `PortfolioJournalRepository`."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import Security
from stock_research_core.domain.virtual_portfolio.enums import (
    DecisionConfidence,
    PortfolioDecisionAction,
    PortfolioTransactionType,
)
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioTransaction,
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
            learner_id=stored_learner.learner_id, name="P", initial_cash=10_000.0, cash_balance=10_000.0,
            simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
        )
        stored_portfolio = await uow.virtual_portfolios.create(portfolio)
        await uow.commit()
    return stored_learner, stored_portfolio, stored_security


def _entry(portfolio_id, learner_id, security_id=None, **overrides) -> PortfolioDecisionJournalEntry:
    defaults: dict = dict(
        portfolio_id=portfolio_id, learner_id=learner_id, security_id=security_id,
        action=PortfolioDecisionAction.HOLD, decision_at=NOW,
        rationale="A sufficiently long rationale for this decision.", confidence=DecisionConfidence.MEDIUM,
        risk_tags=["concentration"], information_considered=["earnings"], assumptions=["market stable"],
    )
    defaults.update(overrides)
    return PortfolioDecisionJournalEntry(**defaults)


async def test_create_and_get_round_trips_association_lists(uow_factory) -> None:
    learner, portfolio, security = await _seed_portfolio_and_security(uow_factory)
    entry = _entry(portfolio.portfolio_id, learner.learner_id, security.security_id)

    async with uow_factory() as uow:
        created = await uow.portfolio_journal.create(entry)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.portfolio_journal.get(created.journal_entry_id)

    assert fetched is not None
    assert fetched.risk_tags == ["concentration"]
    assert fetched.information_considered == ["earnings"]
    assert fetched.assumptions == ["market stable"]


async def test_link_to_transaction_updates_related_transaction_id(uow_factory) -> None:
    learner, portfolio, security = await _seed_portfolio_and_security(uow_factory)
    entry = _entry(portfolio.portfolio_id, learner.learner_id, security.security_id, related_transaction_id=None)
    async with uow_factory() as uow:
        created = await uow.portfolio_journal.create(entry)
        transaction = await uow.portfolio_transactions.create_pending(
            PortfolioTransaction(
                portfolio_id=portfolio.portfolio_id, security_id=security.security_id,
                transaction_type=PortfolioTransactionType.BUY, requested_at=NOW, requested_quantity=5.0,
                source_name="sim", interval="1d", execution_rule_version="next-available-open-v1",
                idempotency_key="key-1",
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        linked = await uow.portfolio_journal.link_to_transaction(created.journal_entry_id, transaction.transaction_id)
        await uow.commit()

    assert linked.related_transaction_id == transaction.transaction_id

    async with uow_factory() as uow:
        by_transaction = await uow.portfolio_journal.get_by_transaction(transaction.transaction_id)
    assert by_transaction is not None
    assert by_transaction.journal_entry_id == created.journal_entry_id


async def test_list_for_portfolio_orders_newest_first(uow_factory) -> None:
    from datetime import timedelta

    learner, portfolio, security = await _seed_portfolio_and_security(uow_factory)
    older = _entry(portfolio.portfolio_id, learner.learner_id, decision_at=NOW)
    newer = _entry(portfolio.portfolio_id, learner.learner_id, decision_at=NOW + timedelta(days=1))

    async with uow_factory() as uow:
        await uow.portfolio_journal.create(older)
        await uow.portfolio_journal.create(newer)
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.portfolio_journal.list_for_portfolio(portfolio.portfolio_id)

    assert listed[0].journal_entry_id == newer.journal_entry_id


async def test_list_for_security_filters_by_security(uow_factory) -> None:
    learner, portfolio, security = await _seed_portfolio_and_security(uow_factory)
    matching = _entry(portfolio.portfolio_id, learner.learner_id, security_id=security.security_id)
    unrelated = _entry(portfolio.portfolio_id, learner.learner_id, security_id=None)

    async with uow_factory() as uow:
        await uow.portfolio_journal.create(matching)
        await uow.portfolio_journal.create(unrelated)
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.portfolio_journal.list_for_security(portfolio.portfolio_id, security.security_id)

    assert {e.journal_entry_id for e in listed} == {matching.journal_entry_id}
