"""PostgreSQL integration tests: ingestion-run auditing and end-to-end persistence.

The ingestion side uses fake `SecurityResolverPort` / `MarketDataPort`
implementations (no internet, no yfinance) so only the database
round trip is under test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text

from stock_research_core.application.market_data.models import DataQualityIssue
from stock_research_core.application.market_data.service import MarketDataIngestionService
from stock_research_core.application.persistence.models import IngestionRunStatus
from stock_research_core.application.persistence.service import (
    PersistedMarketDataIngestionService,
)
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security

pytestmark = pytest.mark.integration


def _bar(security_id, day: int, **overrides: object) -> MarketBar:
    defaults: dict = dict(
        security_id=security_id,
        timestamp=datetime(2025, 1, day, tzinfo=timezone.utc),
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        adjusted_close=102.0,
        volume=1000,
        source_name="fake-provider",
    )
    defaults.update(overrides)
    return MarketBar(**defaults)


class _FakeSecurityResolver:
    def __init__(self, ticker: str, company_name: str) -> None:
        self._ticker = ticker
        self._company_name = company_name

    async def resolve(self, ticker: str | None, company_name: str | None) -> Security:
        return Security(
            ticker=self._ticker, company_name=self._company_name, exchange=Exchange.NASDAQ
        )


class _FakeMarketDataProvider:
    provider_name = "fake-provider"

    def __init__(self, bars: list[MarketBar]) -> None:
        self._bars = bars
        self.calls: list[tuple] = []

    async def fetch_bars(
        self, security: Security, start_at: datetime, end_at: datetime, interval: str = "1d"
    ) -> list[MarketBar]:
        self.calls.append((security, start_at, end_at, interval))
        return [
            bar.model_copy(update={"security_id": security.security_id})
            for bar in self._bars
            if start_at <= bar.timestamp <= end_at
        ]


async def test_ingestion_run_and_quality_issues_are_stored(
    uow_factory, test_engine: AsyncEngine
) -> None:
    security = Security(ticker="NVDA", company_name="NVIDIA Corporation", exchange=Exchange.NASDAQ)

    async with uow_factory() as uow:
        stored = await uow.securities.upsert(security)
        run = await uow.ingestion_runs.start(
            security_id=stored.security_id,
            provider_name="fake-provider",
            interval="1d",
            requested_start_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            requested_end_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
            is_incremental=False,
        )
        await uow.ingestion_runs.save_quality_issues(
            run.run_id,
            [DataQualityIssue(code="TEST_ISSUE", message="a test issue", severity="WARNING")],
        )
        await uow.ingestion_runs.mark_completed(
            run.run_id,
            provider_rows_received=5,
            valid_bars_returned=5,
            bars_persisted=5,
            duplicate_rows_removed=0,
            invalid_rows_removed=0,
        )
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.ingestion_runs.get_by_id(run.run_id)
    assert fetched is not None
    assert fetched.status == IngestionRunStatus.COMPLETED

    async with test_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT COUNT(*) FROM market_data_quality_issues WHERE run_id = :run_id"),
            {"run_id": str(run.run_id)},
        )
        count = result.scalar_one()
    assert count == 1


async def test_failed_transaction_rolls_back(uow_factory, test_engine: AsyncEngine) -> None:
    security = Security(ticker="NVDA", company_name="NVIDIA Corporation", exchange=Exchange.NASDAQ)

    with pytest.raises(RuntimeError):
        async with uow_factory() as uow:
            await uow.securities.upsert(security)
            raise RuntimeError("simulated failure before commit")

    async with test_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT COUNT(*) FROM securities WHERE ticker = 'NVDA'")
        )
        count = result.scalar_one()
    assert count == 0


async def test_complete_historical_ingestion_end_to_end_with_fake_provider(uow_factory) -> None:
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, day) for day in (2, 3, 4)])
    market_data_service = MarketDataIngestionService(
        security_resolver=resolver, market_data_provider=provider
    )
    service = PersistedMarketDataIngestionService(
        market_data_ingestion_service=market_data_service, unit_of_work_factory=uow_factory
    )

    result = await service.ingest_historical_and_store(
        ticker="NVDA",
        company_name=None,
        start_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
    )

    assert result.persistence_counts.bars_persisted == 3
    assert result.status == IngestionRunStatus.COMPLETED

    async with uow_factory() as uow:
        stored_bars = await uow.market_bars.list_range(
            result.ingestion_result.security.security_id,
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 10, tzinfo=timezone.utc),
        )
        tracked = await uow.tracked_securities.get(result.ingestion_result.security.security_id)

    assert len(stored_bars) == 3
    assert tracked is not None


async def test_incremental_ingestion_appends_only_missing_bars(uow_factory) -> None:
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    placeholder_id = uuid4()
    historical_provider = _FakeMarketDataProvider(
        [_bar(placeholder_id, day) for day in (2, 3, 4)]
    )
    market_data_service = MarketDataIngestionService(
        security_resolver=resolver, market_data_provider=historical_provider
    )
    service = PersistedMarketDataIngestionService(
        market_data_ingestion_service=market_data_service, unit_of_work_factory=uow_factory
    )

    historical_result = await service.ingest_historical_and_store(
        ticker="NVDA",
        company_name=None,
        start_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
    )
    canonical_id = historical_result.ingestion_result.security.security_id

    incremental_provider = _FakeMarketDataProvider(
        [_bar(canonical_id, day) for day in (5, 6, 7)]
    )
    market_data_service_incremental = MarketDataIngestionService(
        security_resolver=resolver, market_data_provider=incremental_provider
    )
    incremental_service = PersistedMarketDataIngestionService(
        market_data_ingestion_service=market_data_service_incremental,
        unit_of_work_factory=uow_factory,
    )

    incremental_result = await incremental_service.ingest_incremental_and_store(
        ticker="NVDA", end_at=datetime(2025, 1, 10, tzinfo=timezone.utc)
    )

    # Historical stored days 2-4 (last stored = day 4); incremental should
    # fetch and persist only days 5-7, never re-downloading days 2-4.
    assert incremental_result.persistence_counts.bars_persisted == 3
    requested_start_at = incremental_provider.calls[0][1]
    assert requested_start_at == datetime(2025, 1, 4, tzinfo=timezone.utc) + timedelta(days=1)

    async with uow_factory() as uow:
        all_bars = await uow.market_bars.list_range(
            canonical_id,
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 10, tzinfo=timezone.utc),
        )
    assert len(all_bars) == 6
