"""PostgreSQL integration tests: schema/migration checks and SecurityRepository."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import Security

pytestmark = pytest.mark.integration

_EXPECTED_TABLES = {
    "securities",
    "market_bars",
    "market_data_ingestion_runs",
    "market_data_quality_issues",
    "tracked_securities",
    "alembic_version",
}


async def test_alembic_migration_reaches_head(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(text("SELECT version_num FROM alembic_version"))
        revision = result.scalar_one()
    # Head advances as new migrations are added (0011_ragas_learning_quality
    # added the Phase 13 quality-evaluation schema on top of
    # 0010_langgraph_orchestrator).
    assert revision == "0011_ragas_learning_quality"


async def test_all_tables_exist(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_conn: sa_inspect(sync_conn).get_table_names()
        )
    assert _EXPECTED_TABLES.issubset(set(table_names))


async def test_timescaledb_extension_is_installed(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
        )
        assert result.scalar_one_or_none() == "timescaledb"


async def test_market_bars_is_a_hypertable(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT hypertable_name FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = 'market_bars'"
            )
        )
        assert result.scalar_one_or_none() == "market_bars"


async def test_security_upsert_inserts_a_security(uow_factory) -> None:
    security = Security(ticker="aapl", company_name="Apple Inc.", exchange=Exchange.NASDAQ)

    async with uow_factory() as uow:
        stored = await uow.securities.upsert(security)
        await uow.commit()

    assert stored.security_id == security.security_id
    assert stored.ticker == "AAPL"

    async with uow_factory() as uow:
        fetched = await uow.securities.get_by_id(security.security_id)
    assert fetched is not None
    assert fetched.ticker == "AAPL"


async def test_repeated_security_upsert_does_not_create_duplicates(
    uow_factory, test_engine: AsyncEngine
) -> None:
    security = Security(
        ticker="MSFT", company_name="Microsoft Corporation", exchange=Exchange.NASDAQ
    )

    async with uow_factory() as uow:
        await uow.securities.upsert(security)
        await uow.commit()

    async with uow_factory() as uow:
        await uow.securities.upsert(security)
        await uow.commit()

    async with test_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT COUNT(*) FROM securities WHERE ticker = 'MSFT'")
        )
        count = result.scalar_one()
    assert count == 1


async def test_conflict_upsert_preserves_canonical_security_id(uow_factory) -> None:
    original = Security(ticker="GOOGL", company_name="Alphabet Inc.", exchange=Exchange.NASDAQ)
    async with uow_factory() as uow:
        canonical = await uow.securities.upsert(original)
        await uow.commit()

    duplicate_domain_object = Security(
        ticker="GOOGL", company_name="Alphabet Inc. (renamed)", exchange=Exchange.NASDAQ
    )
    assert duplicate_domain_object.security_id != canonical.security_id

    async with uow_factory() as uow:
        result = await uow.securities.upsert(duplicate_domain_object)
        await uow.commit()

    assert result.security_id == canonical.security_id
    assert result.company_name == "Alphabet Inc. (renamed)"


async def test_get_by_id_returns_none_when_missing(uow_factory) -> None:
    async with uow_factory() as uow:
        result = await uow.securities.get_by_id(uuid4())
    assert result is None
