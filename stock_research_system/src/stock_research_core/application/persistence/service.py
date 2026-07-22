"""Application service that persists market-data ingestion results.

This module depends only on domain models, the Phase 2
`MarketDataIngestionService`, and the persistence `Protocol` contracts.
It never instantiates a concrete adapter, engine, session, or
repository - everything is supplied by the caller (the CLI).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import UUID

from stock_research_core.application.exceptions import (
    NoStoredMarketDataError,
    PersistenceError,
    SecurityNotStoredError,
    StockResearchError,
)
from stock_research_core.application.market_data.models import MarketDataIngestionResult
from stock_research_core.application.market_data.service import MarketDataIngestionService
from stock_research_core.application.persistence.models import (
    IngestionRunStatus,
    PersistedMarketDataResult,
    PersistenceCounts,
)
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.models import MarketBar, TrackedSecurity

_ERROR_MESSAGE_MAX_LENGTH = 2000


def _rewrite_security_id(bars: list[MarketBar], canonical_security_id: UUID) -> list[MarketBar]:
    if all(bar.security_id == canonical_security_id for bar in bars):
        return bars
    return [bar.model_copy(update={"security_id": canonical_security_id}) for bar in bars]


class PersistedMarketDataIngestionService:
    """Ingests market data (via `MarketDataIngestionService`) and stores it."""

    def __init__(
        self,
        market_data_ingestion_service: MarketDataIngestionService,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
    ) -> None:
        self._market_data_ingestion_service = market_data_ingestion_service
        self._unit_of_work_factory = unit_of_work_factory

    async def ingest_historical_and_store(
        self,
        *,
        ticker: str | None,
        company_name: str | None,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
        track_security: bool = True,
    ) -> PersistedMarketDataResult:
        ingestion_result = await self._market_data_ingestion_service.ingest_historical(
            ticker=ticker,
            company_name=company_name,
            start_at=start_at,
            end_at=end_at,
            interval=interval,
        )
        return await self._persist(
            ingestion_result=ingestion_result,
            requested_interval=interval,
            track_security=track_security,
        )

    async def ingest_incremental_and_store(
        self,
        *,
        ticker: str,
        end_at: datetime,
        interval: str = "1d",
    ) -> PersistedMarketDataResult:
        async with self._unit_of_work_factory() as lookup_uow:
            stored_security = await lookup_uow.securities.get_by_ticker(ticker)
            if stored_security is None:
                raise SecurityNotStoredError(
                    f"No stored security found for ticker '{ticker}'. Run historical "
                    "ingestion for this ticker before incremental ingestion."
                )
            last_stored_bar_at = await lookup_uow.market_bars.get_latest_timestamp(
                stored_security.security_id, interval=interval
            )

        if last_stored_bar_at is None:
            raise NoStoredMarketDataError(
                f"No stored market bars found for '{ticker}' at interval '{interval}'. "
                "Run historical ingestion for this ticker before incremental ingestion."
            )

        ingestion_result = await self._market_data_ingestion_service.ingest_incremental(
            security=stored_security,
            last_stored_bar_at=last_stored_bar_at,
            end_at=end_at,
            interval=interval,
        )

        is_no_new_data = any(
            issue.code == "NO_NEW_DATA" for issue in ingestion_result.quality_report.issues
        )

        return await self._persist(
            ingestion_result=ingestion_result,
            requested_interval=interval,
            track_security=False,
            is_no_new_data=is_no_new_data,
        )

    async def ingest_benchmark_and_store(
        self,
        *,
        benchmark_ticker: str,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
        track_security: bool = False,
    ) -> PersistedMarketDataResult:
        ingestion_result = await self._market_data_ingestion_service.ingest_benchmark(
            benchmark_ticker=benchmark_ticker, start_at=start_at, end_at=end_at
        )
        return await self._persist(
            ingestion_result=ingestion_result,
            requested_interval=interval,
            track_security=track_security,
        )

    async def _persist(
        self,
        *,
        ingestion_result: MarketDataIngestionResult,
        requested_interval: str,
        track_security: bool,
        is_no_new_data: bool = False,
    ) -> PersistedMarketDataResult:
        run_id: UUID | None = None
        try:
            async with self._unit_of_work_factory() as uow:
                canonical_security = await uow.securities.upsert(ingestion_result.security)
                canonical_bars = _rewrite_security_id(
                    ingestion_result.bars, canonical_security.security_id
                )

                quality_report = ingestion_result.quality_report
                run = await uow.ingestion_runs.start(
                    security_id=canonical_security.security_id,
                    provider_name=ingestion_result.provider_name,
                    interval=requested_interval,
                    requested_start_at=quality_report.requested_start_at,
                    requested_end_at=quality_report.requested_end_at,
                    is_incremental=ingestion_result.is_incremental,
                )
                run_id = run.run_id

                quality_issues_persisted = await uow.ingestion_runs.save_quality_issues(
                    run_id, quality_report.issues
                )

                if is_no_new_data:
                    bars_persisted = 0
                    await uow.ingestion_runs.mark_no_new_data(
                        run_id,
                        provider_rows_received=quality_report.provider_rows_received,
                        valid_bars_returned=quality_report.valid_bars_returned,
                        duplicate_rows_removed=quality_report.duplicate_rows_removed,
                        invalid_rows_removed=quality_report.invalid_rows_removed,
                    )
                    status = IngestionRunStatus.NO_NEW_DATA
                else:
                    bars_persisted = await uow.market_bars.upsert_many(canonical_bars)
                    await uow.ingestion_runs.mark_completed(
                        run_id,
                        provider_rows_received=quality_report.provider_rows_received,
                        valid_bars_returned=quality_report.valid_bars_returned,
                        bars_persisted=bars_persisted,
                        duplicate_rows_removed=quality_report.duplicate_rows_removed,
                        invalid_rows_removed=quality_report.invalid_rows_removed,
                    )
                    status = IngestionRunStatus.COMPLETED

                latest_stored_bar_at = await uow.market_bars.get_latest_timestamp(
                    canonical_security.security_id, interval=requested_interval
                )

                existing_tracked = await uow.tracked_securities.get(canonical_security.security_id)
                if track_security:
                    tracked_security = existing_tracked or TrackedSecurity(
                        security_id=canonical_security.security_id
                    )
                    await uow.tracked_securities.upsert(tracked_security)
                    existing_tracked = tracked_security
                if existing_tracked is not None and latest_stored_bar_at is not None:
                    await uow.tracked_securities.update_last_successful_update(
                        canonical_security.security_id, latest_stored_bar_at
                    )

                await uow.commit()
        except Exception as exc:
            await self._mark_failed_safely(run_id, exc)
            if isinstance(exc, StockResearchError):
                raise
            raise PersistenceError("Failed to persist market-data ingestion result.") from exc

        canonical_ingestion_result = MarketDataIngestionResult(
            security=canonical_security,
            bars=canonical_bars,
            quality_report=ingestion_result.quality_report,
            is_incremental=ingestion_result.is_incremental,
            provider_name=ingestion_result.provider_name,
        )

        return PersistedMarketDataResult(
            ingestion_result=canonical_ingestion_result,
            run_id=run_id,
            persistence_counts=PersistenceCounts(
                securities_upserted=1,
                bars_attempted=len(canonical_bars),
                bars_persisted=bars_persisted,
                quality_issues_persisted=quality_issues_persisted,
            ),
            latest_stored_bar_at=latest_stored_bar_at,
            status=status,
        )

    async def _mark_failed_safely(self, run_id: UUID | None, exc: Exception) -> None:
        """Best-effort: record a FAILED run in a fresh transaction.

        A secondary failure here (e.g. the database is genuinely down)
        must never replace or hide the original exception, so it is
        swallowed rather than raised.
        """
        if run_id is None:
            return
        try:
            async with self._unit_of_work_factory() as recovery_uow:
                await recovery_uow.ingestion_runs.mark_failed(
                    run_id,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:_ERROR_MESSAGE_MAX_LENGTH],
                )
                await recovery_uow.commit()
        except Exception:  # noqa: BLE001 - best-effort audit write only
            pass
