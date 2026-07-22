"""Maps between `MarketBarORM` rows and the `MarketBar` domain model."""

from __future__ import annotations

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.models import MarketBar
from stock_research_core.infrastructure.database.orm.market_bar import MarketBarORM


def market_bar_orm_to_domain(row: MarketBarORM) -> MarketBar:
    """Map a stored `MarketBarORM` row to a validated `MarketBar` domain object.

    Database `NUMERIC` columns come back as `Decimal`; they are converted
    to `float` here since that is what the domain `MarketBar` expects.
    """
    try:
        return MarketBar(
            security_id=row.security_id,
            timestamp=row.timestamp,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            adjusted_close=float(row.adjusted_close),
            volume=int(row.volume),
            interval=row.interval,
            source_name=row.source_name,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored market bar row for security '{row.security_id}' at "
            f"'{row.timestamp}' could not be mapped to a domain MarketBar."
        ) from exc
