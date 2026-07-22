"""Pandas/NumPy-backed implementation of `PortfolioAnalyticsPort`.

All pandas/NumPy usage is confined to this module (infrastructure only
- domain and application `virtual_portfolio` packages never import
either). Every synchronous calculation runs in a worker thread via
`asyncio.to_thread` so it never blocks the event loop. Public methods
only ever return domain objects - a `pandas.DataFrame` never leaves
this module.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from uuid import UUID, uuid4

import pandas as pd

from stock_research_core.application.exceptions import InsufficientPortfolioValuationDataError
from stock_research_core.application.virtual_portfolio.analytics import (
    PORTFOLIO_PERFORMANCE_VERSION,
    PORTFOLIO_VALUATION_VERSION,
)
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioHolding,
    PortfolioPerformanceSummary,
    PortfolioPositionValuation,
    PortfolioTransaction,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)
from stock_research_core.domain.virtual_portfolio.enums import PortfolioTransactionStatus

_TRADING_DAYS_PER_YEAR = 252
_MINIMUM_BARS_FOR_VOLATILITY = 3

#: Diversification-score component weights (spec section 10). When no
#: holding has known sector data, the sector component's weight is
#: reallocated entirely into the position component (documented
#: behavior for the "sector data unavailable" case).
_POSITION_COMPONENT_WEIGHT = 0.50
_SECTOR_COMPONENT_WEIGHT = 0.30
_HOLDING_COUNT_COMPONENT_WEIGHT = 0.20
_HOLDING_COUNT_NORMALIZER = 10


class PandasPortfolioAnalytics:
    """portfolio-valuation-v1 / portfolio-performance-v1: deterministic,
    point-in-time-safe portfolio analytics backed by pandas/NumPy.
    """

    async def calculate_snapshot(
        self,
        *,
        portfolio: VirtualPortfolio,
        holdings: list[PortfolioHolding],
        prices: dict[UUID, MarketBar],
        securities: dict[UUID, Security],
        benchmark_bars: list[MarketBar],
        as_of: datetime,
    ) -> tuple[PortfolioValuationSnapshot, list[PortfolioPositionValuation]]:
        return await asyncio.to_thread(
            self._calculate_snapshot_sync, portfolio, holdings, prices, securities, benchmark_bars, as_of
        )

    async def calculate_performance(
        self,
        *,
        portfolio: VirtualPortfolio,
        snapshots: list[PortfolioValuationSnapshot],
        transactions: list[PortfolioTransaction],
        start_at: datetime,
        end_at: datetime,
    ) -> PortfolioPerformanceSummary:
        return await asyncio.to_thread(
            self._calculate_performance_sync, portfolio, snapshots, transactions, start_at, end_at
        )

    # -- snapshot valuation ---------------------------------------------------------

    def _calculate_snapshot_sync(
        self,
        portfolio: VirtualPortfolio,
        holdings: list[PortfolioHolding],
        prices: dict[UUID, MarketBar],
        securities: dict[UUID, Security],
        benchmark_bars: list[MarketBar],
        as_of: datetime,
    ) -> tuple[PortfolioValuationSnapshot, list[PortfolioPositionValuation]]:
        # Realized P&L is summed across *every* holding ever held (even
        # fully-sold, zero-quantity ones) - it is a lifetime figure, not
        # a point-in-time one.
        total_realized_pnl = sum(holding.realized_pnl for holding in holdings)

        open_priced_holdings = [
            holding for holding in holdings if holding.quantity > 0 and holding.security_id in prices
        ]

        snapshot_id = uuid4()
        raw_positions: list[dict] = []
        for holding in open_priced_holdings:
            bar = prices[holding.security_id]
            market_price = bar.adjusted_close
            market_value = holding.quantity * market_price
            unrealized_pnl = market_value - holding.cost_basis
            unrealized_return = unrealized_pnl / holding.cost_basis if holding.cost_basis > 0 else 0.0
            security = securities.get(holding.security_id)
            raw_positions.append(
                {
                    "security_id": holding.security_id,
                    "quantity": holding.quantity,
                    "market_price": market_price,
                    "market_value": market_value,
                    "average_cost": holding.average_cost,
                    "cost_basis": holding.cost_basis,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_return": unrealized_return,
                    "sector": security.sector if security is not None else None,
                    "price_timestamp": bar.timestamp,
                }
            )
        if open_priced_holdings:
            data_cutoff_at = max(row["price_timestamp"] for row in raw_positions)
        else:
            data_cutoff_at = as_of

        holdings_value = sum(row["market_value"] for row in raw_positions)
        total_cost_basis = sum(row["cost_basis"] for row in raw_positions)
        unrealized_pnl_total = sum(row["unrealized_pnl"] for row in raw_positions)
        cash_balance = portfolio.cash_balance
        total_value = cash_balance + holdings_value

        positions: list[PortfolioPositionValuation] = []
        for row in raw_positions:
            weight = row["market_value"] / total_value if total_value > 0 else 0.0
            positions.append(
                PortfolioPositionValuation(
                    snapshot_id=snapshot_id,
                    portfolio_id=portfolio.portfolio_id,
                    security_id=row["security_id"],
                    quantity=row["quantity"],
                    market_price=row["market_price"],
                    market_value=row["market_value"],
                    average_cost=row["average_cost"],
                    cost_basis=row["cost_basis"],
                    unrealized_pnl=row["unrealized_pnl"],
                    unrealized_return=row["unrealized_return"],
                    portfolio_weight=weight,
                    sector=row["sector"],
                    price_timestamp=row["price_timestamp"],
                )
            )

        position_weights = [p.portfolio_weight for p in positions]
        largest_position_weight = max(position_weights, default=0.0)
        portfolio_hhi = min(1.0, sum(w * w for w in position_weights))

        sector_weights: dict[str, float] = {}
        for position in positions:
            if position.sector is not None:
                sector_weights[position.sector] = sector_weights.get(position.sector, 0.0) + position.portfolio_weight
        has_sector_data = bool(sector_weights)
        sector_hhi = min(1.0, sum(w * w for w in sector_weights.values())) if has_sector_data else None
        largest_sector_weight = max(sector_weights.values(), default=None) if has_sector_data else None

        cash_weight = cash_balance / total_value if total_value > 0 else 1.0

        position_component = 1.0 - portfolio_hhi
        holding_count_component = min(len(positions) / _HOLDING_COUNT_NORMALIZER, 1.0)
        if has_sector_data:
            sector_component = 1.0 - sector_hhi
            diversification_score = (
                _POSITION_COMPONENT_WEIGHT * position_component
                + _SECTOR_COMPONENT_WEIGHT * sector_component
                + _HOLDING_COUNT_COMPONENT_WEIGHT * holding_count_component
            )
        else:
            # Sector data unavailable: its weight is reallocated entirely
            # into the position component (documented spec behavior).
            diversification_score = (
                _POSITION_COMPONENT_WEIGHT + _SECTOR_COMPONENT_WEIGHT
            ) * position_component + _HOLDING_COUNT_COMPONENT_WEIGHT * holding_count_component
        diversification_score = max(0.0, min(1.0, diversification_score))

        benchmark_return, excess_return = self._calculate_benchmark_return(
            portfolio=portfolio,
            benchmark_bars=benchmark_bars,
            as_of=as_of,
            total_return=(total_value / portfolio.initial_cash - 1.0),
        )

        snapshot = PortfolioValuationSnapshot(
            snapshot_id=snapshot_id,
            portfolio_id=portfolio.portfolio_id,
            as_of=as_of,
            data_cutoff_at=min(data_cutoff_at, as_of),
            cash_balance=cash_balance,
            holdings_value=holdings_value,
            total_value=total_value,
            total_cost_basis=total_cost_basis,
            realized_pnl=total_realized_pnl,
            unrealized_pnl=unrealized_pnl_total,
            net_profit=total_realized_pnl + unrealized_pnl_total,
            total_return=total_value / portfolio.initial_cash - 1.0,
            benchmark_return=benchmark_return,
            excess_return=excess_return,
            largest_position_weight=largest_position_weight,
            largest_sector_weight=largest_sector_weight,
            cash_weight=cash_weight,
            position_count=len(positions),
            portfolio_hhi=portfolio_hhi,
            sector_hhi=sector_hhi,
            diversification_score=diversification_score,
            valuation_version=PORTFOLIO_VALUATION_VERSION,
        )
        return snapshot, positions

    def _calculate_benchmark_return(
        self,
        *,
        portfolio: VirtualPortfolio,
        benchmark_bars: list[MarketBar],
        as_of: datetime,
        total_return: float,
    ) -> tuple[float | None, float | None]:
        if portfolio.benchmark_security_id is None or not benchmark_bars:
            return None, None
        window_bars = [
            bar
            for bar in benchmark_bars
            if portfolio.simulation_start_at <= bar.timestamp <= as_of
        ]
        if len(window_bars) < 2:
            return None, None
        window_bars.sort(key=lambda bar: bar.timestamp)
        start_price = window_bars[0].adjusted_close
        end_price = window_bars[-1].adjusted_close
        benchmark_return = end_price / start_price - 1.0
        return benchmark_return, total_return - benchmark_return

    # -- performance summary ---------------------------------------------------------

    def _calculate_performance_sync(
        self,
        portfolio: VirtualPortfolio,
        snapshots: list[PortfolioValuationSnapshot],
        transactions: list[PortfolioTransaction],
        start_at: datetime,
        end_at: datetime,
    ) -> PortfolioPerformanceSummary:
        window_snapshots = sorted(
            (s for s in snapshots if start_at <= s.as_of <= end_at), key=lambda s: s.as_of
        )
        warnings: list[str] = []
        if len(window_snapshots) < 2:
            raise InsufficientPortfolioValuationDataError(
                "At least two portfolio valuations are required to calculate performance."
            )

        frame = pd.DataFrame(
            [
                {
                    "as_of": s.as_of,
                    "total_value": s.total_value,
                    "cash_weight": s.cash_weight,
                    "position_count": s.position_count,
                    "benchmark_return": s.benchmark_return,
                }
                for s in window_snapshots
            ]
        )

        start_value = float(frame["total_value"].iloc[0])
        end_value = float(frame["total_value"].iloc[-1])
        total_return = end_value / start_value - 1.0

        annualized_volatility = None
        daily_returns = frame["total_value"].astype(float).pct_change().dropna()
        if len(daily_returns) >= _MINIMUM_BARS_FOR_VOLATILITY - 1:
            annualized_volatility = float(daily_returns.std(ddof=1) * math.sqrt(_TRADING_DAYS_PER_YEAR))
        else:
            warnings.append(
                f"Not enough valuation snapshots to compute annualized volatility (need at least "
                f"{_MINIMUM_BARS_FOR_VOLATILITY})."
            )

        running_max = frame["total_value"].astype(float).cummax()
        maximum_drawdown = float(
            min(0.0, (frame["total_value"].astype(float) / running_max - 1.0).min())
        )

        benchmark_return = None
        excess_return = None
        start_benchmark_return = window_snapshots[0].benchmark_return
        end_benchmark_return = window_snapshots[-1].benchmark_return
        if start_benchmark_return is not None and end_benchmark_return is not None:
            benchmark_return = (1.0 + end_benchmark_return) / (1.0 + start_benchmark_return) - 1.0
            excess_return = total_return - benchmark_return
        else:
            warnings.append("Benchmark return is unavailable for part of this window.")

        executed_amounts = [
            txn.gross_amount
            for txn in transactions
            if txn.status == PortfolioTransactionStatus.EXECUTED
            and txn.executed_at is not None
            and start_at <= txn.executed_at <= end_at
            and txn.gross_amount is not None
        ]
        average_value = float(frame["total_value"].astype(float).mean())
        turnover_ratio = (sum(executed_amounts) / average_value) if average_value > 0 else 0.0

        average_cash_weight = float(frame["cash_weight"].astype(float).mean())
        average_position_count = float(frame["position_count"].astype(float).mean())

        return PortfolioPerformanceSummary(
            portfolio_id=portfolio.portfolio_id,
            start_at=start_at,
            end_at=end_at,
            start_value=start_value,
            end_value=end_value,
            total_return=total_return,
            annualized_volatility=annualized_volatility,
            maximum_drawdown=maximum_drawdown if maximum_drawdown != 0.0 or len(frame) > 1 else None,
            benchmark_return=benchmark_return,
            excess_return=excess_return,
            turnover_ratio=turnover_ratio,
            average_cash_weight=average_cash_weight,
            average_position_count=average_position_count,
            calculation_version=PORTFOLIO_PERFORMANCE_VERSION,
            warnings=warnings,
        )
