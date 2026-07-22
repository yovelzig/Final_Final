"""Application service orchestrating security resolution and market-data ingestion.

This module depends only on domain models and `Protocol` contracts. It
must never import a concrete infrastructure library such as yfinance or
pandas; adapters are injected by the caller (e.g. the CLI).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from stock_research_core.application.exceptions import MarketDataUnavailableError
from stock_research_core.application.market_data.models import (
    DataQualityIssue,
    MarketDataIngestionResult,
    MarketDataQualityReport,
)
from stock_research_core.contracts.ports import MarketDataPort, SecurityResolverPort
from stock_research_core.domain.models import MarketBar, Security


@runtime_checkable
class QualityAwareMarketDataPort(MarketDataPort, Protocol):
    """A `MarketDataPort` that can also report data-quality details.

    Providers that support this richer contract are used automatically;
    providers that only implement the plain `MarketDataPort` fall back to
    a minimal, derived quality report.
    """

    async def fetch_bars_with_report(
        self,
        security: Security,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
    ) -> tuple[list[MarketBar], MarketDataQualityReport]: ...


class MarketDataIngestionService:
    """Resolves securities and ingests market data through injected ports."""

    def __init__(
        self,
        security_resolver: SecurityResolverPort,
        market_data_provider: MarketDataPort,
    ) -> None:
        self._security_resolver = security_resolver
        self._market_data_provider = market_data_provider

    async def ingest_historical(
        self,
        *,
        ticker: str | None,
        company_name: str | None,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
    ) -> MarketDataIngestionResult:
        security = await self._security_resolver.resolve(ticker, company_name)
        bars, report = await self._fetch_with_report(security, start_at, end_at, interval)
        return MarketDataIngestionResult(
            security=security,
            bars=bars,
            quality_report=report,
            is_incremental=False,
            provider_name=self._provider_name(),
        )

    async def ingest_incremental(
        self,
        *,
        security: Security,
        last_stored_bar_at: datetime,
        end_at: datetime,
        interval: str = "1d",
    ) -> MarketDataIngestionResult:
        if last_stored_bar_at.tzinfo is None or end_at.tzinfo is None:
            raise ValueError("last_stored_bar_at and end_at must be timezone-aware datetimes.")

        next_start = last_stored_bar_at + timedelta(days=1)

        if next_start >= end_at:
            return self._no_new_data_result(security, next_start, end_at)

        try:
            bars, report = await self._fetch_with_report(security, next_start, end_at, interval)
        except MarketDataUnavailableError:
            return self._no_new_data_result(security, next_start, end_at)

        return MarketDataIngestionResult(
            security=security,
            bars=bars,
            quality_report=report,
            is_incremental=True,
            provider_name=self._provider_name(),
        )

    async def ingest_benchmark(
        self,
        *,
        benchmark_ticker: str,
        start_at: datetime,
        end_at: datetime,
    ) -> MarketDataIngestionResult:
        return await self.ingest_historical(
            ticker=benchmark_ticker,
            company_name=None,
            start_at=start_at,
            end_at=end_at,
            interval="1d",
        )

    async def _fetch_with_report(
        self,
        security: Security,
        start_at: datetime,
        end_at: datetime,
        interval: str,
    ) -> tuple[list[MarketBar], MarketDataQualityReport]:
        provider = self._market_data_provider
        if isinstance(provider, QualityAwareMarketDataPort):
            return await provider.fetch_bars_with_report(security, start_at, end_at, interval)
        bars = await provider.fetch_bars(security, start_at, end_at, interval)
        return bars, self._basic_quality_report(start_at, end_at, bars)

    def _no_new_data_result(
        self,
        security: Security,
        requested_start_at: datetime,
        requested_end_at: datetime,
    ) -> MarketDataIngestionResult:
        report = MarketDataQualityReport(
            requested_start_at=requested_start_at,
            requested_end_at=requested_end_at,
            first_bar_at=None,
            last_bar_at=None,
            provider_rows_received=0,
            valid_bars_returned=0,
            duplicate_rows_removed=0,
            invalid_rows_removed=0,
            issues=[
                DataQualityIssue(
                    code="NO_NEW_DATA",
                    message="No new bars were available after the last stored bar.",
                    severity="WARNING",
                    timestamp=None,
                )
            ],
        )
        return MarketDataIngestionResult(
            security=security,
            bars=[],
            quality_report=report,
            is_incremental=True,
            provider_name=self._provider_name(),
        )

    @staticmethod
    def _basic_quality_report(
        start_at: datetime, end_at: datetime, bars: list[MarketBar]
    ) -> MarketDataQualityReport:
        return MarketDataQualityReport(
            requested_start_at=start_at,
            requested_end_at=end_at,
            first_bar_at=bars[0].timestamp if bars else None,
            last_bar_at=bars[-1].timestamp if bars else None,
            provider_rows_received=len(bars),
            valid_bars_returned=len(bars),
            duplicate_rows_removed=0,
            invalid_rows_removed=0,
            issues=[],
        )

    def _provider_name(self) -> str:
        return getattr(
            self._market_data_provider, "provider_name", type(self._market_data_provider).__name__
        )
