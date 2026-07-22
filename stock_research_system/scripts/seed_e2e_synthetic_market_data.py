"""Seed synthetic OHLCV bars for the Playwright E2E fixture tickers.

The historical-scenario seeder (`seed_historical_market_scenarios.py`)
only ever reads bars already present in `market_bars` - it never calls
yfinance. Real market-data ingestion needs network access that E2E
setup should not depend on, so this script inserts deterministic,
synthetic daily bars directly for two fixture tickers (`E2ETEST`,
`E2EBENCH`) instead. The price path is a pure function of the day
index (no randomness), so scenario window selection is reproducible
across runs.

Usage (PowerShell):

    python scripts/seed_e2e_synthetic_market_data.py
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

_BAR_COUNT = 150
_SOURCE_NAME = "e2e-synthetic"

# Anchored to "now" (not a fixed calendar date) so that virtual-portfolio
# trade execution - which simulates a fill at `requested_at=now()` and
# requires a stored bar strictly AFTER that timestamp - always has one,
# regardless of which real-world day the E2E suite happens to run on.
# 120 days back covers the historical-scenario seeder's need for >=60
# bars before a decision point; 30 days forward covers same-day trades.
_START = datetime.now(timezone.utc) - timedelta(days=120)


def _price_path(day_index: int, base: float, amplitude: float, period: float, drift: float) -> float:
    return base + drift * day_index + amplitude * math.sin(day_index / period)


def _bars_for(security_id, base: float, amplitude: float, period: float, drift: float) -> list[MarketBar]:
    bars = []
    for day in range(_BAR_COUNT):
        close = _price_path(day, base, amplitude, period, drift)
        open_ = _price_path(day - 1, base, amplitude, period, drift) if day > 0 else close
        high = max(open_, close) + 0.5
        low = max(0.01, min(open_, close) - 0.5)
        bars.append(
            MarketBar(
                security_id=security_id,
                timestamp=_START + timedelta(days=day),
                open=round(open_, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(close, 2),
                adjusted_close=round(close, 2),
                volume=1_000_000 + day * 1_000,
                interval="1d",
                source_name=_SOURCE_NAME,
            )
        )
    return bars


async def seed() -> None:
    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            focal = await uow.securities.upsert(
                Security(ticker="E2ETEST", company_name="E2E Test Corp", exchange=Exchange.NASDAQ)
            )
            benchmark = await uow.securities.upsert(
                Security(ticker="E2EBENCH", company_name="E2E Benchmark Index", exchange=Exchange.NYSE)
            )
            await uow.market_bars.upsert_many(_bars_for(focal.security_id, base=100.0, amplitude=15.0, period=18.0, drift=0.15))
            await uow.market_bars.upsert_many(_bars_for(benchmark.security_id, base=200.0, amplitude=8.0, period=25.0, drift=0.05))
            await uow.commit()
        print(f"Seeded {_BAR_COUNT} synthetic daily bars each for E2ETEST and E2EBENCH.")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
