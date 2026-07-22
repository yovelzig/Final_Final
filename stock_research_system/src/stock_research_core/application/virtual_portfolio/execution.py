"""Deterministic, versioned trade-execution and portfolio-accounting policies.

No machine learning, no LLM calls, no randomness. Each policy
implements one of the Protocols below so a future policy (e.g. a
different fee schedule or a different lot-accounting method) can be
substituted without touching `VirtualPortfolioService`.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.application.exceptions import TradeRejectedError
from stock_research_core.application.virtual_portfolio.models import TradePreview
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.enums import PortfolioTransactionType, TradeRejectionReason
from stock_research_core.domain.virtual_portfolio.models import PortfolioHolding, VirtualPortfolio

#: `next-available-open-v1`: a trade executes at the OPEN price of the
#: first stored daily bar whose timestamp is strictly later than
#: `requested_at`. This strict boundary prevents any use of same-day or
#: past prices, and prevents "cherry-picking" a favorable future price.
EXECUTION_RULE_VERSION = "next-available-open-v1"

#: `average-cost-accounting-v1`: a single weighted-average-cost lot per
#: (portfolio, security) - no individual tax lots, no FIFO/LIFO choice.
ACCOUNTING_VERSION = "average-cost-accounting-v1"

_QUANTITY_EPSILON = 1e-9


def _calculate_fee(*, fixed_transaction_fee: float, transaction_fee_bps: float, gross_amount: float) -> float:
    """fee = fixed_transaction_fee + gross_amount * transaction_fee_bps / 10,000."""
    return fixed_transaction_fee + gross_amount * transaction_fee_bps / 10_000


class TradeExecutionPolicyPort(Protocol):
    """Decides at what price/time a requested trade would execute."""

    execution_rule_version: str

    async def preview(
        self,
        *,
        portfolio: VirtualPortfolio,
        security: Security,
        holdings: list[PortfolioHolding],
        transaction_type: PortfolioTransactionType,
        quantity: float,
        requested_at: datetime,
        market_bars: list[MarketBar],
    ) -> TradePreview: ...


class PortfolioAccountingPolicyPort(Protocol):
    """Applies an executed trade to cash and holding state."""

    accounting_version: str

    def calculate_fee(self, *, portfolio: VirtualPortfolio, gross_amount: float) -> float: ...

    def apply_buy(
        self,
        *,
        holding: PortfolioHolding | None,
        portfolio_id: UUID,
        security_id: UUID,
        quantity: float,
        execution_price: float,
        fee: float,
        executed_at: datetime,
    ) -> PortfolioHolding: ...

    def apply_sell(
        self,
        *,
        holding: PortfolioHolding,
        quantity: float,
        execution_price: float,
        fee: float,
        executed_at: datetime,
    ) -> tuple[PortfolioHolding, float]:
        """Returns `(updated_holding, realized_pnl)` for the sold quantity."""
        ...


class NextAvailableOpenExecutionPolicy:
    """next-available-open-v1: deterministic, point-in-time-safe trade preview.

    Never uses a close price from the request date, never uses a bar
    before the request, never interpolates a missing trading day, and
    never calls a market-data provider - `market_bars` must already be
    loaded by the caller (typically just the single next eligible bar,
    fetched via `MarketBarRepositoryPort.get_next_bar_after`).
    """

    execution_rule_version = EXECUTION_RULE_VERSION

    async def preview(
        self,
        *,
        portfolio: VirtualPortfolio,
        security: Security,
        holdings: list[PortfolioHolding],
        transaction_type: PortfolioTransactionType,
        quantity: float,
        requested_at: datetime,
        market_bars: list[MarketBar],
    ) -> TradePreview:
        if quantity <= 0:
            raise TradeRejectedError(
                TradeRejectionReason.INVALID_QUANTITY, "The requested quantity must be greater than zero."
            )
        if not portfolio.allow_fractional_shares and not math.isclose(
            quantity, round(quantity), abs_tol=_QUANTITY_EPSILON
        ):
            raise TradeRejectedError(
                TradeRejectionReason.FRACTIONAL_SHARES_DISABLED,
                "This portfolio does not allow fractional shares; the quantity must be a whole number.",
            )
        if security.currency != portfolio.base_currency:
            raise TradeRejectedError(
                TradeRejectionReason.CURRENCY_MISMATCH,
                f"Security currency '{security.currency}' does not match the portfolio's base "
                f"currency '{portfolio.base_currency}'.",
            )
        if not security.active:
            raise TradeRejectedError(
                TradeRejectionReason.SECURITY_NOT_ACTIVE, "This security is not active and cannot be traded."
            )

        eligible_bars = sorted(market_bars, key=lambda bar: bar.timestamp)
        eligible_bars = [bar for bar in eligible_bars if bar.timestamp > requested_at]
        if not eligible_bars:
            raise TradeRejectedError(
                TradeRejectionReason.NO_EXECUTION_PRICE,
                "No stored market bar exists strictly after the requested time; this trade cannot "
                "be simulated yet.",
            )
        execution_bar = eligible_bars[0]
        execution_price = execution_bar.open

        gross_amount = quantity * execution_price
        fee = _calculate_fee(
            fixed_transaction_fee=portfolio.fixed_transaction_fee,
            transaction_fee_bps=portfolio.transaction_fee_bps,
            gross_amount=gross_amount,
        )

        existing_holding = next((h for h in holdings if h.security_id == security.security_id), None)
        quantity_before = existing_holding.quantity if existing_holding is not None else 0.0

        if transaction_type == PortfolioTransactionType.BUY:
            cash_effect = -(gross_amount + fee)
            quantity_after = quantity_before + quantity
        else:
            cash_effect = gross_amount - fee
            quantity_after = quantity_before - quantity

        cash_after = portfolio.cash_balance + cash_effect

        if transaction_type == PortfolioTransactionType.BUY and cash_after < -_QUANTITY_EPSILON:
            raise TradeRejectedError(
                TradeRejectionReason.INSUFFICIENT_CASH,
                f"This purchase requires {gross_amount + fee:.2f} {portfolio.base_currency}, but only "
                f"{portfolio.cash_balance:.2f} {portfolio.base_currency} is available.",
            )
        if transaction_type == PortfolioTransactionType.SELL and quantity_after < -_QUANTITY_EPSILON:
            raise TradeRejectedError(
                TradeRejectionReason.INSUFFICIENT_QUANTITY,
                f"This sale requests {quantity} shares, but only {quantity_before} are held.",
            )

        return TradePreview(
            portfolio=portfolio,
            security=security,
            transaction_type=transaction_type,
            requested_quantity=quantity,
            expected_execution_at=execution_bar.timestamp,
            expected_execution_price=execution_price,
            gross_amount=gross_amount,
            estimated_fee=fee,
            estimated_cash_effect=cash_effect,
            cash_before=portfolio.cash_balance,
            cash_after=max(0.0, cash_after),
            quantity_before=quantity_before,
            quantity_after=max(0.0, quantity_after),
            execution_rule_version=self.execution_rule_version,
        )


class AverageCostPortfolioAccountingPolicy:
    """average-cost-accounting-v1: a single weighted-average-cost lot per holding."""

    accounting_version = ACCOUNTING_VERSION

    def calculate_fee(self, *, portfolio: VirtualPortfolio, gross_amount: float) -> float:
        return _calculate_fee(
            fixed_transaction_fee=portfolio.fixed_transaction_fee,
            transaction_fee_bps=portfolio.transaction_fee_bps,
            gross_amount=gross_amount,
        )

    def apply_buy(
        self,
        *,
        holding: PortfolioHolding | None,
        portfolio_id: UUID,
        security_id: UUID,
        quantity: float,
        execution_price: float,
        fee: float,
        executed_at: datetime,
    ) -> PortfolioHolding:
        gross_amount = quantity * execution_price
        if holding is None:
            new_quantity = quantity
            new_cost_basis = gross_amount + fee
            new_average_cost = new_cost_basis / new_quantity
            return PortfolioHolding(
                portfolio_id=portfolio_id,
                security_id=security_id,
                quantity=new_quantity,
                average_cost=new_average_cost,
                cost_basis=new_cost_basis,
                realized_pnl=0.0,
                first_acquired_at=executed_at,
                last_transaction_at=executed_at,
                updated_at=executed_at,
            )

        new_quantity = holding.quantity + quantity
        new_cost_basis = holding.cost_basis + gross_amount + fee
        new_average_cost = new_cost_basis / new_quantity
        return holding.model_copy(
            update={
                "quantity": new_quantity,
                "average_cost": new_average_cost,
                "cost_basis": new_cost_basis,
                "last_transaction_at": executed_at,
                "updated_at": executed_at,
            }
        )

    def apply_sell(
        self,
        *,
        holding: PortfolioHolding,
        quantity: float,
        execution_price: float,
        fee: float,
        executed_at: datetime,
    ) -> tuple[PortfolioHolding, float]:
        if quantity > holding.quantity + _QUANTITY_EPSILON:
            raise ValueError("cannot sell more than the held quantity")

        gross_proceeds = quantity * execution_price
        removed_cost_basis = holding.average_cost * quantity
        realized_pnl = gross_proceeds - fee - removed_cost_basis

        new_quantity = holding.quantity - quantity
        new_cost_basis = holding.cost_basis - removed_cost_basis
        if math.isclose(new_quantity, 0.0, abs_tol=_QUANTITY_EPSILON):
            new_quantity = 0.0
            new_average_cost = 0.0
            new_cost_basis = 0.0
        else:
            new_average_cost = holding.average_cost

        updated = holding.model_copy(
            update={
                "quantity": new_quantity,
                "average_cost": new_average_cost,
                "cost_basis": new_cost_basis,
                "realized_pnl": holding.realized_pnl + realized_pnl,
                "last_transaction_at": executed_at,
                "updated_at": executed_at,
            }
        )
        return updated, realized_pnl
