"""Unit tests for `VirtualPortfolioService`.

Uses fake in-memory repository implementations and a fake Unit of Work -
no SQLAlchemy or PostgreSQL is involved anywhere in this file. The real
deterministic execution/accounting policies are used (not further
fakes) so these tests also exercise the service/policy integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.exceptions import (
    InactiveLearnerError,
    InvalidPortfolioStateError,
    LearnerNotFoundError,
    TradeRejectedError,
    VirtualPortfolioNotFoundError,
)
from stock_research_core.application.virtual_portfolio.execution import (
    AverageCostPortfolioAccountingPolicy,
    NextAvailableOpenExecutionPolicy,
)
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.enums import PortfolioTransactionType, TradeRejectionReason
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioHolding,
    PortfolioTransaction,
    VirtualPortfolio,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Minimal fakes for just the repositories VirtualPortfolioService touches
# ---------------------------------------------------------------------------


class FakeLearnerRepository:
    def __init__(self) -> None:
        self.learners: dict[UUID, LearnerProfile] = {}

    async def get(self, learner_id: UUID):
        return self.learners.get(learner_id)


class FakeSecurityRepository:
    def __init__(self) -> None:
        self.securities: dict[UUID, Security] = {}

    async def get_by_id(self, security_id: UUID):
        return self.securities.get(security_id)

    async def get_by_ticker(self, ticker: str, exchange=None):
        return next((s for s in self.securities.values() if s.ticker == ticker), None)


class FakeMarketBarRepository:
    def __init__(self) -> None:
        self.bars: list[MarketBar] = []

    async def get_next_bar_after(self, security_id, after_at, interval="1d", source_name=None):
        candidates = sorted(
            (b for b in self.bars if b.security_id == security_id and b.timestamp > after_at),
            key=lambda b: b.timestamp,
        )
        return candidates[0] if candidates else None

    async def get_latest_bar_at_or_before(self, security_id, as_of, interval="1d", source_name=None):
        candidates = sorted(
            (b for b in self.bars if b.security_id == security_id and b.timestamp <= as_of),
            key=lambda b: b.timestamp,
        )
        return candidates[-1] if candidates else None

    async def list_range(self, security_id, start_at, end_at, interval="1d", source_name=None):
        return sorted(
            (b for b in self.bars if b.security_id == security_id and start_at <= b.timestamp <= end_at),
            key=lambda b: b.timestamp,
        )


class FakeVirtualPortfolioRepository:
    def __init__(self) -> None:
        self.portfolios: dict[UUID, VirtualPortfolio] = {}

    async def create(self, portfolio: VirtualPortfolio) -> VirtualPortfolio:
        self.portfolios[portfolio.portfolio_id] = portfolio
        return portfolio

    async def get(self, portfolio_id: UUID, *, for_update: bool = False):
        return self.portfolios.get(portfolio_id)

    async def list_for_learner(self, learner_id, active_only=False):
        return [p for p in self.portfolios.values() if p.learner_id == learner_id]

    async def update(self, portfolio: VirtualPortfolio) -> VirtualPortfolio:
        self.portfolios[portfolio.portfolio_id] = portfolio
        return portfolio


class FakePortfolioTransactionRepository:
    def __init__(self) -> None:
        self.transactions: dict[UUID, PortfolioTransaction] = {}

    async def create_pending(self, transaction: PortfolioTransaction) -> PortfolioTransaction:
        self.transactions[transaction.transaction_id] = transaction
        return transaction

    async def get(self, transaction_id: UUID):
        return self.transactions.get(transaction_id)

    async def get_by_idempotency_key(self, portfolio_id: UUID, idempotency_key: str):
        return next(
            (
                t
                for t in self.transactions.values()
                if t.portfolio_id == portfolio_id and t.idempotency_key == idempotency_key
            ),
            None,
        )

    async def mark_executed(self, transaction: PortfolioTransaction) -> PortfolioTransaction:
        self.transactions[transaction.transaction_id] = transaction
        return transaction

    async def mark_rejected(self, transaction: PortfolioTransaction) -> PortfolioTransaction:
        self.transactions[transaction.transaction_id] = transaction
        return transaction

    async def list_for_portfolio(self, portfolio_id, start_at=None, end_at=None):
        values = [t for t in self.transactions.values() if t.portfolio_id == portfolio_id]
        return sorted(values, key=lambda t: t.requested_at)


class FakePortfolioHoldingRepository:
    def __init__(self) -> None:
        self.holdings: dict[tuple[UUID, UUID], PortfolioHolding] = {}

    async def get(self, portfolio_id: UUID, security_id: UUID, *, for_update: bool = False):
        return self.holdings.get((portfolio_id, security_id))

    async def list_for_portfolio(self, portfolio_id, include_zero=False):
        values = [h for h in self.holdings.values() if h.portfolio_id == portfolio_id]
        if not include_zero:
            values = [h for h in values if h.quantity > 0]
        return values

    async def upsert(self, holding: PortfolioHolding) -> PortfolioHolding:
        self.holdings[(holding.portfolio_id, holding.security_id)] = holding
        return holding


class FakePortfolioJournalRepository:
    def __init__(self) -> None:
        self.entries: dict[UUID, PortfolioDecisionJournalEntry] = {}

    async def create(self, entry: PortfolioDecisionJournalEntry) -> PortfolioDecisionJournalEntry:
        self.entries[entry.journal_entry_id] = entry
        return entry

    async def link_to_transaction(self, journal_entry_id: UUID, transaction_id: UUID):
        updated = self.entries[journal_entry_id].model_copy(update={"related_transaction_id": transaction_id})
        self.entries[journal_entry_id] = updated
        return updated

    async def get(self, journal_entry_id: UUID):
        return self.entries.get(journal_entry_id)

    async def get_by_transaction(self, transaction_id: UUID):
        return next((e for e in self.entries.values() if e.related_transaction_id == transaction_id), None)

    async def list_for_portfolio(self, portfolio_id, limit=20):
        values = [e for e in self.entries.values() if e.portfolio_id == portfolio_id]
        return sorted(values, key=lambda e: e.decision_at, reverse=True)[:limit]

    async def list_for_security(self, portfolio_id, security_id):
        return [e for e in self.entries.values() if e.portfolio_id == portfolio_id and e.security_id == security_id]


class _StubValuationRepo:
    async def get_latest(self, portfolio_id):
        return None

    async def list_positions(self, snapshot_id):
        return []


class _StubRiskRepo:
    async def get_latest(self, portfolio_id):
        return None


class FakeUnitOfWork:
    def __init__(self, factory: "FakeUnitOfWorkFactory") -> None:
        self.learners = factory.learners
        self.securities = factory.securities
        self.market_bars = factory.market_bars
        self.virtual_portfolios = factory.virtual_portfolios
        self.portfolio_transactions = factory.portfolio_transactions
        self.portfolio_holdings = factory.portfolio_holdings
        self.portfolio_journal = factory.portfolio_journal
        self.portfolio_valuations = factory.portfolio_valuations
        self.portfolio_risk = factory.portfolio_risk
        self.committed = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


class FakeUnitOfWorkFactory:
    def __init__(self) -> None:
        self.learners = FakeLearnerRepository()
        self.securities = FakeSecurityRepository()
        self.market_bars = FakeMarketBarRepository()
        self.virtual_portfolios = FakeVirtualPortfolioRepository()
        self.portfolio_transactions = FakePortfolioTransactionRepository()
        self.portfolio_holdings = FakePortfolioHoldingRepository()
        self.portfolio_journal = FakePortfolioJournalRepository()
        self.portfolio_valuations = _StubValuationRepo()
        self.portfolio_risk = _StubRiskRepo()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self)


def _make_service(factory: FakeUnitOfWorkFactory) -> VirtualPortfolioService:
    return VirtualPortfolioService(
        unit_of_work_factory=factory,
        execution_policy=NextAvailableOpenExecutionPolicy(),
        accounting_policy=AverageCostPortfolioAccountingPolicy(),
        clock=lambda: NOW,
    )


def _learner(**overrides) -> LearnerProfile:
    defaults = dict(display_name="Learner")
    defaults.update(overrides)
    return LearnerProfile(**defaults)


def _security(**overrides) -> Security:
    defaults = dict(ticker="NVDA", company_name="Nvidia", exchange=Exchange.NASDAQ, currency="USD")
    defaults.update(overrides)
    return Security(**defaults)


def _bar(security_id, day: int, price: float) -> MarketBar:
    return MarketBar(
        security_id=security_id, timestamp=NOW + timedelta(days=day), open=price, high=price + 1,
        low=price - 1, close=price, adjusted_close=price, volume=1000, source_name="test",
    )


# ---------------------------------------------------------------------------
# create_portfolio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_portfolio_requires_active_learner() -> None:
    factory = FakeUnitOfWorkFactory()
    service = _make_service(factory)
    with pytest.raises(LearnerNotFoundError):
        await service.create_portfolio(
            learner_id=uuid4(), name="P", initial_cash=1000.0, simulation_start_at=NOW
        )


@pytest.mark.asyncio
async def test_create_portfolio_rejects_inactive_learner() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner(active=False)
    factory.learners.learners[learner.learner_id] = learner
    service = _make_service(factory)
    with pytest.raises(InactiveLearnerError):
        await service.create_portfolio(
            learner_id=learner.learner_id, name="P", initial_cash=1000.0, simulation_start_at=NOW
        )


@pytest.mark.asyncio
async def test_create_portfolio_sets_cash_balance_to_initial_cash() -> None:
    factory = FakeUnitOfWorkFactory()
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    service = _make_service(factory)

    portfolio = await service.create_portfolio(
        learner_id=learner.learner_id, name="P", initial_cash=5000.0, simulation_start_at=NOW
    )
    assert portfolio.cash_balance == 5000.0
    assert portfolio.current_simulation_at == NOW


# ---------------------------------------------------------------------------
# preview / execute trade
# ---------------------------------------------------------------------------


async def _seed_portfolio_and_security(factory: FakeUnitOfWorkFactory, **portfolio_overrides):
    learner = _learner()
    factory.learners.learners[learner.learner_id] = learner
    security = _security()
    factory.securities.securities[security.security_id] = security
    factory.market_bars.bars.append(_bar(security.security_id, 1, 100.0))
    factory.market_bars.bars.append(_bar(security.security_id, 2, 110.0))

    defaults: dict = dict(
        learner_id=learner.learner_id, name="P", initial_cash=10_000.0, cash_balance=10_000.0,
        simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
        require_decision_journal=False,
    )
    defaults.update(portfolio_overrides)
    portfolio = VirtualPortfolio(**defaults)
    factory.virtual_portfolios.portfolios[portfolio.portfolio_id] = portfolio
    return portfolio, security


@pytest.mark.asyncio
async def test_preview_trade_does_not_mutate_state() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(factory)
    service = _make_service(factory)

    await service.preview_trade(
        portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
        transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
    )

    assert factory.virtual_portfolios.portfolios[portfolio.portfolio_id].cash_balance == 10_000.0
    assert not factory.portfolio_transactions.transactions
    assert not factory.portfolio_holdings.holdings


@pytest.mark.asyncio
async def test_execute_trade_updates_cash_and_holding_atomically() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(factory)
    service = _make_service(factory)

    result = await service.execute_trade(
        portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
        transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
        idempotency_key="key-1", journal_entry=None,
    )

    assert result.transaction.status.value == "EXECUTED"
    assert result.holding.quantity == 5
    assert result.portfolio.cash_balance == pytest.approx(10_000.0 - 5 * 100.0)


@pytest.mark.asyncio
async def test_execute_trade_is_idempotent_for_repeated_key() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(factory)
    service = _make_service(factory)

    kwargs = dict(
        portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
        transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
        idempotency_key="dup-key", journal_entry=None,
    )
    first = await service.execute_trade(**kwargs)
    second = await service.execute_trade(**kwargs)

    assert first.transaction.transaction_id == second.transaction.transaction_id
    # Only one holding update should have occurred (still 5 shares, not 10).
    assert second.holding.quantity == 5


@pytest.mark.asyncio
async def test_execute_trade_rejects_when_portfolio_not_active() -> None:
    from stock_research_core.domain.virtual_portfolio.enums import VirtualPortfolioStatus

    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(factory, status=VirtualPortfolioStatus.FROZEN)
    service = _make_service(factory)

    with pytest.raises(InvalidPortfolioStateError):
        await service.execute_trade(
            portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
            transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
            idempotency_key="key-1", journal_entry=None,
        )


@pytest.mark.asyncio
async def test_execute_trade_requires_journal_when_configured() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(factory, require_decision_journal=True)
    service = _make_service(factory)

    with pytest.raises(InvalidPortfolioStateError):
        await service.execute_trade(
            portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
            transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
            idempotency_key="key-1", journal_entry=None,
        )


@pytest.mark.asyncio
async def test_execute_trade_rejects_simulation_date_regression() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(
        factory, current_simulation_at=NOW + timedelta(days=10)
    )
    service = _make_service(factory)

    with pytest.raises(TradeRejectedError) as exc_info:
        await service.execute_trade(
            portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
            transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
            idempotency_key="key-1", journal_entry=None,
        )
    assert exc_info.value.reason == TradeRejectionReason.SIMULATION_DATE_REGRESSION


@pytest.mark.asyncio
async def test_rejected_trade_does_not_mutate_cash_or_holdings() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(factory, require_decision_journal=False)
    service = _make_service(factory)

    with pytest.raises(TradeRejectedError):
        await service.execute_trade(
            portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
            transaction_type=PortfolioTransactionType.BUY, quantity=100_000, requested_at=NOW,
            idempotency_key="key-1", journal_entry=None,
        )

    assert factory.virtual_portfolios.portfolios[portfolio.portfolio_id].cash_balance == 10_000.0
    assert not factory.portfolio_holdings.holdings


@pytest.mark.asyncio
async def test_execute_trade_with_journal_links_entry_to_transaction() -> None:
    from stock_research_core.domain.virtual_portfolio.enums import DecisionConfidence, PortfolioDecisionAction

    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(factory)
    service = _make_service(factory)
    journal_entry = PortfolioDecisionJournalEntry(
        portfolio_id=portfolio.portfolio_id, learner_id=uuid4(), action=PortfolioDecisionAction.BUY,
        decision_at=NOW, rationale="A sufficiently long rationale for this trade.",
        confidence=DecisionConfidence.MEDIUM,
    )

    result = await service.execute_trade(
        portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
        transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
        idempotency_key="key-1", journal_entry=journal_entry,
    )

    assert result.journal_entry is not None
    assert result.journal_entry.related_transaction_id == result.transaction.transaction_id
    assert result.journal_entry.learner_id == portfolio.learner_id


# ---------------------------------------------------------------------------
# record_non_trade_decision / overview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_non_trade_decision_rejects_buy_sell_actions() -> None:
    from stock_research_core.domain.virtual_portfolio.enums import DecisionConfidence, PortfolioDecisionAction

    factory = FakeUnitOfWorkFactory()
    portfolio, _security = await _seed_portfolio_and_security(factory)
    service = _make_service(factory)

    with pytest.raises(InvalidPortfolioStateError):
        await service.record_non_trade_decision(
            portfolio_id=portfolio.portfolio_id, security_id=None, action=PortfolioDecisionAction.BUY,
            decision_at=NOW, rationale="A sufficiently long rationale here.",
            expected_horizon_days=None, confidence=DecisionConfidence.LOW,
            risk_tags=[], information_considered=[], assumptions=[],
        )


@pytest.mark.asyncio
async def test_get_overview_assembles_portfolio_state() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed_portfolio_and_security(factory, require_decision_journal=False)
    service = _make_service(factory)
    await service.execute_trade(
        portfolio_id=portfolio.portfolio_id, ticker=security.ticker,
        transaction_type=PortfolioTransactionType.BUY, quantity=5, requested_at=NOW,
        idempotency_key="key-1", journal_entry=None,
    )

    overview = await service.get_overview(portfolio.portfolio_id)

    assert overview.portfolio.portfolio_id == portfolio.portfolio_id
    assert len(overview.holdings) == 1
    assert len(overview.recent_transactions) == 1


@pytest.mark.asyncio
async def test_get_overview_requires_existing_portfolio() -> None:
    factory = FakeUnitOfWorkFactory()
    service = _make_service(factory)
    with pytest.raises(VirtualPortfolioNotFoundError):
        await service.get_overview(uuid4())
