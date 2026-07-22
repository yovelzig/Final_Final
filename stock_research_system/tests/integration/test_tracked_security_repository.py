"""PostgreSQL integration tests: TrackedSecurityRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import Security, TrackedSecurity

pytestmark = pytest.mark.integration


async def _seed_security(uow_factory, ticker: str = "NVDA") -> Security:
    security = Security(ticker=ticker, company_name=f"{ticker} Inc.", exchange=Exchange.NASDAQ)
    async with uow_factory() as uow:
        stored = await uow.securities.upsert(security)
        await uow.commit()
    return stored


async def test_tracked_security_can_be_inserted_and_updated(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    tracked = TrackedSecurity(security_id=security.security_id)

    async with uow_factory() as uow:
        await uow.tracked_securities.upsert(tracked)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.tracked_securities.get(security.security_id)
    assert fetched is not None
    assert fetched.enabled is True

    async with uow_factory() as uow:
        await uow.tracked_securities.update_last_successful_update(
            security.security_id, datetime(2025, 1, 5, tzinfo=timezone.utc)
        )
        await uow.commit()

    async with uow_factory() as uow:
        updated = await uow.tracked_securities.get(security.security_id)
    assert updated is not None
    assert updated.last_successful_update_at == datetime(2025, 1, 5, tzinfo=timezone.utc)


async def test_list_enabled_returns_only_enabled_securities(uow_factory) -> None:
    enabled_security = await _seed_security(uow_factory, ticker="ENAB")
    disabled_security = await _seed_security(uow_factory, ticker="DSAB")

    async with uow_factory() as uow:
        await uow.tracked_securities.upsert(
            TrackedSecurity(security_id=enabled_security.security_id, enabled=True)
        )
        await uow.tracked_securities.upsert(
            TrackedSecurity(security_id=disabled_security.security_id, enabled=False)
        )
        await uow.commit()

    async with uow_factory() as uow:
        enabled_list = await uow.tracked_securities.list_enabled()

    ids = {tracked.security_id for tracked in enabled_list}
    assert enabled_security.security_id in ids
    assert disabled_security.security_id not in ids


async def test_tracking_requires_existing_security(uow_factory) -> None:
    tracked = TrackedSecurity(security_id=uuid4())

    with pytest.raises(PersistenceError):
        async with uow_factory() as uow:
            await uow.tracked_securities.upsert(tracked)
            await uow.commit()
