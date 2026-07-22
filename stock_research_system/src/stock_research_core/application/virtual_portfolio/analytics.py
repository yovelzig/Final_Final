"""The portfolio-analytics Protocol and its version constants.

Implementations may use pandas/NumPy - but only in infrastructure
(`stock_research_core.infrastructure.virtual_portfolio`). This module
stays pure so both the application layer and its tests can import it
without pulling in a heavyweight numerical dependency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioHolding,
    PortfolioPerformanceSummary,
    PortfolioPositionValuation,
    PortfolioTransaction,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)

#: Calculator versions. Every `PortfolioValuationSnapshot`/
#: `PortfolioPerformanceSummary` this codebase produces must carry one
#: of these, so the same stored bars + version always reproduce the
#: same numbers.
PORTFOLIO_VALUATION_VERSION = "portfolio-valuation-v1"
PORTFOLIO_PERFORMANCE_VERSION = "portfolio-performance-v1"


class PortfolioAnalyticsPort(Protocol):
    """Computes deterministic, point-in-time-safe portfolio valuation and
    performance metrics from already-stored `MarketBar` objects. Never
    queries a database, never calls yfinance, and never reads a price
    later than the `as_of`/`end_at` it was asked to compute over.
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
        """`securities` (keyed by `security_id`) is not in the original
        spec signature but is required to compute sector exposure/HHI -
        `prices` (plain `MarketBar` rows) carries no sector information.
        A minimal, necessary addition mirroring the pattern already used
        throughout this codebase when a literal spec signature omits a
        value a rule genuinely needs."""
        ...

    async def calculate_performance(
        self,
        *,
        portfolio: VirtualPortfolio,
        snapshots: list[PortfolioValuationSnapshot],
        transactions: list[PortfolioTransaction],
        start_at: datetime,
        end_at: datetime,
    ) -> PortfolioPerformanceSummary: ...
