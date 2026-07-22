"""Maps between `SecurityORM` rows and the `Security` domain model."""

from __future__ import annotations

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import Security
from stock_research_core.infrastructure.database.orm.security import SecurityORM


def security_orm_to_domain(row: SecurityORM) -> Security:
    """Map a stored `SecurityORM` row to a validated `Security` domain object."""
    try:
        return Security(
            security_id=row.security_id,
            ticker=row.ticker,
            company_name=row.company_name,
            exchange=Exchange(row.exchange),
            currency=row.currency,
            sector=row.sector,
            industry=row.industry,
            active=row.active,
        )
    except (ValidationError, ValueError) as exc:
        raise DatabaseMappingError(
            f"Stored security row '{row.security_id}' could not be mapped to a domain Security."
        ) from exc
