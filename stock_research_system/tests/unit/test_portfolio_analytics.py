"""Unit tests for `PandasPortfolioAnalytics` (portfolio-valuation-v1 / portfolio-performance-v1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.enums import (
    PortfolioTransactionStatus,
    PortfolioTransactionType,
)
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioHolding,
    PortfolioTransaction,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import (
    PandasPortfolioAnalytics,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ANALYTICS = PandasPortfolioAnalytics()


def _portfolio(**overrides: object) -> VirtualPortfolio:
    defaults: dict = dict(
        learner_id=uuid4(), name="P", initial_cash=10_000.0, cash_balance=5_000.0,
        simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
    )
    defaults.update(overrides)
    return VirtualPortfolio(**defaults)


def _security(sector: str | None = "Technology") -> Security:
    return Security(ticker="NVDA", company_name="Nvidia", exchange=Exchange.NASDAQ, currency="USD", sector=sector)


def _holding(security_id, quantity=10.0, average_cost=100.0) -> PortfolioHolding:
    return PortfolioHolding(
        portfolio_id=uuid4(), security_id=security_id, quantity=quantity, average_cost=average_cost,
        cost_basis=quantity * average_cost, first_acquired_at=NOW, last_transaction_at=NOW,
    )


def _bar(security_id, price: float, day: int = 0) -> MarketBar:
    return MarketBar(
        security_id=security_id, timestamp=NOW + timedelta(days=day), open=price, high=price + 1,
        low=price - 1, close=price, adjusted_close=price, volume=1000, source_name="test",
    )


@pytest.mark.asyncio
async def test_calculate_snapshot_computes_market_value_and_unrealized_pnl() -> None:
    security = _security()
    holding = _holding(security.security_id, quantity=10, average_cost=100.0)
    portfolio = _portfolio(cash_balance=5000.0)
    bar = _bar(security.security_id, price=120.0)

    snapshot, positions = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[holding], prices={security.security_id: bar},
        securities={security.security_id: security}, benchmark_bars=[], as_of=NOW,
    )

    assert len(positions) == 1
    assert positions[0].market_value == pytest.approx(1200.0)
    assert positions[0].unrealized_pnl == pytest.approx(200.0)
    assert snapshot.holdings_value == pytest.approx(1200.0)
    assert snapshot.total_value == pytest.approx(6200.0)


@pytest.mark.asyncio
async def test_calculate_snapshot_computes_weights_and_hhi() -> None:
    security_a, security_b = _security(), _security()
    holding_a = _holding(security_a.security_id, quantity=10, average_cost=100.0)
    holding_b = _holding(security_b.security_id, quantity=10, average_cost=100.0)
    portfolio = _portfolio(cash_balance=0.0)
    bar_a = _bar(security_a.security_id, price=100.0)
    bar_b = _bar(security_b.security_id, price=100.0)

    snapshot, positions = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[holding_a, holding_b],
        prices={security_a.security_id: bar_a, security_b.security_id: bar_b},
        securities={security_a.security_id: security_a, security_b.security_id: security_b},
        benchmark_bars=[], as_of=NOW,
    )

    # Equal-weighted 2-position portfolio: HHI = 0.5^2 + 0.5^2 = 0.5
    assert snapshot.portfolio_hhi == pytest.approx(0.5)
    assert snapshot.largest_position_weight == pytest.approx(0.5)
    assert snapshot.position_count == 2


@pytest.mark.asyncio
async def test_missing_sector_data_reallocates_to_position_component() -> None:
    security = _security(sector=None)
    holding = _holding(security.security_id)
    portfolio = _portfolio()
    bar = _bar(security.security_id, price=100.0)

    snapshot, positions = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[holding], prices={security.security_id: bar},
        securities={security.security_id: security}, benchmark_bars=[], as_of=NOW,
    )

    assert positions[0].sector is None
    assert snapshot.sector_hhi is None
    assert snapshot.largest_sector_weight is None
    # Still produces a valid diversification score (position + holding-count components only).
    assert 0.0 <= snapshot.diversification_score <= 1.0


@pytest.mark.asyncio
async def test_realized_pnl_is_summed_across_all_holdings_including_zero_quantity() -> None:
    security = _security()
    open_holding = _holding(security.security_id, quantity=5, average_cost=100.0)
    closed_holding = PortfolioHolding(
        portfolio_id=uuid4(), security_id=uuid4(), quantity=0.0, average_cost=0.0, cost_basis=0.0,
        realized_pnl=250.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )
    portfolio = _portfolio()
    bar = _bar(security.security_id, price=100.0)

    snapshot, _positions = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[open_holding, closed_holding], prices={security.security_id: bar},
        securities={security.security_id: security}, benchmark_bars=[], as_of=NOW,
    )

    assert snapshot.realized_pnl == pytest.approx(250.0)


@pytest.mark.asyncio
async def test_benchmark_return_uses_only_bars_up_to_as_of() -> None:
    benchmark_security_id = uuid4()
    portfolio = _portfolio(benchmark_security_id=benchmark_security_id)
    benchmark_bars = [
        _bar(benchmark_security_id, price=100.0, day=0),
        _bar(benchmark_security_id, price=110.0, day=1),
        _bar(benchmark_security_id, price=200.0, day=5),  # after as_of, must be ignored
    ]

    snapshot, _positions = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[], prices={}, securities={},
        benchmark_bars=benchmark_bars, as_of=NOW + timedelta(days=1),
    )

    assert snapshot.benchmark_return == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_calculate_performance_computes_drawdown_and_turnover() -> None:
    portfolio = _portfolio()
    snapshots = [
        PortfolioValuationSnapshot(
            portfolio_id=portfolio.portfolio_id, as_of=NOW, data_cutoff_at=NOW,
            cash_balance=10000, holdings_value=0, total_value=10000, total_cost_basis=0,
            realized_pnl=0, unrealized_pnl=0, net_profit=0, total_return=0.0,
            largest_position_weight=0.0, cash_weight=1.0, position_count=0,
            portfolio_hhi=0.0, diversification_score=0.0, valuation_version="portfolio-valuation-v1",
        ),
        PortfolioValuationSnapshot(
            portfolio_id=portfolio.portfolio_id, as_of=NOW + timedelta(days=1), data_cutoff_at=NOW,
            cash_balance=8000, holdings_value=1000, total_value=9000, total_cost_basis=1000,
            realized_pnl=0, unrealized_pnl=0, net_profit=0, total_return=-0.10,
            largest_position_weight=0.11, cash_weight=0.89, position_count=1,
            portfolio_hhi=0.01, diversification_score=0.5, valuation_version="portfolio-valuation-v1",
        ),
        PortfolioValuationSnapshot(
            portfolio_id=portfolio.portfolio_id, as_of=NOW + timedelta(days=2), data_cutoff_at=NOW,
            cash_balance=8000, holdings_value=1500, total_value=9500, total_cost_basis=1000,
            realized_pnl=0, unrealized_pnl=500, net_profit=500, total_return=-0.05,
            largest_position_weight=0.16, cash_weight=0.84, position_count=1,
            portfolio_hhi=0.02, diversification_score=0.5, valuation_version="portfolio-valuation-v1",
        ),
    ]
    transactions = [
        PortfolioTransaction(
            portfolio_id=portfolio.portfolio_id, security_id=uuid4(), transaction_type=PortfolioTransactionType.BUY,
            status=PortfolioTransactionStatus.EXECUTED, requested_at=NOW, executed_at=NOW + timedelta(days=1),
            requested_quantity=10, executed_quantity=10, execution_price=100.0, gross_amount=1000.0,
            fee_amount=0.0, net_cash_effect=-1000.0, source_name="s", interval="1d",
            execution_rule_version="next-available-open-v1", idempotency_key="k1",
        )
    ]

    summary = await ANALYTICS.calculate_performance(
        portfolio=portfolio, snapshots=snapshots, transactions=transactions,
        start_at=NOW, end_at=NOW + timedelta(days=2),
    )

    assert summary.start_value == pytest.approx(10000.0)
    assert summary.end_value == pytest.approx(9500.0)
    assert summary.maximum_drawdown < 0
    assert summary.turnover_ratio > 0


@pytest.mark.asyncio
async def test_calculate_performance_ignores_snapshots_outside_window() -> None:
    portfolio = _portfolio()
    in_window_start = PortfolioValuationSnapshot(
        portfolio_id=portfolio.portfolio_id, as_of=NOW, data_cutoff_at=NOW,
        cash_balance=10000, holdings_value=0, total_value=10000, total_cost_basis=0,
        realized_pnl=0, unrealized_pnl=0, net_profit=0, total_return=0.0,
        largest_position_weight=0.0, cash_weight=1.0, position_count=0,
        portfolio_hhi=0.0, diversification_score=0.0, valuation_version="portfolio-valuation-v1",
    )
    in_window_end = PortfolioValuationSnapshot(
        portfolio_id=portfolio.portfolio_id, as_of=NOW + timedelta(minutes=30), data_cutoff_at=NOW,
        cash_balance=10000, holdings_value=0, total_value=10000, total_cost_basis=0,
        realized_pnl=0, unrealized_pnl=0, net_profit=0, total_return=0.0,
        largest_position_weight=0.0, cash_weight=1.0, position_count=0,
        portfolio_hhi=0.0, diversification_score=0.0, valuation_version="portfolio-valuation-v1",
    )
    future_snapshot_causing_huge_drop = PortfolioValuationSnapshot(
        portfolio_id=portfolio.portfolio_id, as_of=NOW + timedelta(days=100), data_cutoff_at=NOW,
        cash_balance=1, holdings_value=0, total_value=1, total_cost_basis=0,
        realized_pnl=0, unrealized_pnl=0, net_profit=0, total_return=-0.9999,
        largest_position_weight=0.0, cash_weight=1.0, position_count=0,
        portfolio_hhi=0.0, diversification_score=0.0, valuation_version="portfolio-valuation-v1",
    )

    summary = await ANALYTICS.calculate_performance(
        portfolio=portfolio, snapshots=[in_window_start, in_window_end, future_snapshot_causing_huge_drop],
        transactions=[], start_at=NOW, end_at=NOW + timedelta(hours=1),
    )

    # Only the two in-window snapshots should be used - end_value must not
    # reflect the catastrophic future snapshot.
    assert summary.end_value == pytest.approx(10000.0)


@pytest.mark.asyncio
async def test_calculate_performance_raises_when_no_snapshots_in_window() -> None:
    from stock_research_core.application.exceptions import InsufficientPortfolioValuationDataError

    portfolio = _portfolio()
    with pytest.raises(InsufficientPortfolioValuationDataError, match="At least two portfolio valuations"):
        await ANALYTICS.calculate_performance(
            portfolio=portfolio, snapshots=[], transactions=[], start_at=NOW, end_at=NOW + timedelta(days=1),
        )


@pytest.mark.asyncio
async def test_calculate_performance_raises_when_only_one_snapshot_in_window() -> None:
    from stock_research_core.application.exceptions import InsufficientPortfolioValuationDataError

    portfolio = _portfolio()
    single_snapshot = PortfolioValuationSnapshot(
        portfolio_id=portfolio.portfolio_id, as_of=NOW, data_cutoff_at=NOW,
        cash_balance=10000, holdings_value=0, total_value=10000, total_cost_basis=0,
        realized_pnl=0, unrealized_pnl=0, net_profit=0, total_return=0.0,
        largest_position_weight=0.0, cash_weight=1.0, position_count=0,
        portfolio_hhi=0.0, diversification_score=0.0, valuation_version="portfolio-valuation-v1",
    )
    with pytest.raises(InsufficientPortfolioValuationDataError):
        await ANALYTICS.calculate_performance(
            portfolio=portfolio, snapshots=[single_snapshot], transactions=[],
            start_at=NOW, end_at=NOW + timedelta(days=1),
        )
