"""Unit tests for `NextAvailableOpenExecutionPolicy` (next-available-open-v1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import TradeRejectedError
from stock_research_core.application.virtual_portfolio.execution import NextAvailableOpenExecutionPolicy
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.enums import PortfolioTransactionType, TradeRejectionReason
from stock_research_core.domain.virtual_portfolio.models import PortfolioHolding, VirtualPortfolio

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = NextAvailableOpenExecutionPolicy()


def _portfolio(**overrides: object) -> VirtualPortfolio:
    defaults: dict = dict(
        learner_id=uuid4(),
        name="P",
        initial_cash=10_000.0,
        cash_balance=10_000.0,
        simulation_start_at=NOW,
        current_simulation_at=NOW,
        portfolio_version="virtual-portfolio-v1",
    )
    defaults.update(overrides)
    return VirtualPortfolio(**defaults)


def _security(**overrides: object) -> Security:
    defaults: dict = dict(ticker="NVDA", company_name="Nvidia", exchange=Exchange.NASDAQ, currency="USD")
    defaults.update(overrides)
    return Security(**defaults)


def _bar(security_id, day: int, open_price: float = 100.0) -> MarketBar:
    return MarketBar(
        security_id=security_id,
        timestamp=NOW + timedelta(days=day),
        open=open_price,
        high=open_price + 5,
        low=open_price - 5,
        close=open_price + 1,
        adjusted_close=open_price + 1,
        volume=1000,
        source_name="test",
    )


def test_policy_version_is_stable() -> None:
    assert POLICY.execution_rule_version == "next-available-open-v1"


@pytest.mark.asyncio
async def test_executes_at_first_bar_strictly_after_request() -> None:
    security = _security()
    same_day_bar = _bar(security.security_id, 0, open_price=999.0)  # not strictly after
    next_bar = _bar(security.security_id, 1, open_price=105.0)
    later_bar = _bar(security.security_id, 2, open_price=110.0)

    preview = await POLICY.preview(
        portfolio=_portfolio(),
        security=security,
        holdings=[],
        transaction_type=PortfolioTransactionType.BUY,
        quantity=5,
        requested_at=NOW,
        market_bars=[later_bar, next_bar, same_day_bar],
    )

    assert preview.expected_execution_price == 105.0
    assert preview.expected_execution_at == next_bar.timestamp


@pytest.mark.asyncio
async def test_rejects_when_no_bar_strictly_after_request() -> None:
    security = _security()
    same_day_bar = _bar(security.security_id, 0)

    with pytest.raises(TradeRejectedError) as exc_info:
        await POLICY.preview(
            portfolio=_portfolio(),
            security=security,
            holdings=[],
            transaction_type=PortfolioTransactionType.BUY,
            quantity=5,
            requested_at=NOW,
            market_bars=[same_day_bar],
        )
    assert exc_info.value.reason == TradeRejectionReason.NO_EXECUTION_PRICE


@pytest.mark.asyncio
async def test_buy_fee_formula() -> None:
    security = _security()
    bar = _bar(security.security_id, 1, open_price=100.0)
    portfolio = _portfolio(fixed_transaction_fee=1.0, transaction_fee_bps=50.0)  # 0.50%

    preview = await POLICY.preview(
        portfolio=portfolio, security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
        quantity=10, requested_at=NOW, market_bars=[bar],
    )

    gross_amount = 1000.0
    expected_fee = 1.0 + gross_amount * 50.0 / 10_000
    assert preview.estimated_fee == pytest.approx(expected_fee)
    assert preview.estimated_cash_effect == pytest.approx(-(gross_amount + expected_fee))


@pytest.mark.asyncio
async def test_sell_fee_formula() -> None:
    security = _security()
    bar = _bar(security.security_id, 1, open_price=100.0)
    portfolio = _portfolio(fixed_transaction_fee=1.0, transaction_fee_bps=50.0)
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=security.security_id, quantity=10,
        average_cost=80.0, cost_basis=800.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )

    preview = await POLICY.preview(
        portfolio=portfolio, security=security, holdings=[holding], transaction_type=PortfolioTransactionType.SELL,
        quantity=10, requested_at=NOW, market_bars=[bar],
    )

    gross_amount = 1000.0
    expected_fee = 1.0 + gross_amount * 50.0 / 10_000
    assert preview.estimated_cash_effect == pytest.approx(gross_amount - expected_fee)


@pytest.mark.asyncio
async def test_rejects_insufficient_cash() -> None:
    security = _security()
    bar = _bar(security.security_id, 1, open_price=10_000.0)
    portfolio = _portfolio(initial_cash=100.0, cash_balance=100.0)

    with pytest.raises(TradeRejectedError) as exc_info:
        await POLICY.preview(
            portfolio=portfolio, security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
            quantity=5, requested_at=NOW, market_bars=[bar],
        )
    assert exc_info.value.reason == TradeRejectionReason.INSUFFICIENT_CASH


@pytest.mark.asyncio
async def test_rejects_insufficient_quantity_on_sell() -> None:
    security = _security()
    bar = _bar(security.security_id, 1)
    portfolio = _portfolio()
    holding = PortfolioHolding(
        portfolio_id=portfolio.portfolio_id, security_id=security.security_id, quantity=2,
        average_cost=80.0, cost_basis=160.0, first_acquired_at=NOW, last_transaction_at=NOW,
    )

    with pytest.raises(TradeRejectedError) as exc_info:
        await POLICY.preview(
            portfolio=portfolio, security=security, holdings=[holding], transaction_type=PortfolioTransactionType.SELL,
            quantity=10, requested_at=NOW, market_bars=[bar],
        )
    assert exc_info.value.reason == TradeRejectionReason.INSUFFICIENT_QUANTITY


@pytest.mark.asyncio
async def test_rejects_invalid_quantity() -> None:
    security = _security()
    bar = _bar(security.security_id, 1)
    with pytest.raises(TradeRejectedError) as exc_info:
        await POLICY.preview(
            portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
            quantity=0, requested_at=NOW, market_bars=[bar],
        )
    assert exc_info.value.reason == TradeRejectionReason.INVALID_QUANTITY


@pytest.mark.asyncio
async def test_rejects_fractional_shares_when_disabled() -> None:
    security = _security()
    bar = _bar(security.security_id, 1)
    portfolio = _portfolio(allow_fractional_shares=False)
    with pytest.raises(TradeRejectedError) as exc_info:
        await POLICY.preview(
            portfolio=portfolio, security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
            quantity=1.5, requested_at=NOW, market_bars=[bar],
        )
    assert exc_info.value.reason == TradeRejectionReason.FRACTIONAL_SHARES_DISABLED


@pytest.mark.asyncio
async def test_rejects_currency_mismatch() -> None:
    security = _security(currency="EUR")
    bar = _bar(security.security_id, 1)
    with pytest.raises(TradeRejectedError) as exc_info:
        await POLICY.preview(
            portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
            quantity=1, requested_at=NOW, market_bars=[bar],
        )
    assert exc_info.value.reason == TradeRejectionReason.CURRENCY_MISMATCH


@pytest.mark.asyncio
async def test_rejects_inactive_security() -> None:
    security = _security(active=False)
    bar = _bar(security.security_id, 1)
    with pytest.raises(TradeRejectedError) as exc_info:
        await POLICY.preview(
            portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
            quantity=1, requested_at=NOW, market_bars=[bar],
        )
    assert exc_info.value.reason == TradeRejectionReason.SECURITY_NOT_ACTIVE


@pytest.mark.asyncio
async def test_execution_is_deterministic() -> None:
    security = _security()
    bar = _bar(security.security_id, 1, open_price=105.0)
    kwargs = dict(
        portfolio=_portfolio(), security=security, holdings=[], transaction_type=PortfolioTransactionType.BUY,
        quantity=5, requested_at=NOW, market_bars=[bar],
    )
    first = await POLICY.preview(**kwargs)
    second = await POLICY.preview(**kwargs)
    assert first.expected_execution_price == second.expected_execution_price
    assert first.gross_amount == second.gross_amount
