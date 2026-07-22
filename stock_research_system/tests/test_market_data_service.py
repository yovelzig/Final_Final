"""Offline tests for MarketDataIngestionService using fake Protocol implementations."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone

from stock_research_core.application.exceptions import MarketDataUnavailableError
from stock_research_core.application.market_data import service as service_module
from stock_research_core.application.market_data.service import MarketDataIngestionService
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security

START_AT = datetime(2025, 1, 1, tzinfo=timezone.utc)
END_AT = datetime(2025, 1, 10, tzinfo=timezone.utc)


def _security() -> Security:
    return Security(ticker="NVDA", company_name="NVIDIA Corporation", exchange=Exchange.NASDAQ)


def _bar(security_id, day: int) -> MarketBar:
    return MarketBar(
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


class _FakeSecurityResolver:
    def __init__(self, security: Security) -> None:
        self._security = security
        self.calls: list[tuple[str | None, str | None]] = []

    async def resolve(self, ticker: str | None, company_name: str | None) -> Security:
        self.calls.append((ticker, company_name))
        return self._security


class _FakeMarketDataProvider:
    provider_name = "fake-provider"

    def __init__(self, bars: list[MarketBar]) -> None:
        self._bars = bars
        self.calls: list[tuple] = []

    async def fetch_bars(self, security, start_at, end_at, interval="1d") -> list[MarketBar]:
        self.calls.append((security, start_at, end_at, interval))
        return self._bars


class _NoNewDataMarketDataProvider:
    provider_name = "fake-provider"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def fetch_bars(self, security, start_at, end_at, interval="1d") -> list[MarketBar]:
        self.calls.append((security, start_at, end_at, interval))
        raise MarketDataUnavailableError("no new bars")


async def test_historical_ingestion_resolves_security_and_fetches_bars():
    security = _security()
    resolver = _FakeSecurityResolver(security)
    bars = [_bar(security.security_id, 2), _bar(security.security_id, 3)]
    provider = _FakeMarketDataProvider(bars)
    service = MarketDataIngestionService(resolver, provider)

    result = await service.ingest_historical(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
    )

    assert resolver.calls == [("NVDA", None)]
    assert len(provider.calls) == 1
    assert result.security == security
    assert len(result.bars) == 2


async def test_historical_result_is_not_incremental():
    security = _security()
    resolver = _FakeSecurityResolver(security)
    provider = _FakeMarketDataProvider([_bar(security.security_id, 2)])
    service = MarketDataIngestionService(resolver, provider)

    result = await service.ingest_historical(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
    )

    assert result.is_incremental is False


async def test_incremental_ingestion_requests_only_dates_after_last_stored_bar():
    security = _security()
    resolver = _FakeSecurityResolver(security)
    provider = _FakeMarketDataProvider([_bar(security.security_id, 6)])
    service = MarketDataIngestionService(resolver, provider)
    last_stored_bar_at = datetime(2025, 1, 5, tzinfo=timezone.utc)

    await service.ingest_incremental(
        security=security, last_stored_bar_at=last_stored_bar_at, end_at=END_AT
    )

    requested_start_at = provider.calls[0][1]
    assert requested_start_at == last_stored_bar_at + timedelta(days=1)


async def test_incremental_result_is_incremental():
    security = _security()
    resolver = _FakeSecurityResolver(security)
    provider = _FakeMarketDataProvider([_bar(security.security_id, 6)])
    service = MarketDataIngestionService(resolver, provider)

    result = await service.ingest_incremental(
        security=security,
        last_stored_bar_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
        end_at=END_AT,
    )

    assert result.is_incremental is True


async def test_benchmark_ingestion_uses_supplied_benchmark_ticker():
    security = _security()
    resolver = _FakeSecurityResolver(security)
    provider = _FakeMarketDataProvider([_bar(security.security_id, 2)])
    service = MarketDataIngestionService(resolver, provider)

    await service.ingest_benchmark(benchmark_ticker="SPY", start_at=START_AT, end_at=END_AT)

    assert resolver.calls == [("SPY", None)]


async def test_no_new_data_incremental_request_returns_empty_result_with_warning():
    security = _security()
    resolver = _FakeSecurityResolver(security)
    provider = _NoNewDataMarketDataProvider()
    service = MarketDataIngestionService(resolver, provider)

    result = await service.ingest_incremental(
        security=security,
        last_stored_bar_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
        end_at=END_AT,
    )

    assert result.bars == []
    assert result.is_incremental is True
    assert any(issue.code == "NO_NEW_DATA" for issue in result.quality_report.issues)


async def test_service_uses_injected_dependencies():
    security = _security()
    resolver = _FakeSecurityResolver(security)
    provider = _FakeMarketDataProvider([_bar(security.security_id, 2)])
    service = MarketDataIngestionService(resolver, provider)

    assert service._security_resolver is resolver
    assert service._market_data_provider is provider


def test_application_service_does_not_import_yfinance():
    tree = ast.parse(inspect.getsource(service_module))
    imported_root_modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "yfinance" not in imported_root_modules
    assert "pandas" not in imported_root_modules
