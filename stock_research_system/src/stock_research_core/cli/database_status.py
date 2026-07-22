"""Database status CLI: connection, migration state, and row counts.

    python -m stock_research_core.cli.database_status

Never prints credentials - only the masked connection URL. Exits
non-zero if the database is unavailable.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    check_database_connection,
    create_database_engine,
)


async def _scalar_or_none(engine: AsyncEngine, query: str) -> object:
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(query))
            return result.scalar_one_or_none()
    except Exception:  # noqa: BLE001 - table may not exist yet; treat as "unknown"
        return None


async def _run() -> int:
    settings = DatabaseSettings()
    print(f"Database URL:           {settings.masked_database_url()}")

    engine = create_database_engine(settings)
    try:
        connected = await check_database_connection(engine)
        print(f"Connection:             {'OK' if connected else 'FAILED'}")
        if not connected:
            return 1

        revision = await _scalar_or_none(engine, "SELECT version_num FROM alembic_version")
        print(f"Alembic revision:       {revision or 'unknown (migrations not run?)'}")

        timescale_installed = await _scalar_or_none(
            engine, "SELECT extname FROM pg_extension WHERE extname = 'timescaledb'"
        )
        print(f"TimescaleDB extension:  {'installed' if timescale_installed else 'not installed'}")

        is_hypertable = await _scalar_or_none(
            engine,
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'market_bars'",
        )
        print(f"market_bars hypertable: {'yes' if is_hypertable else 'no'}")

        securities_count = await _scalar_or_none(engine, "SELECT COUNT(*) FROM securities")
        print(f"Securities:             {securities_count if securities_count is not None else 'n/a'}")

        bars_count = await _scalar_or_none(engine, "SELECT COUNT(*) FROM market_bars")
        print(f"Market bars:            {bars_count if bars_count is not None else 'n/a'}")

        tracked_count = await _scalar_or_none(engine, "SELECT COUNT(*) FROM tracked_securities")
        print(f"Tracked securities:     {tracked_count if tracked_count is not None else 'n/a'}")

        print("Recent ingestion runs:")
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text(
                        "SELECT run_id, status, provider_name, started_at "
                        "FROM market_data_ingestion_runs "
                        "ORDER BY started_at DESC LIMIT 5"
                    )
                )
                rows = result.all()
        except Exception:  # noqa: BLE001 - table may not exist yet
            rows = []

        if not rows:
            print("  (none)")
        else:
            for row in rows:
                print(f"  {row.started_at}  {row.status:<12} {row.provider_name}  run={row.run_id}")

        return 0
    finally:
        await engine.dispose()


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
