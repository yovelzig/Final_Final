"""Application service computing point-in-time portfolio valuations.

Depends only on domain models, application result models, and
`Protocol` contracts (`UnitOfWorkPort`, `PortfolioAnalyticsPort`,
`PortfolioFeedbackPolicyPort`). Never calls `datetime.now()` directly -
time comes from an injected `clock`. Never calls yfinance and never
reads a `MarketBar` later than the requested `as_of`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable
from uuid import UUID

from stock_research_core.application.exceptions import PortfolioValuationError, VirtualPortfolioNotFoundError
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.virtual_portfolio.analytics import (
    PORTFOLIO_VALUATION_VERSION,
    PortfolioAnalyticsPort,
)
from stock_research_core.application.virtual_portfolio.feedback import FEEDBACK_VERSION, PortfolioFeedbackPolicyPort
from stock_research_core.application.virtual_portfolio.models import (
    BatchPortfolioValuationItem,
    PortfolioValuationResult,
)
from stock_research_core.domain.models import MarketBar, Security, utc_now
from stock_research_core.domain.virtual_portfolio.enums import PortfolioFeedbackCode, PortfolioValuationRunStatus
from stock_research_core.domain.virtual_portfolio.models import PortfolioPerformanceSummary, PortfolioValuationRun

Clock = Callable[[], datetime]

_DEFAULT_RECENT_JOURNAL_LIMIT = 10
_DEFAULT_MAX_CONCURRENCY = 4


class PortfolioValuationService:
    """Orchestrates point-in-time portfolio valuation, performance, and batch valuation."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        analytics: PortfolioAnalyticsPort,
        feedback_policy: PortfolioFeedbackPolicyPort,
        clock: Clock = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._analytics = analytics
        self._feedback_policy = feedback_policy
        self._clock = clock

    async def value_portfolio(
        self,
        *,
        portfolio_id: UUID,
        as_of: datetime,
        valuation_version: str = PORTFOLIO_VALUATION_VERSION,
        risk_policy_version: str = FEEDBACK_VERSION,
    ) -> PortfolioValuationResult:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            portfolio = await uow.virtual_portfolios.get(portfolio_id)
            if portfolio is None:
                raise VirtualPortfolioNotFoundError(f"No virtual portfolio found with id '{portfolio_id}'.")
            if as_of < portfolio.simulation_start_at:
                raise PortfolioValuationError("as_of cannot precede the portfolio's simulation_start_at.")

            # `include_zero=True`: a fully-sold (zero-quantity) holding still
            # carries realized P&L history that must count toward the
            # portfolio's total - the analytics layer sums `realized_pnl`
            # across everything given here, but only builds a position
            # valuation for currently-held (quantity > 0), priced holdings.
            all_holdings = await uow.portfolio_holdings.list_for_portfolio(portfolio_id, include_zero=True)
            open_holdings = [holding for holding in all_holdings if holding.quantity > 0]

            run = await uow.portfolio_valuation_runs.create_started(
                PortfolioValuationRun(
                    portfolio_id=portfolio_id,
                    requested_as_of=as_of,
                    valuation_version=valuation_version,
                    risk_policy_version=risk_policy_version,
                    holding_count=len(open_holdings),
                    priced_holding_count=0,
                    missing_price_count=0,
                    started_at=now,
                )
            )

            prices: dict[UUID, MarketBar] = {}
            missing_price_count = 0
            for holding in open_holdings:
                bar = await uow.market_bars.get_latest_bar_at_or_before(holding.security_id, as_of)
                if bar is not None:
                    prices[holding.security_id] = bar
                else:
                    missing_price_count += 1

            benchmark_bars: list[MarketBar] = []
            if portfolio.benchmark_security_id is not None:
                benchmark_bars = await uow.market_bars.list_range(
                    portfolio.benchmark_security_id, portfolio.simulation_start_at, as_of
                )

            try:
                priced_open_holdings = [holding for holding in open_holdings if holding.security_id in prices]
                securities: dict[UUID, Security] = {}
                for holding in priced_open_holdings:
                    security = await uow.securities.get_by_id(holding.security_id)
                    if security is not None:
                        securities[holding.security_id] = security
                snapshot, positions = await self._analytics.calculate_snapshot(
                    portfolio=portfolio,
                    holdings=all_holdings,
                    prices=prices,
                    securities=securities,
                    benchmark_bars=benchmark_bars,
                    as_of=as_of,
                )
            except Exception as exc:
                await uow.portfolio_valuation_runs.mark_failed(
                    run.run_id,
                    completed_at=self._clock(),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                await uow.commit()
                raise

            stored_snapshot = await uow.portfolio_valuations.upsert_snapshot(snapshot)
            rewritten_positions = [
                position.model_copy(update={"snapshot_id": stored_snapshot.snapshot_id})
                for position in positions
            ]
            stored_positions = (
                await uow.portfolio_valuations.upsert_positions(rewritten_positions)
                if rewritten_positions
                else []
            )

            prior_snapshots = await uow.portfolio_valuations.list_range(
                portfolio_id, portfolio.simulation_start_at, as_of
            )
            performance = None
            if len(prior_snapshots) >= 2:
                transactions = await uow.portfolio_transactions.list_for_portfolio(
                    portfolio_id, portfolio.simulation_start_at, as_of
                )
                performance = await self._analytics.calculate_performance(
                    portfolio=portfolio,
                    snapshots=prior_snapshots,
                    transactions=transactions,
                    start_at=portfolio.simulation_start_at,
                    end_at=as_of,
                )

            recent_journal_entries = await uow.portfolio_journal.list_for_portfolio(
                portfolio_id, limit=_DEFAULT_RECENT_JOURNAL_LIMIT
            )
            related_skill_ids: list = []
            risk_assessment = self._feedback_policy.assess(
                portfolio=portfolio,
                snapshot=stored_snapshot,
                positions=stored_positions,
                performance=performance,
                recent_journal_entries=recent_journal_entries,
                related_skill_ids=related_skill_ids,
            )
            if missing_price_count > 0:
                risk_assessment = risk_assessment.model_copy(
                    update={
                        "feedback_codes": [
                            *risk_assessment.feedback_codes,
                            PortfolioFeedbackCode.MISSING_PRICE_DATA,
                        ],
                        "educational_feedback": [
                            *risk_assessment.educational_feedback,
                            f"{missing_price_count} holding(s) could not be priced as of this valuation "
                            "and were excluded from the totals above.",
                        ],
                    }
                )
            stored_risk_assessment = await uow.portfolio_risk.upsert(risk_assessment)

            completed_at = self._clock()
            if open_holdings and not prices:
                stored_run = await uow.portfolio_valuation_runs.mark_no_price_data(
                    run.run_id, completed_at=completed_at, missing_price_count=missing_price_count
                )
            else:
                stored_run = await uow.portfolio_valuation_runs.mark_completed(
                    run.run_id,
                    completed_at=completed_at,
                    priced_holding_count=len(prices),
                    missing_price_count=missing_price_count,
                )

            await uow.commit()

        return PortfolioValuationResult(
            run=stored_run,
            snapshot=stored_snapshot,
            positions=stored_positions,
            risk_assessment=stored_risk_assessment,
        )

    async def calculate_performance(
        self, *, portfolio_id: UUID, start_at: datetime, end_at: datetime
    ) -> PortfolioPerformanceSummary:
        async with self._unit_of_work_factory() as uow:
            portfolio = await uow.virtual_portfolios.get(portfolio_id)
            if portfolio is None:
                raise VirtualPortfolioNotFoundError(f"No virtual portfolio found with id '{portfolio_id}'.")

            snapshots = await uow.portfolio_valuations.list_range(portfolio_id, start_at, end_at)
            transactions = await uow.portfolio_transactions.list_for_portfolio(portfolio_id, start_at, end_at)

        return await self._analytics.calculate_performance(
            portfolio=portfolio,
            snapshots=snapshots,
            transactions=transactions,
            start_at=start_at,
            end_at=end_at,
        )

    async def value_many(
        self, *, portfolio_ids: list[UUID], as_of: datetime, max_concurrency: int = _DEFAULT_MAX_CONCURRENCY
    ) -> list[BatchPortfolioValuationItem]:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero")

        deduplicated_ids = list(dict.fromkeys(portfolio_ids))
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _value_one(portfolio_id: UUID) -> BatchPortfolioValuationItem:
            async with semaphore:
                try:
                    result = await self.value_portfolio(portfolio_id=portfolio_id, as_of=as_of)
                    return BatchPortfolioValuationItem(
                        portfolio_id=portfolio_id, status=result.run.status, result=result
                    )
                except Exception as exc:
                    return BatchPortfolioValuationItem(
                        portfolio_id=portfolio_id,
                        status=PortfolioValuationRunStatus.FAILED,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )

        # Each `_value_one` call opens its own independent Unit of Work
        # (via `value_portfolio` -> `self._unit_of_work_factory()`) - no
        # AsyncSession is ever shared across these concurrent tasks.
        results = await asyncio.gather(*(_value_one(portfolio_id) for portfolio_id in deduplicated_ids))
        return list(results)
