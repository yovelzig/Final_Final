"""Unit tests for ORM-to-domain mapper functions.

These instantiate ORM classes as plain Python objects (no database
connection, no PostgreSQL required) and check the resulting domain
objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.enums import Exchange
from stock_research_core.infrastructure.database.mappers.market_bar_mapper import (
    market_bar_orm_to_domain,
)
from stock_research_core.infrastructure.database.mappers.security_mapper import (
    security_orm_to_domain,
)
from stock_research_core.infrastructure.database.mappers.tracked_security_mapper import (
    tracked_security_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.market_bar import MarketBarORM
from stock_research_core.infrastructure.database.orm.security import SecurityORM
from stock_research_core.infrastructure.database.orm.tracked_security import TrackedSecurityORM


def _security_row(**overrides: object) -> SecurityORM:
    defaults: dict = dict(
        security_id=uuid4(),
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        exchange="NASDAQ",
        currency="USD",
        sector="Technology",
        industry="Semiconductors",
        active=True,
    )
    defaults.update(overrides)
    return SecurityORM(**defaults)


def _market_bar_row(**overrides: object) -> MarketBarORM:
    defaults: dict = dict(
        security_id=uuid4(),
        timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc),
        interval="1d",
        source_name="yfinance",
        open=Decimal("100.50"),
        high=Decimal("105.25"),
        low=Decimal("99.75"),
        close=Decimal("102.00"),
        adjusted_close=Decimal("101.90"),
        volume=123456,
    )
    defaults.update(overrides)
    return MarketBarORM(**defaults)


def _tracked_security_row(**overrides: object) -> TrackedSecurityORM:
    defaults: dict = dict(
        security_id=uuid4(),
        enabled=True,
        monitoring_started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        last_successful_update_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        next_scheduled_update_at=None,
        alert_threshold_probability_change=Decimal("0.100000"),
        alert_threshold_expected_return_change=Decimal("0.030000"),
    )
    defaults.update(overrides)
    return TrackedSecurityORM(**defaults)


def test_security_orm_to_domain_maps_all_fields() -> None:
    row = _security_row()

    security = security_orm_to_domain(row)

    assert security.security_id == row.security_id
    assert security.ticker == "NVDA"
    assert security.exchange == Exchange.NASDAQ
    assert security.sector == "Technology"
    assert security.industry == "Semiconductors"


def test_market_bar_orm_to_domain_converts_decimals_to_floats() -> None:
    row = _market_bar_row()

    bar = market_bar_orm_to_domain(row)

    assert isinstance(bar.open, float)
    assert isinstance(bar.adjusted_close, float)
    assert bar.open == pytest.approx(100.50)
    assert bar.adjusted_close == pytest.approx(101.90)


def test_market_bar_orm_to_domain_preserves_uuid_and_utc_timestamp() -> None:
    security_id = uuid4()
    row = _market_bar_row(security_id=security_id)

    bar = market_bar_orm_to_domain(row)

    assert bar.security_id == security_id
    assert bar.timestamp.tzinfo is not None
    assert bar.timestamp == datetime(2025, 1, 2, tzinfo=timezone.utc)


def test_market_bar_orm_to_domain_rejects_invalid_ohlc() -> None:
    row = _market_bar_row(high=Decimal("50.00"))  # high below close/open -> invalid

    with pytest.raises(DatabaseMappingError):
        market_bar_orm_to_domain(row)


def test_security_orm_to_domain_rejects_invalid_exchange() -> None:
    row = _security_row(exchange="NOT_A_REAL_EXCHANGE")

    with pytest.raises(DatabaseMappingError):
        security_orm_to_domain(row)


def test_tracked_security_orm_to_domain_maps_all_fields() -> None:
    row = _tracked_security_row()

    tracked = tracked_security_orm_to_domain(row)

    assert tracked.security_id == row.security_id
    assert tracked.enabled is True
    assert isinstance(tracked.alert_threshold_probability_change, float)
    assert tracked.alert_threshold_probability_change == pytest.approx(0.10)
    assert tracked.monitoring_started_at.tzinfo is not None
