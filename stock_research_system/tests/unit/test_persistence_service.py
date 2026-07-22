"""Unit tests for `PersistedMarketDataIngestionService`.

Uses a real (Phase 2) `MarketDataIngestionService` wired to fake
`SecurityResolverPort` / `MarketDataPort` implementations, plus fake
repositories and a fake Unit of Work standing in for the database.
No SQLAlchemy or PostgreSQL is involved.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.application.market_data import models as market_data_models_module
from stock_research_core.application.market_data.models import DataQualityIssue
from stock_research_core.application.market_data.service import MarketDataIngestionService
from stock_research_core.application.persistence import models as persistence_models_module
from stock_research_core.application.persistence import ports as persistence_ports_module
from stock_research_core.application.persistence import service as persistence_service_module
from stock_research_core.application.persistence.models import (
    IngestionRunRecord,
    IngestionRunStatus,
)
from stock_research_core.application.persistence.service import (
    PersistedMarketDataIngestionService,
)
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security, TrackedSecurity

START_AT = datetime(2025, 1, 1, tzinfo=timezone.utc)
END_AT = datetime(2025, 1, 10, tzinfo=timezone.utc)


def _bar(security_id: UUID, day: int, **overrides: object) -> MarketBar:
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
    """Mimics YFinanceSecurityResolver: a fresh random ID every call."""

    def __init__(
        self, ticker: str, company_name: str, exchange: Exchange = Exchange.NASDAQ
    ) -> None:
        self._ticker = ticker
        self._company_name = company_name
        self._exchange = exchange

    async def resolve(self, ticker: str | None, company_name: str | None) -> Security:
        return Security(ticker=self._ticker, company_name=self._company_name, exchange=self._exchange)


class _FakeMarketDataProvider:
    provider_name = "fake-provider"

    def __init__(self, bars: list[MarketBar] | None = None) -> None:
        self._bars = bars or []
        self.calls: list[tuple] = []

    async def fetch_bars(
        self, security: Security, start_at: datetime, end_at: datetime, interval: str = "1d"
    ) -> list[MarketBar]:
        self.calls.append((security, start_at, end_at, interval))
        return [bar.model_copy(update={"security_id": security.security_id}) for bar in self._bars]


class FakeSecurityRepository:
    def __init__(self) -> None:
        self._by_ticker_exchange: dict[tuple[str, str], Security] = {}
        self.upsert_calls = 0

    async def upsert(self, security: Security) -> Security:
        self.upsert_calls += 1
        key = (security.ticker, security.exchange.value)
        canonical = self._by_ticker_exchange.get(key)
        if canonical is None:
            canonical = security
        else:
            canonical = canonical.model_copy(
                update={
                    "company_name": security.company_name,
                    "currency": security.currency,
                    "sector": security.sector,
                    "industry": security.industry,
                    "active": security.active,
                }
            )
        self._by_ticker_exchange[key] = canonical
        return canonical

    async def get_by_id(self, security_id: UUID) -> Security | None:
        for security in self._by_ticker_exchange.values():
            if security.security_id == security_id:
                return security
        return None

    async def get_by_ticker(self, ticker: str, exchange: Exchange | None = None) -> Security | None:
        normalized = ticker.strip().upper()
        for (stored_ticker, stored_exchange), security in self._by_ticker_exchange.items():
            if stored_ticker == normalized and (exchange is None or stored_exchange == exchange.value):
                return security
        return None

    def seed(self, security: Security) -> None:
        self._by_ticker_exchange[(security.ticker, security.exchange.value)] = security


class FakeMarketBarRepository:
    def __init__(self) -> None:
        self._bars: dict[tuple, MarketBar] = {}

    async def upsert_many(self, bars: list[MarketBar]) -> int:
        for bar in bars:
            key = (bar.security_id, bar.timestamp, bar.interval, bar.source_name)
            self._bars[key] = bar
        return len(bars)

    async def list_range(
        self,
        security_id: UUID,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> list[MarketBar]:
        matches = [
            bar
            for bar in self._bars.values()
            if bar.security_id == security_id
            and bar.interval == interval
            and start_at <= bar.timestamp <= end_at
            and (source_name is None or bar.source_name == source_name)
        ]
        return sorted(matches, key=lambda bar: bar.timestamp)

    async def get_latest_timestamp(
        self, security_id: UUID, interval: str = "1d", source_name: str | None = None
    ) -> datetime | None:
        matches = [
            bar
            for bar in self._bars.values()
            if bar.security_id == security_id
            and bar.interval == interval
            and (source_name is None or bar.source_name == source_name)
        ]
        return max((bar.timestamp for bar in matches), default=None)

    async def count(self, security_id: UUID, interval: str = "1d") -> int:
        return sum(
            1
            for bar in self._bars.values()
            if bar.security_id == security_id and bar.interval == interval
        )


class FailingMarketBarRepository(FakeMarketBarRepository):
    async def upsert_many(self, bars: list[MarketBar]) -> int:
        raise RuntimeError("simulated database failure")


class FakeIngestionRunRepository:
    def __init__(self) -> None:
        self.runs: dict[UUID, IngestionRunRecord] = {}
        self.saved_issues: dict[UUID, list[DataQualityIssue]] = {}

    async def start(
        self,
        *,
        security_id: UUID,
        provider_name: str,
        interval: str,
        requested_start_at: datetime,
        requested_end_at: datetime,
        is_incremental: bool,
    ) -> IngestionRunRecord:
        run = IngestionRunRecord(
            run_id=uuid4(),
            security_id=security_id,
            provider_name=provider_name,
            interval=interval,
            requested_start_at=requested_start_at,
            requested_end_at=requested_end_at,
            is_incremental=is_incremental,
            status=IngestionRunStatus.STARTED,
            provider_rows_received=0,
            valid_bars_returned=0,
            bars_persisted=0,
            duplicate_rows_removed=0,
            invalid_rows_removed=0,
            started_at=datetime.now(timezone.utc),
        )
        self.runs[run.run_id] = run
        return run

    async def mark_completed(
        self,
        run_id: UUID,
        *,
        provider_rows_received: int,
        valid_bars_returned: int,
        bars_persisted: int,
        duplicate_rows_removed: int,
        invalid_rows_removed: int,
    ) -> IngestionRunRecord:
        updated = self.runs[run_id].model_copy(
            update={
                "status": IngestionRunStatus.COMPLETED,
                "provider_rows_received": provider_rows_received,
                "valid_bars_returned": valid_bars_returned,
                "bars_persisted": bars_persisted,
                "duplicate_rows_removed": duplicate_rows_removed,
                "invalid_rows_removed": invalid_rows_removed,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        self.runs[run_id] = updated
        return updated

    async def mark_no_new_data(
        self,
        run_id: UUID,
        *,
        provider_rows_received: int = 0,
        valid_bars_returned: int = 0,
        duplicate_rows_removed: int = 0,
        invalid_rows_removed: int = 0,
    ) -> IngestionRunRecord:
        updated = self.runs[run_id].model_copy(
            update={
                "status": IngestionRunStatus.NO_NEW_DATA,
                "provider_rows_received": provider_rows_received,
                "valid_bars_returned": valid_bars_returned,
                "bars_persisted": 0,
                "duplicate_rows_removed": duplicate_rows_removed,
                "invalid_rows_removed": invalid_rows_removed,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        self.runs[run_id] = updated
        return updated

    async def mark_failed(self, run_id: UUID, *, error_type: str, error_message: str) -> IngestionRunRecord:
        updated = self.runs[run_id].model_copy(
            update={
                "status": IngestionRunStatus.FAILED,
                "error_type": error_type,
                "error_message": error_message,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        self.runs[run_id] = updated
        return updated

    async def save_quality_issues(self, run_id: UUID, issues: list[DataQualityIssue]) -> int:
        self.saved_issues.setdefault(run_id, []).extend(issues)
        return len(issues)

    async def get_by_id(self, run_id: UUID) -> IngestionRunRecord | None:
        return self.runs.get(run_id)

    async def list_recent(self, security_id: UUID, limit: int = 10) -> list[IngestionRunRecord]:
        matches = [run for run in self.runs.values() if run.security_id == security_id]
        return sorted(matches, key=lambda run: run.started_at, reverse=True)[:limit]


class FakeTrackedSecurityRepository:
    def __init__(self) -> None:
        self.tracked: dict[UUID, TrackedSecurity] = {}

    async def upsert(self, tracked_security: TrackedSecurity) -> TrackedSecurity:
        self.tracked[tracked_security.security_id] = tracked_security
        return tracked_security

    async def get(self, security_id: UUID) -> TrackedSecurity | None:
        return self.tracked.get(security_id)

    async def list_enabled(self) -> list[TrackedSecurity]:
        return [t for t in self.tracked.values() if t.enabled]

    async def set_enabled(self, security_id: UUID, enabled: bool) -> TrackedSecurity:
        updated = self.tracked[security_id].model_copy(update={"enabled": enabled})
        self.tracked[security_id] = updated
        return updated

    async def update_last_successful_update(
        self, security_id: UUID, timestamp: datetime
    ) -> TrackedSecurity:
        updated = self.tracked[security_id].model_copy(update={"last_successful_update_at": timestamp})
        self.tracked[security_id] = updated
        return updated


class FakeUnitOfWork:
    """Wraps a shared set of fake repositories for one `async with` block."""

    def __init__(
        self,
        securities: FakeSecurityRepository,
        market_bars: FakeMarketBarRepository,
        ingestion_runs: FakeIngestionRunRepository,
        tracked_securities: FakeTrackedSecurityRepository,
    ) -> None:
        self.securities = securities
        self.market_bars = market_bars
        self.ingestion_runs = ingestion_runs
        self.tracked_securities = tracked_securities
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None:
            self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeUnitOfWorkFactory:
    """Creates fresh `FakeUnitOfWork` wrappers sharing one set of repository state."""

    def __init__(self, market_bars: FakeMarketBarRepository | None = None) -> None:
        self.securities = FakeSecurityRepository()
        self.market_bars = market_bars or FakeMarketBarRepository()
        self.ingestion_runs = FakeIngestionRunRepository()
        self.tracked_securities = FakeTrackedSecurityRepository()
        self.instances: list[FakeUnitOfWork] = []

    def __call__(self) -> FakeUnitOfWork:
        uow = FakeUnitOfWork(
            self.securities, self.market_bars, self.ingestion_runs, self.tracked_securities
        )
        self.instances.append(uow)
        return uow


def _build_service(
    provider: _FakeMarketDataProvider,
    resolver: _FakeSecurityResolver,
    factory: FakeUnitOfWorkFactory,
) -> PersistedMarketDataIngestionService:
    market_data_service = MarketDataIngestionService(
        security_resolver=resolver, market_data_provider=provider
    )
    return PersistedMarketDataIngestionService(
        market_data_ingestion_service=market_data_service,
        unit_of_work_factory=factory,
    )


async def test_historical_ingestion_persists_security_and_bars() -> None:
    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2), _bar(placeholder_id, 3)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    factory = FakeUnitOfWorkFactory()
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_historical_and_store(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
    )

    assert factory.securities.upsert_calls == 1
    assert result.persistence_counts.bars_persisted == 2
    assert await factory.market_bars.count(result.ingestion_result.security.security_id) == 2


async def test_canonical_security_id_replaces_provider_created_id() -> None:
    canonical_security = Security(ticker="NVDA", company_name="NVIDIA Corporation", exchange=Exchange.NASDAQ)
    factory = FakeUnitOfWorkFactory()
    factory.securities.seed(canonical_security)

    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_historical_and_store(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
    )

    assert result.ingestion_result.security.security_id == canonical_security.security_id


async def test_all_bars_are_rewritten_to_the_canonical_security_id() -> None:
    canonical_security = Security(ticker="NVDA", company_name="NVIDIA Corporation", exchange=Exchange.NASDAQ)
    factory = FakeUnitOfWorkFactory()
    factory.securities.seed(canonical_security)

    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2), _bar(placeholder_id, 3)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_historical_and_store(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
    )

    assert all(
        bar.security_id == canonical_security.security_id for bar in result.ingestion_result.bars
    )


async def test_quality_issues_are_persisted() -> None:
    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    factory = FakeUnitOfWorkFactory()
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_historical_and_store(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
    )

    expected_issue_count = len(result.ingestion_result.quality_report.issues)
    assert result.persistence_counts.quality_issues_persisted == expected_issue_count
    assert factory.ingestion_runs.saved_issues[result.run_id] == result.ingestion_result.quality_report.issues


async def test_tracked_security_created_when_tracking_enabled() -> None:
    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    factory = FakeUnitOfWorkFactory()
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_historical_and_store(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT, track_security=True
    )

    tracked = await factory.tracked_securities.get(result.ingestion_result.security.security_id)
    assert tracked is not None
    assert tracked.enabled is True


async def test_tracking_is_skipped_when_disabled() -> None:
    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    factory = FakeUnitOfWorkFactory()
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_historical_and_store(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT, track_security=False
    )

    tracked = await factory.tracked_securities.get(result.ingestion_result.security.security_id)
    assert tracked is None


async def test_incremental_ingestion_queries_latest_stored_timestamp_and_skips_full_history() -> None:
    stored_security = Security(ticker="NVDA", company_name="NVIDIA Corporation", exchange=Exchange.NASDAQ)
    factory = FakeUnitOfWorkFactory()
    factory.securities.seed(stored_security)
    last_stored_bar_at = datetime(2025, 1, 5, tzinfo=timezone.utc)
    await factory.market_bars.upsert_many([_bar(stored_security.security_id, 5)])
    # Force the seeded bar's exact timestamp to match `last_stored_bar_at`.
    assert await factory.market_bars.get_latest_timestamp(stored_security.security_id) == last_stored_bar_at

    provider = _FakeMarketDataProvider([_bar(stored_security.security_id, 6)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    service = _build_service(provider, resolver, factory)

    await service.ingest_incremental_and_store(ticker="NVDA", end_at=END_AT)

    assert len(provider.calls) == 1
    requested_start_at = provider.calls[0][1]
    assert requested_start_at == last_stored_bar_at + timedelta(days=1)


async def test_no_new_data_creates_the_correct_run_status() -> None:
    stored_security = Security(ticker="NVDA", company_name="NVIDIA Corporation", exchange=Exchange.NASDAQ)
    factory = FakeUnitOfWorkFactory()
    factory.securities.seed(stored_security)
    await factory.market_bars.upsert_many([_bar(stored_security.security_id, 9)])

    # No bars past the last stored bar -> incremental range collapses to nothing.
    provider = _FakeMarketDataProvider([])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_incremental_and_store(
        ticker="NVDA", end_at=datetime(2025, 1, 10, tzinfo=timezone.utc)
    )

    assert result.status == IngestionRunStatus.NO_NEW_DATA
    assert result.persistence_counts.bars_persisted == 0


async def test_persistence_failure_triggers_rollback() -> None:
    failing_bars_repo = FailingMarketBarRepository()
    factory = FakeUnitOfWorkFactory(market_bars=failing_bars_repo)

    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    service = _build_service(provider, resolver, factory)

    with pytest.raises(PersistenceError):
        await service.ingest_historical_and_store(
            ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
        )

    main_uow = factory.instances[0]
    assert main_uow.committed is False
    assert main_uow.rolled_back is True


async def test_failed_main_transaction_does_not_return_completed() -> None:
    failing_bars_repo = FailingMarketBarRepository()
    factory = FakeUnitOfWorkFactory(market_bars=failing_bars_repo)

    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2)])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    service = _build_service(provider, resolver, factory)

    with pytest.raises(PersistenceError):
        await service.ingest_historical_and_store(
            ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
        )

    # The recovery Unit of Work marks the run FAILED in a fresh transaction.
    (run,) = factory.ingestion_runs.runs.values()
    assert run.status == IngestionRunStatus.FAILED
    assert run.status != IngestionRunStatus.COMPLETED


async def test_benchmark_storage_uses_the_requested_ticker() -> None:
    placeholder_id = uuid4()
    provider = _FakeMarketDataProvider([_bar(placeholder_id, 2)])
    resolver = _FakeSecurityResolver("SPY", "SPDR S&P 500 ETF Trust")
    factory = FakeUnitOfWorkFactory()
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_benchmark_and_store(
        benchmark_ticker="SPY", start_at=START_AT, end_at=END_AT
    )

    assert result.ingestion_result.security.ticker == "SPY"


async def test_empty_bar_lists_are_handled_safely() -> None:
    provider = _FakeMarketDataProvider([])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    factory = FakeUnitOfWorkFactory()
    service = _build_service(provider, resolver, factory)

    result = await service.ingest_historical_and_store(
        ticker="NVDA", company_name=None, start_at=START_AT, end_at=END_AT
    )

    assert result.persistence_counts.bars_persisted == 0
    assert result.ingestion_result.bars == []


async def test_service_uses_injected_dependencies() -> None:
    provider = _FakeMarketDataProvider([])
    resolver = _FakeSecurityResolver("NVDA", "NVIDIA Corporation")
    factory = FakeUnitOfWorkFactory()
    market_data_service = MarketDataIngestionService(
        security_resolver=resolver, market_data_provider=provider
    )
    service = PersistedMarketDataIngestionService(
        market_data_ingestion_service=market_data_service, unit_of_work_factory=factory
    )

    assert service._market_data_ingestion_service is market_data_service
    assert service._unit_of_work_factory is factory


def _imported_root_modules(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }


def test_application_persistence_package_does_not_import_sqlalchemy() -> None:
    for module in (
        persistence_service_module,
        persistence_models_module,
        persistence_ports_module,
        market_data_models_module,
    ):
        imported = _imported_root_modules(module)
        assert "sqlalchemy" not in imported
        assert "asyncpg" not in imported


def test_domain_and_contracts_packages_do_not_import_infrastructure_libraries() -> None:
    from stock_research_core.domain import enums as domain_enums_module
    from stock_research_core.domain import models as domain_models_module
    from stock_research_core.contracts import ports as contracts_ports_module

    forbidden = {"sqlalchemy", "asyncpg", "pandas", "yfinance"}
    for module in (domain_enums_module, domain_models_module, contracts_ports_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(forbidden), f"{module.__name__} imports {imported & forbidden}"
