"""Wait for the configured database to accept connections.

Usage (PowerShell):

    python scripts/wait_for_database.py

Retries a bounded number of times, then exits non-zero. Never prints
credentials - only the masked connection URL.
"""

from __future__ import annotations

import asyncio
import sys

from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import check_database_connection
from stock_research_core.infrastructure.database.engine import create_database_engine

_MAX_ATTEMPTS = 30
_DELAY_SECONDS = 2.0


async def _wait() -> bool:
    settings = DatabaseSettings()
    print(f"Waiting for database at {settings.masked_database_url()} ...")

    engine = create_database_engine(settings)
    try:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            if await check_database_connection(engine):
                print(f"Database is ready (attempt {attempt}/{_MAX_ATTEMPTS}).")
                return True
            print(f"Attempt {attempt}/{_MAX_ATTEMPTS}: not ready yet.")
            await asyncio.sleep(_DELAY_SECONDS)
    finally:
        await engine.dispose()

    print(f"Database did not become ready after {_MAX_ATTEMPTS} attempts.", file=sys.stderr)
    return False


def main() -> None:
    ready = asyncio.run(_wait())
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
