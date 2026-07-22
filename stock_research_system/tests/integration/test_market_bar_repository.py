"""PostgreSQL integration tests: MarketBarRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import PersistenceError
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
        source_name="test-source",
    )
    defaults.update(overrides)
    return MarketBar(**defaults)


async def _seed_security(uow_factory, ticker: str = "NVDA") -> Security:
    security = Security(ticker=ticker, company_name=f"{ticker} Inc.", exchange=Exchange.NASDAQ)
    async with uow_factory() as uow:
        stored = await uow.securities.upsert(security)
        await uow.commit()
    return stored


async def test_market_bar_bulk_upsert_inserts_rows(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    bars = [_bar(security.security_id, day) for day in (2, 3, 4)]

    async with uow_factory() as uow:
        inserted = await uow.market_bars.upsert_many(bars)
        await uow.commit()

    assert inserted == 3

    async with uow_factory() as uow:
        count = await uow.market_bars.count(security.security_id)
    assert count == 3


async def test_repeated_market_bar_upsert_does_not_create_duplicates(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    bars = [_bar(security.security_id, 2)]

    async with uow_factory() as uow:
        await uow.market_bars.upsert_many(bars)
        await uow.commit()

    async with uow_factory() as uow:
        await uow.market_bars.upsert_many(bars)
        await uow.commit()

    async with uow_factory() as uow:
        count = await uow.market_bars.count(security.security_id)
    assert count == 1


async def test_repeated_upsert_updates_revised_prices(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    original = _bar(security.security_id, 2, close=100.0, adjusted_close=100.0)

    async with uow_factory() as uow:
        await uow.market_bars.upsert_many([original])
        await uow.commit()

    revised = _bar(security.security_id, 2, high=130.0, close=123.45, adjusted_close=123.40)
    async with uow_factory() as uow:
        await uow.market_bars.upsert_many([revised])
        await uow.commit()

    async with uow_factory() as uow:
        bars = await uow.market_bars.list_range(
            security.security_id,
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 10, tzinfo=timezone.utc),
        )
    assert len(bars) == 1
    assert bars[0].close == pytest.approx(123.45)


async def test_market_bars_returned_in_chronological_order(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    bars = [_bar(security.security_id, day) for day in (5, 2, 4, 3)]

    async with uow_factory() as uow:
        await uow.market_bars.upsert_many(bars)
        await uow.commit()

    async with uow_factory() as uow:
        result = await uow.market_bars.list_range(
            security.security_id,
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 10, tzinfo=timezone.utc),
        )

    timestamps = [bar.timestamp for bar in result]
    assert timestamps == sorted(timestamps)


async def test_latest_timestamp_query_is_correct(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    bars = [_bar(security.security_id, day) for day in (2, 5, 3)]

    async with uow_factory() as uow:
        await uow.market_bars.upsert_many(bars)
        await uow.commit()

    async with uow_factory() as uow:
        latest = await uow.market_bars.get_latest_timestamp(security.security_id)

    assert latest == datetime(2025, 1, 5, tzinfo=timezone.utc)


async def test_range_query_respects_requested_window(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    bars = [_bar(security.security_id, day) for day in range(1, 11)]

    async with uow_factory() as uow:
        await uow.market_bars.upsert_many(bars)
        await uow.commit()

    async with uow_factory() as uow:
        result = await uow.market_bars.list_range(
            security.security_id,
            datetime(2025, 1, 3, tzinfo=timezone.utc),
            datetime(2025, 1, 6, tzinfo=timezone.utc),
        )

    assert [bar.timestamp.day for bar in result] == [3, 4, 5, 6]


async def test_foreign_key_behavior_rejects_unknown_security(uow_factory) -> None:
    orphan_bar = _bar(uuid4(), 2)

    with pytest.raises(PersistenceError):
        async with uow_factory() as uow:
            await uow.market_bars.upsert_many([orphan_bar])
            await uow.commit()
