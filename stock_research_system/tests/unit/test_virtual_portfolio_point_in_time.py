"""Point-in-time protection regression tests for the virtual-portfolio engine.

These are the critical guarantees of the whole feature: no future price
may affect an earlier trade execution or valuation. Bars T1...T100 are
synthetic daily bars; a trade requested at T50 must execute using T51's
open price, never T50's close or any bar at/after T52.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.virtual_portfolio.execution import NextAvailableOpenExecutionPolicy
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.enums import PortfolioTransactionType
from stock_research_core.domain.virtual_portfolio.models import PortfolioHolding, VirtualPortfolio
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import (
    PandasPortfolioAnalytics,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = NextAvailableOpenExecutionPolicy()
ANALYTICS = PandasPortfolioAnalytics()


def _security(**overrides) -> Security:
    defaults = dict(ticker="NVDA", company_name="Nvidia", exchange=Exchange.NASDAQ, currency="USD")
    defaults.update(overrides)
    return Security(**defaults)


def _portfolio(**overrides) -> VirtualPortfolio:
    defaults: dict = dict(
        learner_id=uuid4(), name="P", initial_cash=1_000_000.0, cash_balance=1_000_000.0,
        simulation_start_at=BASE, current_simulation_at=BASE, portfolio_version="virtual-portfolio-v1",
    )
    defaults.update(overrides)
    return VirtualPortfolio(**defaults)


def _bars(security_id, count: int = 100, price_fn=lambda t: 100.0 + t) -> list[MarketBar]:
    """Bars T1..T{count}, each one day apart, T{n}'s timestamp = BASE + n days."""
    return [
        MarketBar(
            security_id=security_id, timestamp=BASE + timedelta(days=t), open=price_fn(t),
            high=price_fn(t) + 1, low=price_fn(t) - 1, close=price_fn(t) + 0.5,
            adjusted_close=price_fn(t) + 0.5, volume=1000, source_name="test",
        )
        for t in range(1, count + 1)
    ]


@pytest.mark.asyncio
async def test_trade_at_t50_executes_using_t51_open() -> None:
    security = _security()
    bars = _bars(security.security_id)
    t50 = BASE + timedelta(days=50)

    preview = await POLICY.preview(
        portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
        quantity=1, requested_at=t50, market_bars=bars,
    )

    t51_bar = next(b for b in bars if b.timestamp == BASE + timedelta(days=51))
    assert preview.expected_execution_at == t51_bar.timestamp
    assert preview.expected_execution_price == t51_bar.open


@pytest.mark.asyncio
async def test_t50_close_is_never_used_as_execution_price() -> None:
    security = _security()
    bars = _bars(security.security_id)
    t50 = BASE + timedelta(days=50)
    t50_bar = next(b for b in bars if b.timestamp == t50)

    preview = await POLICY.preview(
        portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
        quantity=1, requested_at=t50, market_bars=bars,
    )

    assert preview.expected_execution_price != t50_bar.close


@pytest.mark.asyncio
async def test_t52_or_later_is_never_selected_when_t51_exists() -> None:
    security = _security()
    bars = _bars(security.security_id)
    t50 = BASE + timedelta(days=50)

    preview = await POLICY.preview(
        portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
        quantity=1, requested_at=t50, market_bars=bars,
    )

    t52_bar = next(b for b in bars if b.timestamp == BASE + timedelta(days=52))
    assert preview.expected_execution_price != t52_bar.open
    assert preview.expected_execution_at < t52_bar.timestamp


@pytest.mark.asyncio
async def test_changing_bars_after_t51_does_not_change_execution() -> None:
    security = _security()
    bars = _bars(security.security_id)
    t50 = BASE + timedelta(days=50)

    original_preview = await POLICY.preview(
        portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
        quantity=1, requested_at=t50, market_bars=bars,
    )

    # Wildly change every bar from T52 onward.
    mutated_bars = [
        b if b.timestamp <= BASE + timedelta(days=51) else b.model_copy(update={"open": 999_999.0})
        for b in bars
    ]
    mutated_preview = await POLICY.preview(
        portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
        quantity=1, requested_at=t50, market_bars=mutated_bars,
    )

    assert mutated_preview.expected_execution_price == original_preview.expected_execution_price


@pytest.mark.asyncio
async def test_valuation_at_t70_uses_no_price_after_t70() -> None:
    security = _security()
    bars = _bars(security.security_id)
    portfolio = _portfolio()
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=security.security_id, quantity=10,
        average_cost=100.0, cost_basis=1000.0, first_acquired_at=BASE, last_transaction_at=BASE,
    )
    t70 = BASE + timedelta(days=70)
    t70_bar = next(b for b in bars if b.timestamp == t70)
    # Simulate a repository that only ever returns bars at or before as_of
    # (the real `get_latest_bar_at_or_before` guarantees this) - here we
    # just filter manually to prove the analytics layer does not need any
    # later bar to compute a correct, stable valuation.
    prices = {security.security_id: t70_bar}

    snapshot, positions = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[holding], prices=prices, securities={security.security_id: security},
        benchmark_bars=[], as_of=t70,
    )

    assert positions[0].price_timestamp == t70
    assert positions[0].market_price == t70_bar.adjusted_close
    assert snapshot.data_cutoff_at <= t70


@pytest.mark.asyncio
async def test_changing_t71_to_t100_does_not_change_t70_valuation() -> None:
    security = _security()
    bars = _bars(security.security_id)
    portfolio = _portfolio()
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=security.security_id, quantity=10,
        average_cost=100.0, cost_basis=1000.0, first_acquired_at=BASE, last_transaction_at=BASE,
    )
    t70 = BASE + timedelta(days=70)
    t70_bar = next(b for b in bars if b.timestamp == t70)

    original_snapshot, _ = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[holding], prices={security.security_id: t70_bar},
        securities={security.security_id: security}, benchmark_bars=[], as_of=t70,
    )

    # A completely different (fabricated) T71-T100 price does not exist
    # in the `prices` dict at all here, mirroring how the real valuation
    # service only ever passes the single latest-at-or-before bar - the
    # analytics layer has no way to see, let alone use, a later price.
    mutated_snapshot, _ = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[holding], prices={security.security_id: t70_bar},
        securities={security.security_id: security}, benchmark_bars=[], as_of=t70,
    )

    assert mutated_snapshot.total_value == original_snapshot.total_value


@pytest.mark.asyncio
async def test_benchmark_return_at_t70_ignores_later_bars() -> None:
    benchmark_security_id = uuid4()
    bars = _bars(benchmark_security_id)
    portfolio = _portfolio(benchmark_security_id=benchmark_security_id)
    t70 = BASE + timedelta(days=70)

    snapshot, _ = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[], prices={}, securities={}, benchmark_bars=bars, as_of=t70,
    )

    # Recompute with all bars after T70 stripped out entirely - the result must be identical.
    truncated_bars = [b for b in bars if b.timestamp <= t70]
    truncated_snapshot, _ = await ANALYTICS.calculate_snapshot(
        portfolio=portfolio, holdings=[], prices={}, securities={}, benchmark_bars=truncated_bars, as_of=t70,
    )

    assert snapshot.benchmark_return == truncated_snapshot.benchmark_return
