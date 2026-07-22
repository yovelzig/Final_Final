"""Unit tests verifying `PortfolioValuationService.value_many` respects
bounded concurrency and never shares an AsyncSession-like object across
concurrent portfolio valuations.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.virtual_portfolio.analytics import PortfolioAnalyticsPort
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.virtual_portfolio.enums import PortfolioValuationRunStatus
from stock_research_core.domain.virtual_portfolio.models import PortfolioValuationRun, VirtualPortfolio

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _NoOpAnalytics:
    """A stand-in `PortfolioAnalyticsPort` that just sleeps briefly, so
    concurrency can be observed without needing real market data."""

    def __init__(self, delay_seconds: float = 0.02) -> None:
        self._delay_seconds = delay_seconds
        self.current_in_flight = 0
        self.max_observed_in_flight = 0

    async def calculate_snapshot(self, **kwargs):
        self.current_in_flight += 1
        self.max_observed_in_flight = max(self.max_observed_in_flight, self.current_in_flight)
        try:
            await asyncio.sleep(self._delay_seconds)
            portfolio = kwargs["portfolio"]
            from stock_research_core.domain.virtual_portfolio.models import PortfolioValuationSnapshot

            snapshot = PortfolioValuationSnapshot(
                portfolio_id=portfolio.portfolio_id, as_of=kwargs["as_of"], data_cutoff_at=kwargs["as_of"],
                cash_balance=portfolio.cash_balance, holdings_value=0.0, total_value=portfolio.cash_balance,
                total_cost_basis=0.0, realized_pnl=0.0, unrealized_pnl=0.0, net_profit=0.0, total_return=0.0,
                largest_position_weight=0.0, cash_weight=1.0, position_count=0, portfolio_hhi=0.0,
                diversification_score=0.0, valuation_version="portfolio-valuation-v1",
            )
            return snapshot, []
        finally:
            self.current_in_flight -= 1

    async def calculate_performance(self, **kwargs):
        raise NotImplementedError


class FakeVirtualPortfolioRepository:
    def __init__(self, portfolios: dict) -> None:
        self._portfolios = portfolios

    async def get(self, portfolio_id, *, for_update: bool = False):
        return self._portfolios.get(portfolio_id)


class FakeHoldingRepository:
    async def list_for_portfolio(self, portfolio_id, include_zero=False):
        return []


class FakeJournalRepository:
    async def list_for_portfolio(self, portfolio_id, limit=10):
        return []


class FakeValuationRepository:
    async def upsert_snapshot(self, snapshot):
        return snapshot

    async def upsert_positions(self, positions):
        return list(positions)

    async def list_range(self, portfolio_id, start_at, end_at):
        return []


class FakeRiskRepository:
    async def upsert(self, assessment):
        return assessment


class FakeValuationRunRepository:
    async def create_started(self, run: PortfolioValuationRun) -> PortfolioValuationRun:
        return run

    async def mark_completed(self, run_id, *, completed_at, priced_holding_count, missing_price_count):
        return PortfolioValuationRun(
            run_id=run_id, portfolio_id=uuid4(), status=PortfolioValuationRunStatus.COMPLETED,
            requested_as_of=NOW, valuation_version="portfolio-valuation-v1",
            risk_policy_version="portfolio-feedback-v1", holding_count=0, priced_holding_count=0,
            missing_price_count=0, completed_at=completed_at,
        )

    async def mark_failed(self, run_id, *, completed_at, error_type, error_message):
        raise AssertionError("not expected in this test")

    async def mark_no_price_data(self, run_id, *, completed_at, missing_price_count):
        raise AssertionError("not expected in this test")


class FakeSecurityRepository:
    async def get_by_id(self, security_id):
        return None


class FakeMarketBarRepository:
    async def get_latest_bar_at_or_before(self, *args, **kwargs):
        return None

    async def list_range(self, *args, **kwargs):
        return []


class FakeUnitOfWork:
    """Each instance is a distinct, independent object - never shared
    across concurrent `value_portfolio` calls (verified by identity)."""

    _instance_counter = 0

    def __init__(self, portfolios: dict) -> None:
        FakeUnitOfWork._instance_counter += 1
        self.instance_id = FakeUnitOfWork._instance_counter
        self.virtual_portfolios = FakeVirtualPortfolioRepository(portfolios)
        self.portfolio_holdings = FakeHoldingRepository()
        self.portfolio_journal = FakeJournalRepository()
        self.portfolio_valuations = FakeValuationRepository()
        self.portfolio_risk = FakeRiskRepository()
        self.portfolio_valuation_runs = FakeValuationRunRepository()
        self.securities = FakeSecurityRepository()
        self.market_bars = FakeMarketBarRepository()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


def _portfolio() -> VirtualPortfolio:
    return VirtualPortfolio(
        learner_id=uuid4(), name="P", initial_cash=1000.0, cash_balance=1000.0,
        simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
    )


@pytest.mark.asyncio
async def test_value_many_respects_max_concurrency() -> None:
    portfolios = {}
    for _ in range(6):
        p = _portfolio()
        portfolios[p.portfolio_id] = p

    seen_instance_ids: set[int] = set()

    def factory():
        uow = FakeUnitOfWork(portfolios)
        seen_instance_ids.add(uow.instance_id)
        return uow

    analytics = _NoOpAnalytics(delay_seconds=0.03)
    service = PortfolioValuationService(
        unit_of_work_factory=factory, analytics=analytics, feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
    )

    results = await service.value_many(portfolio_ids=list(portfolios.keys()), as_of=NOW, max_concurrency=2)

    assert len(results) == 6
    assert analytics.max_observed_in_flight <= 2
    # Every portfolio got its own Unit of Work instance - none shared.
    assert len(seen_instance_ids) == 6


@pytest.mark.asyncio
async def test_value_many_with_high_concurrency_limit_runs_more_in_parallel() -> None:
    portfolios = {}
    for _ in range(4):
        p = _portfolio()
        portfolios[p.portfolio_id] = p

    def factory():
        return FakeUnitOfWork(portfolios)

    analytics = _NoOpAnalytics(delay_seconds=0.03)
    service = PortfolioValuationService(
        unit_of_work_factory=factory, analytics=analytics, feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
    )

    await service.value_many(portfolio_ids=list(portfolios.keys()), as_of=NOW, max_concurrency=4)

    assert analytics.max_observed_in_flight == 4
