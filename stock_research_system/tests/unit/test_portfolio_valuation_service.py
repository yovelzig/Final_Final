"""Unit tests for `PortfolioValuationService`.

Uses fake in-memory repository implementations and a fake Unit of Work -
no SQLAlchemy or PostgreSQL is involved anywhere in this file. The real
`PandasPortfolioAnalytics` and `RuleBasedPortfolioFeedbackPolicy` are
used (not further fakes) so these tests also exercise the
service/policy integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.exceptions import PortfolioValuationError, VirtualPortfolioNotFoundError
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.enums import PortfolioValuationRunStatus
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioHolding,
    PortfolioPositionValuation,
    PortfolioRiskAssessment,
    PortfolioValuationRun,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import (
    PandasPortfolioAnalytics,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeSecurityRepository:
    def __init__(self) -> None:
        self.securities: dict[UUID, Security] = {}

    async def get_by_id(self, security_id: UUID):
        return self.securities.get(security_id)


class FakeMarketBarRepository:
    def __init__(self) -> None:
        self.bars: list[MarketBar] = []

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

    async def get(self, portfolio_id: UUID, *, for_update: bool = False):
        return self.portfolios.get(portfolio_id)


class FakePortfolioHoldingRepository:
    def __init__(self) -> None:
        self.holdings: dict[tuple[UUID, UUID], PortfolioHolding] = {}

    async def list_for_portfolio(self, portfolio_id, include_zero=False):
        values = [h for h in self.holdings.values() if h.portfolio_id == portfolio_id]
        if not include_zero:
            values = [h for h in values if h.quantity > 0]
        return values


class FakePortfolioJournalRepository:
    async def list_for_portfolio(self, portfolio_id, limit=10):
        return []


class FakePortfolioTransactionRepository:
    """Minimal fake: `value_portfolio` reads this when it auto-computes
    performance after a second snapshot exists in the window."""

    async def list_for_portfolio(self, portfolio_id, start_at=None, end_at=None):
        return []


class FakePortfolioValuationRepository:
    def __init__(self) -> None:
        self.snapshots: dict[tuple[UUID, datetime, str], PortfolioValuationSnapshot] = {}
        self.positions: dict[UUID, list[PortfolioPositionValuation]] = {}

    async def upsert_snapshot(self, snapshot: PortfolioValuationSnapshot) -> PortfolioValuationSnapshot:
        key = (snapshot.portfolio_id, snapshot.as_of, snapshot.valuation_version)
        existing = self.snapshots.get(key)
        stored = snapshot.model_copy(update={"snapshot_id": existing.snapshot_id}) if existing else snapshot
        self.snapshots[key] = stored
        return stored

    async def upsert_positions(self, positions):
        if not positions:
            return []
        snapshot_id = positions[0].snapshot_id
        self.positions[snapshot_id] = list(positions)
        return list(positions)

    async def get_latest(self, portfolio_id: UUID):
        values = [s for s in self.snapshots.values() if s.portfolio_id == portfolio_id]
        return max(values, key=lambda s: s.as_of) if values else None

    async def list_range(self, portfolio_id: UUID, start_at, end_at):
        values = [
            s for s in self.snapshots.values() if s.portfolio_id == portfolio_id and start_at <= s.as_of <= end_at
        ]
        return sorted(values, key=lambda s: s.as_of)

    async def list_positions(self, snapshot_id: UUID):
        return self.positions.get(snapshot_id, [])


class FakePortfolioRiskRepository:
    def __init__(self) -> None:
        self.assessments: dict[tuple[UUID, str], PortfolioRiskAssessment] = {}

    async def upsert(self, assessment: PortfolioRiskAssessment) -> PortfolioRiskAssessment:
        key = (assessment.snapshot_id, assessment.policy_version)
        self.assessments[key] = assessment
        return assessment

    async def get_latest(self, portfolio_id: UUID):
        values = [a for a in self.assessments.values() if a.portfolio_id == portfolio_id]
        return max(values, key=lambda a: a.calculated_at) if values else None


class FakePortfolioValuationRunRepository:
    def __init__(self) -> None:
        self.runs: dict[UUID, PortfolioValuationRun] = {}

    async def create_started(self, run: PortfolioValuationRun) -> PortfolioValuationRun:
        self.runs[run.run_id] = run
        return run

    async def mark_completed(self, run_id, *, completed_at, priced_holding_count, missing_price_count):
        updated = self.runs[run_id].model_copy(
            update={
                "status": PortfolioValuationRunStatus.COMPLETED, "completed_at": completed_at,
                "priced_holding_count": priced_holding_count, "missing_price_count": missing_price_count,
            }
        )
        self.runs[run_id] = updated
        return updated

    async def mark_failed(self, run_id, *, completed_at, error_type, error_message):
        updated = self.runs[run_id].model_copy(
            update={
                "status": PortfolioValuationRunStatus.FAILED, "completed_at": completed_at,
                "error_type": error_type, "error_message": error_message,
            }
        )
        self.runs[run_id] = updated
        return updated

    async def mark_no_price_data(self, run_id, *, completed_at, missing_price_count):
        updated = self.runs[run_id].model_copy(
            update={
                "status": PortfolioValuationRunStatus.NO_PRICE_DATA, "completed_at": completed_at,
                "missing_price_count": missing_price_count,
            }
        )
        self.runs[run_id] = updated
        return updated


class FakeUnitOfWork:
    def __init__(self, factory: "FakeUnitOfWorkFactory") -> None:
        self.securities = factory.securities
        self.market_bars = factory.market_bars
        self.virtual_portfolios = factory.virtual_portfolios
        self.portfolio_holdings = factory.portfolio_holdings
        self.portfolio_journal = factory.portfolio_journal
        self.portfolio_transactions = factory.portfolio_transactions
        self.portfolio_valuations = factory.portfolio_valuations
        self.portfolio_risk = factory.portfolio_risk
        self.portfolio_valuation_runs = factory.portfolio_valuation_runs

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class FakeUnitOfWorkFactory:
    def __init__(self) -> None:
        self.securities = FakeSecurityRepository()
        self.market_bars = FakeMarketBarRepository()
        self.virtual_portfolios = FakeVirtualPortfolioRepository()
        self.portfolio_holdings = FakePortfolioHoldingRepository()
        self.portfolio_journal = FakePortfolioJournalRepository()
        self.portfolio_transactions = FakePortfolioTransactionRepository()
        self.portfolio_valuations = FakePortfolioValuationRepository()
        self.portfolio_risk = FakePortfolioRiskRepository()
        self.portfolio_valuation_runs = FakePortfolioValuationRunRepository()
        self.instances: list[FakeUnitOfWork] = []

    def __call__(self) -> FakeUnitOfWork:
        uow = FakeUnitOfWork(self)
        self.instances.append(uow)
        return uow


def _make_valuation_service(factory: FakeUnitOfWorkFactory, clock=lambda: NOW) -> PortfolioValuationService:
    return PortfolioValuationService(
        unit_of_work_factory=factory,
        analytics=PandasPortfolioAnalytics(),
        feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
        clock=clock,
    )


def _portfolio(**overrides) -> VirtualPortfolio:
    defaults: dict = dict(
        learner_id=uuid4(), name="P", initial_cash=10_000.0, cash_balance=8_000.0,
        simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
    )
    defaults.update(overrides)
    return VirtualPortfolio(**defaults)


def _security(**overrides) -> Security:
    defaults = dict(ticker="NVDA", company_name="Nvidia", exchange=Exchange.NASDAQ, currency="USD")
    defaults.update(overrides)
    return Security(**defaults)


def _bar(security_id, day: int, price: float) -> MarketBar:
    return MarketBar(
        security_id=security_id, timestamp=NOW + timedelta(days=day), open=price, high=price + 1,
        low=price - 1, close=price, adjusted_close=price, volume=1000, source_name="test",
    )


async def _seed(factory: FakeUnitOfWorkFactory):
    portfolio = _portfolio()
    factory.virtual_portfolios.portfolios[portfolio.portfolio_id] = portfolio
    security = _security()
    factory.securities.securities[security.security_id] = security
    factory.market_bars.bars.append(_bar(security.security_id, 0, 100.0))
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=security.security_id, quantity=10,
        average_cost=90.0, cost_basis=900.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    factory.portfolio_holdings.holdings[(portfolio.portfolio_id, security.security_id)] = holding
    return portfolio, security


@pytest.mark.asyncio
async def test_value_portfolio_creates_completed_run() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, _security = await _seed(factory)
    service = _make_valuation_service(factory)

    result = await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW)

    assert result.run.status == PortfolioValuationRunStatus.COMPLETED
    assert result.snapshot.holdings_value == pytest.approx(1000.0)


@pytest.mark.asyncio
async def test_value_portfolio_requires_existing_portfolio() -> None:
    factory = FakeUnitOfWorkFactory()
    service = _make_valuation_service(factory)
    with pytest.raises(VirtualPortfolioNotFoundError):
        await service.value_portfolio(portfolio_id=uuid4(), as_of=NOW)


@pytest.mark.asyncio
async def test_value_portfolio_rejects_as_of_before_simulation_start() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, _security = await _seed(factory)
    service = _make_valuation_service(factory)

    with pytest.raises(PortfolioValuationError):
        await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW - timedelta(days=1))


@pytest.mark.asyncio
async def test_value_portfolio_is_idempotent_for_same_as_of() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, _security = await _seed(factory)
    service = _make_valuation_service(factory)

    first = await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW)
    second = await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW)

    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert len(factory.portfolio_valuations.snapshots) == 1


@pytest.mark.asyncio
async def test_value_portfolio_reports_missing_price_data() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio = _portfolio()
    factory.virtual_portfolios.portfolios[portfolio.portfolio_id] = portfolio
    unpriced_security_id = uuid4()
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=unpriced_security_id, quantity=10,
        average_cost=90.0, cost_basis=900.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    factory.portfolio_holdings.holdings[(portfolio.portfolio_id, unpriced_security_id)] = holding
    service = _make_valuation_service(factory)

    result = await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW)

    assert result.run.status == PortfolioValuationRunStatus.NO_PRICE_DATA
    from stock_research_core.domain.virtual_portfolio.enums import PortfolioFeedbackCode

    assert PortfolioFeedbackCode.MISSING_PRICE_DATA in result.risk_assessment.feedback_codes


@pytest.mark.asyncio
async def test_value_portfolio_never_uses_a_future_price() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio, security = await _seed(factory)
    # A much higher future price must not affect a valuation as of an earlier date.
    factory.market_bars.bars.append(_bar(security.security_id, 100, 999_999.0))
    service = _make_valuation_service(factory)

    result = await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW)

    assert result.snapshot.holdings_value == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# value_many
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_value_many_rejects_non_positive_concurrency() -> None:
    factory = FakeUnitOfWorkFactory()
    service = _make_valuation_service(factory)
    with pytest.raises(ValueError):
        await service.value_many(portfolio_ids=[uuid4()], as_of=NOW, max_concurrency=0)


@pytest.mark.asyncio
async def test_value_many_deduplicates_and_preserves_order() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio_a, _sec_a = await _seed(factory)
    portfolio_b = _portfolio()
    factory.virtual_portfolios.portfolios[portfolio_b.portfolio_id] = portfolio_b
    service = _make_valuation_service(factory)

    results = await service.value_many(
        portfolio_ids=[portfolio_a.portfolio_id, portfolio_b.portfolio_id, portfolio_a.portfolio_id],
        as_of=NOW,
    )

    assert [r.portfolio_id for r in results] == [portfolio_a.portfolio_id, portfolio_b.portfolio_id]


@pytest.mark.asyncio
async def test_value_many_one_failure_does_not_fail_others() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio_a, _sec_a = await _seed(factory)
    missing_portfolio_id = uuid4()
    service = _make_valuation_service(factory)

    results = await service.value_many(
        portfolio_ids=[portfolio_a.portfolio_id, missing_portfolio_id], as_of=NOW
    )

    ok_result = next(r for r in results if r.portfolio_id == portfolio_a.portfolio_id)
    failed_result = next(r for r in results if r.portfolio_id == missing_portfolio_id)
    assert ok_result.status == PortfolioValuationRunStatus.COMPLETED
    assert failed_result.status == PortfolioValuationRunStatus.FAILED
    assert failed_result.error_type is not None


@pytest.mark.asyncio
async def test_value_many_uses_independent_unit_of_work_per_portfolio() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio_a, _sec_a = await _seed(factory)
    portfolio_b = _portfolio()
    factory.virtual_portfolios.portfolios[portfolio_b.portfolio_id] = portfolio_b
    service = _make_valuation_service(factory)

    await service.value_many(portfolio_ids=[portfolio_a.portfolio_id, portfolio_b.portfolio_id], as_of=NOW)

    # Each `value_portfolio` call opens its own Unit of Work instance.
    assert len(factory.instances) >= 2


# ---------------------------------------------------------------------------
# calculate_performance - Phase 10 stabilization (insufficient valuation data)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calculate_performance_raises_controlled_error_with_no_snapshots() -> None:
    from stock_research_core.application.exceptions import InsufficientPortfolioValuationDataError

    factory = FakeUnitOfWorkFactory()
    portfolio = _portfolio()
    factory.virtual_portfolios.portfolios[portfolio.portfolio_id] = portfolio
    service = _make_valuation_service(factory)

    with pytest.raises(InsufficientPortfolioValuationDataError):
        await service.calculate_performance(
            portfolio_id=portfolio.portfolio_id, start_at=NOW, end_at=NOW + timedelta(days=30)
        )


@pytest.mark.asyncio
async def test_calculate_performance_raises_controlled_error_with_only_one_snapshot() -> None:
    from stock_research_core.application.exceptions import InsufficientPortfolioValuationDataError

    factory = FakeUnitOfWorkFactory()
    portfolio = _portfolio()
    factory.virtual_portfolios.portfolios[portfolio.portfolio_id] = portfolio
    service = _make_valuation_service(factory)

    # A single valuation performed, but performance needs a start *and* an end point.
    await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW)

    with pytest.raises(InsufficientPortfolioValuationDataError):
        await service.calculate_performance(
            portfolio_id=portfolio.portfolio_id, start_at=NOW, end_at=NOW + timedelta(days=30)
        )


@pytest.mark.asyncio
async def test_calculate_performance_succeeds_with_two_snapshots() -> None:
    factory = FakeUnitOfWorkFactory()
    portfolio = _portfolio()
    factory.virtual_portfolios.portfolios[portfolio.portfolio_id] = portfolio
    service = _make_valuation_service(factory)

    await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW)
    await service.value_portfolio(portfolio_id=portfolio.portfolio_id, as_of=NOW + timedelta(days=1))

    summary = await service.calculate_performance(
        portfolio_id=portfolio.portfolio_id, start_at=NOW, end_at=NOW + timedelta(days=30)
    )
    assert summary.portfolio_id == portfolio.portfolio_id
